import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Band, HudJob, HudRun, Live, Quota } from '../types'

// Compound V run band. Everything it prints was read off disk by the plugin's own
// readers: statuses from state.json and backend/tier from manifest.yaml (via
// `compound-v-dashboard.py hud`), liveness and idle seconds from
// `compound-v-liveness.py`. No percent, no ETA: neither is measured.

const band = atom({ plugin: 'superpowers-v', key: 'band' } as const, null)
const spin = atom({ plugin: 'superpowers-v', key: 'spin' } as const, 0)

const TICK_MS = 5_000
const IDLE_POLL_EVERY = 6 // ticks: with no run tracked, ask the reader every 30 s
const LIVENESS_MS = 30_000
const CLOSING_MS = 60_000
const READER_TIMEOUT_MS = 8_000
const LIVENESS_TIMEOUT_MS = 15_000
const STALLED = ['STALE', 'DEAD']
const SPIN_MS = 500
const SPIN_FRAMES = ['◐', '◓', '◑', '◒']
const TABLE_MAX_JOBS = 8 // more than this and the band falls back to one line per wave

// The amiainative.dev palette (its CSS custom properties), one meaning each.
const C = {
  brand: '#DC02DF', // --color-magenta: the V mark
  run: '#1195F2', // --color-blue: running
  done: '#34D399', // --color-emerald: done
  warn: '#FFC53D', // the site's amber: five minutes without progress
  bad: '#FB2C36', // --color-red-500: stalled, dead, blocked
  route: '#6565F2', // --color-violet: the backend a job runs on
  idle: '#575868', // --color-slate: queued
}
const GLYPH_WIDTH = 2
const BACKEND_WIDTH = 12 // "antigravity" + 1

const EMPTY: Band = { run: null, live: null, alerted: [], quota: [], closing: null, error: null }

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

const QUOTA_LABEL: Record<string, string> = { five_hour: '5h', seven_day: '7d', spend_limit: 'spend' }

/**
 * The account's rate-limit windows now, against where they stood when this run was first
 * seen. The baseline lives in `$.store` under the run id, so a restarted session keeps it.
 * These are ACCOUNT windows: anything else running on the account moves them too.
 */
async function readQuota($: EngineInterface, runId: string): Promise<Quota[]> {
  let windows: { kind: string; percentUsed: number; resetsAt?: string }[] = []
  try {
    windows = (await $.session.usage()).rateLimits
  } catch {
    return []
  }
  if (windows.length === 0) {
    return []
  }
  let saved = (await $.store.get('quota')) as { runId?: string; base?: Record<string, number> } | undefined
  if (!saved || saved.runId !== runId || typeof saved.base !== 'object' || saved.base === null) {
    saved = { runId, base: {} }
  }
  const base = saved.base ?? {}
  let hasNew = false
  for (const w of windows) {
    if (typeof base[w.kind] !== 'number') {
      base[w.kind] = w.percentUsed
      hasNew = true
    }
  }
  if (hasNew) {
    await $.store.set('quota', { runId, base })
  }

  return windows.map(w => ({ kind: w.kind, start: base[w.kind] ?? w.percentUsed, now: w.percentUsed, resetsAt: w.resetsAt }))
}

/** `5h +6.5% → 41%`; after a window reset (now below the start) only where it stands. */
function quotaText(q: Quota): string {
  const label = QUOTA_LABEL[q.kind] ?? q.kind
  const delta = Math.round((q.now - q.start) * 10) / 10

  return delta >= 0 ? `${label} +${delta}% → ${q.now}%` : `${label} → ${q.now}%`
}

/** What a job runs on, after the backend name: the resolved model, else its tier. */
function route(job: HudJob): string {
  const what = job.model ?? job.tier ?? ''

  return job.effort ? `${what} · ${job.effort}` : what
}

type Look = { glyph: string; color: string; note: string; isLoud: boolean }

/** One job's mark, color and right-hand note. `frame` animates a running job. */
function look(job: HudJob, live: Record<string, Live> | null, frame: number): Look {
  const why = trouble(job, live)
  const idle = live?.[job.id]?.idle_s
  if (why !== null) {
    const since = STALLED.includes(why) ? ` · ${age(idle)}` : ''

    return { glyph: '✕', color: C.bad, note: `${why}${since}`, isLoud: true }
  }
  if (job.status === 'done' || job.status === 'success') {
    return { glyph: '●', color: C.done, note: 'done', isLoud: false }
  }
  if (job.status === 'running') {
    const isSlow = typeof idle === 'number' && idle >= 300
    const note = live === null ? '?' : age(idle)

    return { glyph: SPIN_FRAMES[frame % SPIN_FRAMES.length] ?? '◐', color: isSlow ? C.warn : C.run, note, isLoud: true }
  }

  return { glyph: '○', color: C.idle, note: 'queued', isLoud: false }
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

function closingLine(run: HudRun, quota: Quota[]): string {
  const bad = run.waves.flatMap(w => w.jobs).filter(j => j.attention)
  const tail = bad.length > 0 ? ` · ${bad.map(j => `${j.id} ${j.status}`).join(', ')}` : ''
  const spent = quota.length > 0 ? ` · account quota ${quota.map(quotaText).join(', ')}` : ''
  const loose = run.unresolved > 0 ? ` · ${run.unresolved} caller(s) not lane-checked` : ''

  return `${run.id} · ${run.phase} · ${run.done}/${run.total} done${tail}${loose}${spent}`
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
      await update($, band, b => ({ ...(b ?? EMPTY), run: doc.run, live: null, alerted: [], quota: [], error: null }))

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
  const quota = await readQuota($, tracked.id)
  if (!hasChanged && !isLivenessDue) {
    if (JSON.stringify(quota) !== JSON.stringify(cur.quota)) {
      await update($, band, b => ({ ...(b ?? EMPTY), quota }))
    }

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
        quota: [],
        closing: { text: closingLine(last, quota), until: now + CLOSING_MS },
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

  const looseKey = `unresolved:${run.unresolved}`
  if (run.unresolved > 0 && !alerted.includes(looseKey)) {
    alerted.push(looseKey)
    $.ui.toast(`Compound V · ${run.unresolved} caller(s) wrote without a lane check`, { timeoutMs: 8_000 })
  }

  await update($, band, b => ({ ...(b ?? EMPTY), run, live, alerted, quota, error: null }))
}

/** `CV_DISABLED_HOOKS=run-band` turns the band off, like any other Compound V hook. */
async function isDisabled($: EngineInterface): Promise<boolean> {
  const list = (await $.env.get('CV_DISABLED_HOOKS')) ?? ''

  return list
    .split(',')
    .map(name => name.trim())
    .includes('run-band')
}

/** Advances the running-job glyph, only while a tracked run has a job running. */
async function spinTick($: EngineInterface): Promise<void> {
  const cur = await read($, band)
  if (cur?.run && cur.run.running > 0) {
    await update($, spin, n => (n + 1) % SPIN_FRAMES.length)
  }
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
      $.clock.every(SPIN_MS, () => {
        void spinTick($)
      })
      void tick($)
    }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const b = await read($, band)
    const frame = await read($, spin)
    const beneath = await next(e)
    if (e.props.hasSurvey || b === null || (b.run === null && b.closing === null)) {
      return beneath
    }

    const { Box, Text } = $.ui.resolve(e)
    const rows = []

    if (b.closing !== null) {
      rows.push(
        <Box flexDirection="row" columnGap={1}>
          <Text bold color={C.brand}>
            V
          </Text>
          <Text dimColor wrap="truncate-end">
            {b.closing.text}
          </Text>
        </Box>,
      )
    }

    if (b.run !== null) {
      const run = b.run
      const jobs = run.waves.flatMap(w => w.jobs)
      const cell = jobs.length > 24 ? '▰' : '▰▰'
      const waveCount = run.waves.filter(w => w.n !== null && w.n !== '?').length
      const nameWidth = Math.min(28, Math.max(...jobs.map(j => j.id.length), 4) + 2)
      const isTable = jobs.length <= TABLE_MAX_JOBS && jobs.length + 3 <= e.props.maxRows

      // Header: who and where on the left; one segment per job and the count on the right.
      rows.push(
        <Box flexDirection="row" justifyContent="space-between" columnGap={2}>
          <Box flexDirection="row" columnGap={1}>
            <Text bold color={C.brand}>
              V
            </Text>
            <Text bold wrap="truncate-end">
              {run.id}
            </Text>
            <Text dimColor>{run.phase.toLowerCase()}</Text>
            {b.error !== null && <Text color={C.warn}>{b.error}</Text>}
            {run.state_error && <Text color={C.warn}>state.json did not parse</Text>}
          </Box>
          <Box flexDirection="row" columnGap={1}>
            <Box flexDirection="row">
              {jobs.map(job => {
                const l = look(job, b.live, 0)

                return (
                  <Text color={l.color}>{cell}</Text>
                )
              })}
            </Box>
            <Text bold>
              {run.done}/{run.total}
            </Text>
          </Box>
        </Box>,
      )

      for (const wave of run.waves) {
        const label = wave.n === null ? '' : wave.n === '?' ? 'unplaced' : `wave ${wave.n}/${waveCount}`
        if (isTable) {
          rows.push(
            <Box flexDirection="row" alignItems="flex-start">
              <Box width={10}>
                <Text dimColor>{label}</Text>
              </Box>
              <Box flexDirection="column" flexGrow={1}>
                {wave.jobs.map(job => {
                  const l = look(job, b.live, frame)

                  return (
                    <Box flexDirection="row" justifyContent="space-between" columnGap={2}>
                      <Box flexDirection="row">
                        <Box width={GLYPH_WIDTH}>
                          <Text color={l.color}>{l.glyph}</Text>
                        </Box>
                        <Box width={nameWidth}>
                          <Text bold={l.isLoud} dimColor={!l.isLoud} wrap="truncate-end">
                            {job.id}
                          </Text>
                        </Box>
                        <Box width={BACKEND_WIDTH}>
                          {job.backend !== null && <Text color={C.route}>{job.backend}</Text>}
                        </Box>
                        {route(job) !== '' && <Text dimColor>{route(job)}</Text>}
                      </Box>
                      <Text color={l.isLoud ? l.color : undefined} dimColor={!l.isLoud}>
                        {l.note}
                      </Text>
                    </Box>
                  )
                })}
              </Box>
            </Box>,
          )
        } else {
          rows.push(
            <Box flexDirection="row" alignItems="flex-start">
              <Box width={10}>
                <Text dimColor>{label}</Text>
              </Box>
              <Box flexDirection="row" flexWrap="wrap" columnGap={2} flexGrow={1}>
                {wave.jobs.map(job => {
                  const l = look(job, b.live, frame)

                  return (
                    <Box flexDirection="row" columnGap={1}>
                      <Text color={l.color}>{l.glyph}</Text>
                      <Text bold={l.isLoud} dimColor={!l.isLoud}>
                        {job.id}
                      </Text>
                      {l.isLoud && <Text color={l.color}>{l.note}</Text>}
                    </Box>
                  )
                })}
              </Box>
            </Box>,
          )
        }
      }
    }

    if (b.run !== null && b.run.unresolved > 0) {
      rows.push(
        <Box flexDirection="row" columnGap={1}>
          <Text color={C.warn}>⚠</Text>
          <Text color={C.warn} wrap="truncate-end">
            {b.run.unresolved} caller(s) wrote without a lane check — the guard could not tell whose they were
          </Text>
          <Text dimColor>lane-guard-unresolved.jsonl</Text>
        </Box>,
      )
    }

    if (b.run !== null && b.quota.length > 0) {
      rows.push(
        <Box flexDirection="row" justifyContent="space-between" columnGap={2}>
          <Text dimColor>account quota since this run appeared</Text>
          <Box flexDirection="row" columnGap={2}>
            {b.quota.map(q => (
              <Text color={q.now >= 95 ? C.bad : q.now >= 80 ? C.warn : undefined} dimColor={q.now < 80}>
                {quotaText(q)}
              </Text>
            ))}
          </Box>
        </Box>,
      )
    }

    return (
      <Box flexDirection="column">
        <Box flexDirection="column" paddingX={1}>
          {rows}
        </Box>
        {beneath}
      </Box>
    )
  })
}
