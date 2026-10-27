import { expect, mock, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

const HUD = {
  run: '20261022-101500-salon-booking',
  stage: 'verify',
  tier: 'full',
  steps: { tests: 'pass', review: 'missing', live: 'fail', scope: 'error' },
  review_round: 1,
  outcome: 'pending',
  cost_usd: 2.5,
}

const BAND = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 9 },
  view: {},
}
const OK = (stdout: string) => ({
  value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

type Setup = {
  hud?: unknown
  hasRunsDir?: boolean
  fiveHour?: () => number
  disabled?: string
  store?: Record<string, unknown>
  seen?: { usage: number }
}

function stub(on: Parameters<TestBody>[1], s: Setup) {
  const calls: string[][] = []
  const store: Record<string, unknown> = s.store ?? {}
  on('session.start', () => ({ cwd: '/repo' }))
  on('env.get', () => ({ value: s.disabled }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.id', () => ({ value: 's1' }))
  on('fs.stat', () => {
    if (s.hasRunsDir === false) {
      throw new Error('ENOENT')
    }

    return { value: { kind: 'dir' as const, size: 1, mtimeMs: 1, isLink: false } }
  })
  on('process.run', ($$, e) => {
    calls.push([...e.argv])

    return OK(JSON.stringify(s.hud ?? {}))
  })
  on('session.usage', () => {
    if (s.seen) {
      s.seen.usage += 1
    }
    const rateLimits = s.fiveHour ? [{ kind: 'five_hour', percentUsed: s.fiveHour() }] : []

    return { value: { startedAt: 0, context: {} as never, rateLimits } }
  })
  on('store.get', ($$, e) => ({ value: store[e.key] }))
  on('store.set', ($$, e) => {
    store[e.key] = e.value

    return { value: undefined }
  })
  on('store.keys', () => ({ value: Object.keys(store) }))
  on('store.delete', ($$, e) => {
    delete store[e.key]

    return { value: undefined }
  })
  on('session.measure', ($$, e) => ({ changed: e.changed }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine band'] }))

  return calls
}

for (const surface of ['terminal', 'desktop'] as const) {
  test(`shows missing steps (${surface})`, async ($, on) => {
    const clock = mock.clock(on)
    const calls = stub(on, { hud: HUD })
    await $.session.start({ cwd: '/repo', surface, isInteractive: true })
    await clock.settle()
    const ui = await $.ui.mount({ plugin: 'compound-v', surface, component: 'AbovePrompt', props: BAND })
    expect(await ui.find({ type: 'Text', text: /^20261022-101500-salon-booking$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^· verify \(full\) ·$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^tests ●$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^review ○$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^live ✕$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^scope !$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^· round 1\/2 ·$/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /^\$2\.50$/ })).toBeDefined()
    expect(await ui.find({ text: /outcome/ })).toBeUndefined()
    expect(calls[0]).toEqual(expect.arrayContaining(['hud', '--repo', '/repo', '--session', 's1']))
  })
}

test('renders nothing without a run', async ($, on) => {
  const clock = mock.clock(on)
  stub(on, { hud: {} })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'compound-v', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.drawn()).toMatchObject({ type: 'Text' })
})

test('shows ? when cost is null, and the outcome and waivers on a second line', async ($, on) => {
  const clock = mock.clock(on)
  stub(on, {
    hud: { ...HUD, cost_usd: null, outcome: 'incomplete', steps: { tests: 'pass', live: 'waived', scope: 'stale' } },
  })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'compound-v', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.find({ type: 'Text', text: /^\$\?$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^live ◇$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^scope ◐$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^outcome incomplete · waived by the user: live$/ })).toBeDefined()
})

test('quota footer labelled account quota, moved by session.measure', async ($, on) => {
  const clock = mock.clock(on)
  stub(on, { hud: HUD, fiveHour: () => 30 })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  await $.session.measure({
    context: {} as never,
    rateLimits: [{ kind: 'five_hour', percentUsed: 36.5 }],
    changed: ['rateLimits'],
  })
  const ui = await $.ui.mount({ plugin: 'compound-v', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.find({ type: 'Text', text: /^account quota since this run appeared$/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /^5h \+6\.5% → 36\.5%$/ })).toBeDefined()
})

test('a narrow band keeps the quota and shortens its label', async ($, on) => {
  const clock = mock.clock(on)
  stub(on, { hud: HUD, fiveHour: () => 30 })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount({
    plugin: 'compound-v',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: { ...BAND, bodyColumns: 40 },
  })
  expect(await ui.find({ type: 'Text', text: /^quota$/ })).toBeDefined()
  expect(await ui.find({ text: /account quota/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /^5h \+0% → 30%$/ })).toBeDefined()
})

test('each run keeps its own baseline, whatever another session stores', async ($, on) => {
  const clock = mock.clock(on)
  const store: Record<string, unknown> = { [`quota:${HUD.run}`]: { five_hour: 30 } }
  stub(on, { hud: HUD, fiveHour: () => 35, store })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  store['quota:other-session-run'] = { five_hour: 38 }
  await $.session.measure({
    context: {} as never,
    rateLimits: [{ kind: 'five_hour', percentUsed: 40 }],
    changed: ['rateLimits'],
  })
  const ui = await $.ui.mount({ plugin: 'compound-v', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.find({ type: 'Text', text: /^5h \+10% → 40%$/ })).toBeDefined()
  expect(store[`quota:${HUD.run}`]).toEqual({ five_hour: 30 })
  expect(store['quota:other-session-run']).toEqual({ five_hour: 38 })
})

test('quota is read once per run, never polled, even with no rate-limit windows', async ($, on) => {
  const clock = mock.clock(on)
  const seen = { usage: 0 }
  stub(on, { hud: HUD, seen })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  await clock.advance(120_000)
  expect(seen.usage).toBe(1)
})

test('polls the reader every 30 s while the run records stay still', async ($, on) => {
  const clock = mock.clock(on)
  const calls = stub(on, { hud: HUD })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  expect(calls).toHaveLength(1)
  await clock.advance(25_000)
  expect(calls).toHaveLength(1)
  await clock.advance(5_000)
  expect(calls).toHaveLength(2)
})

test('a repository with no run records never starts the reader', async ($, on) => {
  const clock = mock.clock(on)
  const calls = stub(on, { hud: HUD, hasRunsDir: false })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.advance(120_000)
  expect(calls).toHaveLength(0)
})

test('CV_DISABLED_HOOKS=run-band starts no poller', async ($, on) => {
  const clock = mock.clock(on)
  const calls = stub(on, { hud: HUD, disabled: 'memory-refresh, run-band' })
  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.advance(60_000)
  expect(calls).toHaveLength(0)
})
