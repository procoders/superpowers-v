import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionRateLimit } from 'claude-code'

import type { Band, Hud, Quota, StepMark } from '../types'

const band = atom({ plugin: 'compound-v', key: 'band' } as const, null)

const TICK_MS = 5_000
const IDLE_MS = 30_000
const READER_TIMEOUT_MS = 8_000
const MAX_ROUNDS = 2
const RUNS = 'docs/compound-v/runs'

// The amiainative.dev palette, one meaning each.
const C = {
  brand: '#DC02DF',
  pass: '#34D399',
  warn: '#FFC53D',
  bad: '#FB2C36',
  idle: '#575868',
  waived: '#6565F2',
}

const MARK: Record<StepMark, { glyph: string; color: string }> = {
  pass: { glyph: '●', color: C.pass },
  missing: { glyph: '○', color: C.idle },
  stale: { glyph: '◐', color: C.warn },
  fail: { glyph: '✕', color: C.bad },
  error: { glyph: '!', color: C.warn },
  waived: { glyph: '◇', color: C.waived },
}

const EMPTY: Band = { hud: null, quota: [], error: null }

const QUOTA_KEY = 'quota:'
const KEPT_BASELINES = 20
const QUOTA_TITLE = 'account quota since this run appeared'
const QUOTA_LABEL: Record<string, string> = { five_hour: '5h', seven_day: '7d', spend_limit: 'spend' }

async function readHud($: EngineInterface, cwd: string): Promise<Hud | null | undefined> {
  const script = `${$.plugin.root}/scripts/compound-v.py`
  const argv = ['python3', '-I', '-B', script, 'hud', '--repo', cwd]
  try {
    const sid = await $.session.id()
    if (sid) {
      argv.push('--session', sid)
    }
  } catch {
    // no session id: the CLI falls back to the newest open run
  }
  try {
    const { exitCode, stdout } = await $.process.run(argv, { timeoutMs: READER_TIMEOUT_MS })
    if (exitCode !== 0) {
      return undefined
    }
    const doc = JSON.parse(stdout) as Partial<Hud>

    return typeof doc === 'object' && doc !== null && typeof doc.run === 'string' ? (doc as Hud) : null
  } catch {
    return undefined
  }
}

/**
 * The account's rate-limit windows against where they stood when this run was first seen.
 * Each run keeps its own baseline in `$.store` (`quota:<run>`), so another session or a late
 * measurement for an earlier run never resets it, and a restarted session keeps it.
 * These are ACCOUNT windows: anything else running on the account moves them too.
 */
async function quotaFor($: EngineInterface, runId: string, windows: SessionRateLimit[]): Promise<Quota[]> {
  if (windows.length === 0) {
    return []
  }
  const key = `${QUOTA_KEY}${runId}`
  const saved = await $.store.get(key)
  const base: Record<string, number> = typeof saved === 'object' && saved !== null ? { ...(saved as Record<string, number>) } : {}
  let hasNew = false
  for (const w of windows) {
    if (typeof base[w.kind] !== 'number') {
      base[w.kind] = w.percentUsed
      hasNew = true
    }
  }
  if (hasNew) {
    await $.store.set(key, base)
    await prune($)
  }

  return windows.map(w => ({ kind: w.kind, start: base[w.kind] ?? w.percentUsed, now: w.percentUsed, resetsAt: w.resetsAt }))
}

/** Keeps the newest baselines only; the store is one capped file shared by every session. */
async function prune($: EngineInterface): Promise<void> {
  const keys = (await $.store.keys()).filter(k => k.startsWith(QUOTA_KEY))
  for (const k of keys.slice(0, Math.max(0, keys.length - KEPT_BASELINES))) {
    await $.store.delete(k)
  }
}

/** One read when a run first appears; after that `session.measure` pushes every move. */
async function readQuota($: EngineInterface, runId: string): Promise<Quota[]> {
  try {
    return await quotaFor($, runId, (await $.session.usage()).rateLimits)
  } catch {
    return []
  }
}

/** `5h +6.5% → 41%`; after a window reset (now below the start) only where it stands. */
function quotaText(q: Quota): string {
  const label = QUOTA_LABEL[q.kind] ?? q.kind
  const delta = Math.round((q.now - q.start) * 10) / 10

  return delta >= 0 ? `${label} +${delta}% → ${q.now}%` : `${label} → ${q.now}%`
}

function cost(hud: Hud): string {
  return hud.cost_usd === null ? '$?' : `${hud.cost_basis === 'estimate' ? '~' : ''}$${hud.cost_usd.toFixed(2)}`
}

// Module variables start over on a hot reload: the next tick re-reads everything.
const mem = { isBusy: false, mtime: -1, readAt: -IDLE_MS, quotaRun: '' }

async function step($: EngineInterface): Promise<void> {
  const now = await $.clock.now()
  const cwd = await $.session.cwd()
  let mtime: number
  try {
    const st = await $.fs.stat(`${cwd}/${RUNS}`)
    if (st.kind !== 'dir') {
      throw new Error('not a dir')
    }
    mtime = st.mtimeMs
  } catch {
    // A repository that never ran Compound V: one stat per tick and no reader process.
    if ((await read($, band))?.hud) {
      await update($, band, () => EMPTY)
    }

    return
  }
  // The reader re-hashes the tree, so it runs when a record moved, else every 30 s for staleness.
  if (mtime === mem.mtime && now - mem.readAt < IDLE_MS) {
    return
  }
  mem.mtime = mtime
  mem.readAt = now
  const hud = await readHud($, cwd)
  if (hud === undefined) {
    await update($, band, b => ({ ...(b ?? EMPTY), error: 'run record unreadable' }))

    return
  }
  let fresh: Quota[] | undefined
  if (hud !== null && mem.quotaRun !== hud.run) {
    mem.quotaRun = hud.run
    fresh = await readQuota($, hud.run)
  }
  await update($, band, b => ({
    hud,
    quota: hud === null ? [] : (fresh ?? (b?.hud?.run === hud.run ? b.quota : [])),
    error: null,
  }))
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

  on('session.measure', async ($, e, next) => {
    if (e.changed.includes('rateLimits')) {
      try {
        const run = (await read($, band))?.hud?.run
        if (run !== undefined) {
          const quota = await quotaFor($, run, e.rateLimits)
          await update($, band, b => (b !== null && b.hud?.run === run ? { ...b, quota } : b))
        }
      } catch {
        // a missed reading is replaced by the next one
      }
    }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const b = await read($, band)
    const beneath = await next(e)
    if (e.props.hasSurvey || b === null || b.hud === null) {
      return beneath
    }
    const { Box, Text } = $.ui.resolve(e)
    const hud = b.hud
    const width = e.props.bodyColumns
    const steps = Object.entries(hud.steps)
    const waived = steps.filter(([, m]) => m === 'waived').map(([s]) => s)
    const rows = [
      <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
        <Text bold color={C.brand}>
          V
        </Text>
        <Text bold wrap="truncate-end">
          {hud.run}
        </Text>
        <Text dimColor>{`· ${hud.stage} (${hud.tier}) ·`}</Text>
        {steps.map(([name, m]) => (
          <Text color={MARK[m]?.color}>{`${name} ${MARK[m]?.glyph ?? '?'}`}</Text>
        ))}
        <Text dimColor>{`· round ${hud.review_round}/${MAX_ROUNDS} ·`}</Text>
        <Text>{cost(hud)}</Text>
        {b.error !== null && <Text color={C.warn}>{b.error}</Text>}
      </Box>,
    ]
    if (hud.outcome !== 'pending' || waived.length > 0) {
      const parts = [hud.outcome !== 'pending' ? `outcome ${hud.outcome}` : '']
      if (waived.length > 0) {
        parts.push(`waived by the user: ${waived.join(', ')}`)
      }
      const color = hud.outcome === 'verified' ? C.pass : hud.outcome === 'failed' ? C.bad : C.warn
      rows.push(
        <Box flexDirection="row" paddingLeft={2}>
          <Text color={color}>{parts.filter(p => p !== '').join(' · ')}</Text>
        </Box>,
      )
    }
    if (b.quota.length > 0) {
      const texts = b.quota.map(quotaText)
      const room = width - 2 - texts.reduce((n, t) => n + t.length + 2, 0)
      rows.push(
        <Box flexDirection="row" justifyContent="space-between" columnGap={2}>
          <Text dimColor wrap="truncate-end">
            {room >= QUOTA_TITLE.length ? QUOTA_TITLE : 'quota'}
          </Text>
          <Box flexDirection="row" columnGap={2}>
            {b.quota.map((q, i) => (
              <Text color={q.now >= 95 ? C.bad : q.now >= 80 ? C.warn : undefined} dimColor={q.now < 80}>
                {texts[i]}
              </Text>
            ))}
          </Box>
        </Box>,
      )
    }

    return (
      <Box flexDirection="column">
        <Box flexDirection="column" paddingX={1} width={width}>
          {rows}
        </Box>
        {beneath}
      </Box>
    )
  })
}
