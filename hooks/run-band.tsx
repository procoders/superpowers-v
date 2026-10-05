import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Band, HudJob, HudRun, Live } from '../types'

// Compound V run band. Everything it prints was read off disk by the plugin's own
// readers: statuses from state.json and backend/tier from manifest.yaml (via
// `compound-v-dashboard.py hud`), liveness and idle seconds from
// `compound-v-liveness.py`. No percent, no ETA: neither is measured.

const band = atom({ plugin: 'superpowers-v', key: 'band' } as const, null)

const TICK_MS = 5_000
const IDLE_POLL_EVERY = 6 // ticks: with no run tracked, ask the reader every 30 s
const LIVENESS_MS = 30_000
const CLOSING_MS = 60_000
const READER_TIMEOUT_MS = 8_000
const LIVENESS_TIMEOUT_MS = 15_000
const STALLED = ['STALE', 'DEAD']

const EMPTY: Band = { run: null, live: null, alerted: [], closing: null, error: null }

async function scriptPath($: EngineInterface, name: string): Promise<string | null> {
  const path = `${$.plugin.root}/scripts/${name}`
  try {
    return (await $.fs.stat(path)).kind === 'file' ? path : null
  } catch {
    return null
  }
}

async function readHud($: EngineInterface, runId?: string): Promise<{ run: HudRun | null } | null> {
  const script = await scriptPath($, 'compound-v-dashboard.py')
  if (script === null) {
    return null
  }
  const argv = ['python3', '-B', script, 'hud', ...(runId ? ['--run', runId] : [])]
  try {
    const { exitCode, stdout } = await $.process.run(argv, { timeoutMs: READER_TIMEOUT_MS })
    if (exitCode !== 0) {
      return null
    }
    const doc = JSON.parse(stdout) as { run: HudRun | null }

    return typeof doc === 'object' && doc !== null && 'run' in doc ? doc : null
  } catch {
    return null
  }
}

async function readLiveness($: EngineInterface, runDir: string): Promise<Record<string, Live> | null> {
  const script = await scriptPath($, 'compound-v-liveness.py')
  if (script === null) {
    return null
  }
  try {
    const { stdout } = await $.process.run(['python3', '-B', script, '--json', runDir], {
      timeoutMs: LIVENESS_TIMEOUT_MS,
    })
    const doc = JSON.parse(stdout) as Record<string, { liveness?: string; last_progress_s?: number | null }>
    const out: Record<string, Live> = {}
    for (const [id, one] of Object.entries(doc)) {
      if (one && typeof one.liveness === 'string') {
        out[id] = {
          liveness: one.liveness,
          idle_s: typeof one.last_progress_s === 'number' ? one.last_progress_s : null,
        }
      }
    }

    return out
  } catch {
    return null
  }
}

function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return '?'
  }
  if (seconds < 60) {
    return `${seconds}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`
  }

  return `${Math.floor(seconds / 3600)}h${Math.floor((seconds % 3600) / 60)}m`
}

function lane(job: HudJob): string {
  return job.backend ? `${job.backend}${job.tier ? `·${job.tier}` : ''}` : ''
}

/** Why a job needs a person, or null. The key is what a toast is deduplicated on. */
function trouble(job: HudJob, live: Record<string, Live> | null): string | null {
  if (job.attention) {
    return job.status.toUpperCase()
  }
  const state = live?.[job.id]?.liveness
  if (job.status === 'running' && state && STALLED.includes(state)) {
    return state
  }

  return null
}

function closingLine(run: HudRun): string {
  const bad = run.waves.flatMap(w => w.jobs).filter(j => j.attention)
  const tail = bad.length > 0 ? ` · ${bad.map(j => `${j.id} ${j.status}`).join(', ')}` : ''

  return `${run.id} · ${run.phase} · ${run.done}/${run.total} done${tail}`
}

// The poller's own bookkeeping. Module variables start over on a hot reload, which is
// what we want: the next tick re-reads everything.
const mem = { isBusy: false, ticks: 0, stateMtime: -1, livenessAt: 0 }

async function step($: EngineInterface): Promise<void> {
  const now = await $.clock.now()
  const cur = (await read($, band)) ?? EMPTY
  mem.ticks += 1

  if (cur.closing !== null && now > cur.closing.until) {
    await update($, band, b => ({ ...(b ?? EMPTY), closing: null }))
  }

  if (cur.run === null) {
    if (mem.ticks % IDLE_POLL_EVERY !== 1) {
      return
    }
    // A repository that never ran Compound V has no execution directory: one stat every
    // 30 s, and no reader process at all.
    try {
      const root = `${await $.session.cwd()}/docs/superpowers/execution`
      if ((await $.fs.stat(root)).kind !== 'dir') {
        return
      }
    } catch {
      return
    }
    const doc = await readHud($)
    if (doc?.run) {
      mem.stateMtime = -1
      mem.livenessAt = 0
      await update($, band, b => ({ ...(b ?? EMPTY), run: doc.run, live: null, alerted: [], error: null }))

      // Same tick, tracked path: liveness and the first toasts should not wait 5 s.
      return step($)
    }

    return
  }

  const tracked = cur.run
  let mtime = -2
  try {
    mtime = (await $.fs.stat(`${tracked.run_dir}/state.json`)).mtimeMs
  } catch {
    // gone or unreadable: fall through to the reader, which says which
  }
  const hasChanged = mtime !== mem.stateMtime
  const isLivenessDue = tracked.running > 0 && now - mem.livenessAt >= LIVENESS_MS
  if (!hasChanged && !isLivenessDue) {
    return
  }

  let run: HudRun = tracked
  if (hasChanged) {
    mem.stateMtime = mtime
    const doc = await readHud($)
    if (doc === null) {
      await update($, band, b => ({ ...(b ?? EMPTY), error: 'run state unreadable' }))

      return
    }
    if (doc.run === null || doc.run.id !== tracked.id) {
      // The tracked run left the active set: say how it ended, for a minute.
      const last = (await readHud($, tracked.id))?.run ?? tracked
      mem.stateMtime = -1
      mem.livenessAt = 0
      await update($, band, () => ({
        run: doc.run,
        live: null,
        alerted: [],
        closing: { text: closingLine(last), until: now + CLOSING_MS },
        error: null,
      }))

      return
    }
    run = doc.run
  }

  let live = cur.live
  if (run.running > 0 && (isLivenessDue || hasChanged)) {
    live = await readLiveness($, run.run_dir)
    mem.livenessAt = now
  } else if (run.running === 0) {
    live = {}
  }

  const alerted = [...cur.alerted]
  for (const job of run.waves.flatMap(w => w.jobs)) {
    const why = trouble(job, live)
    const key = `${job.id}:${why}`
    if (why !== null && !alerted.includes(key)) {
      alerted.push(key)
      const idle = live?.[job.id]?.idle_s
      const since = STALLED.includes(why) && idle != null ? `, no progress for ${age(idle)}` : ''
      $.ui.toast(`Compound V · ${job.id} is ${why}${since}`, { timeoutMs: 8_000 })
    }
  }

  await update($, band, b => ({ ...(b ?? EMPTY), run, live, alerted, error: null }))
}

/** `CV_DISABLED_HOOKS=run-band` turns the band off, like any other Compound V hook. */
async function isDisabled($: EngineInterface): Promise<boolean> {
  const list = (await $.env.get('CV_DISABLED_HOOKS')) ?? ''

  return list
    .split(',')
    .map(name => name.trim())
    .includes('run-band')
}

async function tick($: EngineInterface): Promise<void> {
  if (mem.isBusy) {
    return
  }
  mem.isBusy = true
  try {
    await step($)
  } catch {
    // a failed tick is skipped; the next one starts clean
  } finally {
    mem.isBusy = false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    if (!(await isDisabled($))) {
      $.clock.every(TICK_MS, () => {
        void tick($)
      })
      void tick($)
    }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const b = await read($, band)
    const beneath = await next(e)
    if (e.props.hasSurvey || b === null || (b.run === null && b.closing === null)) {
      return beneath
    }

    const { Box, Text } = $.ui.resolve(e)
    const rows = []

    if (b.closing !== null) {
      rows.push(
        <Text dimColor wrap="truncate-end">
          <Text bold>V</Text> {b.closing.text}
        </Text>,
      )
    }

    if (b.run !== null) {
      const run = b.run
      const waveCount = run.waves.filter(w => w.n !== null && w.n !== '?').length
      rows.push(
        <Text wrap="truncate-end">
          <Text bold>V</Text> {run.id} <Text dimColor>·</Text> {run.phase} <Text dimColor>·</Text> done{' '}
          {run.done}/{run.total}
          {b.error !== null && <Text dimColor> · {b.error}</Text>}
          {run.state_error && <Text dimColor> · state.json did not parse</Text>}
        </Text>,
      )
      for (const wave of run.waves) {
        const label = wave.n === null ? '' : wave.n === '?' ? 'unplaced ' : `wave ${wave.n}/${waveCount} `
        rows.push(
          <Text wrap="truncate-end">
            {'  '}
            <Text dimColor>{label}</Text>
            {wave.jobs.map(job => {
              const why = trouble(job, b.live)
              const live = b.live?.[job.id]
              const isDone = job.status === 'done' || job.status === 'success'
              const isRunning = job.status === 'running'
              const mark = why !== null ? '!' : isDone ? '✓' : isRunning ? '…' : '·'
              const idle = isRunning ? ` ${b.live === null ? '?' : age(live?.idle_s)}` : ''

              return (
                <Text color={why !== null ? 'red' : undefined} dimColor={why === null && !isRunning}>
                  {mark} {job.id}
                  {lane(job) !== '' && <Text dimColor> {lane(job)}</Text>}
                  {why !== null ? ` ${why}` : ''}
                  {idle}
                  {'   '}
                </Text>
              )
            })}
          </Text>,
        )
      }
    }

    return (
      <Box flexDirection="column">
        {rows}
        {beneath}
      </Box>
    )
  })
}
