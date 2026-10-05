import { expect, mock, test } from 'claude-code/testing'

const RUN = {
  id: '2026-10-05-demo',
  phase: 'DISPATCHED',
  run_dir: '/repo/docs/superpowers/execution/2026-10-05-demo',
  done: 1,
  total: 3,
  running: 1,
  state_error: false,
  waves: [
    {
      n: '1',
      jobs: [
        { id: 'docs-core', status: 'done', backend: 'claude', tier: 'deep', attention: false },
        { id: 'docs-skills', status: 'running', backend: 'codex', tier: 'standard', attention: false },
      ],
    },
    { n: '2', jobs: [{ id: 'review', status: 'pending', backend: 'claude', tier: 'deep', attention: false }] },
  ],
}

const BAND = { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100 }

for (const surface of ['terminal', 'desktop'] as const) {
  test(`draws the active run and toasts a stalled job once (${surface})`, async ($, on) => {
    const clock = mock.clock(on)
    const toasts: string[] = []
    const calls: string[] = []
    let hud: unknown = { run: RUN }
    let mtime = 1

    on('session.start', () => ({ cwd: '/repo' }))
  on('env.get', () => ({ value: undefined }))
  on('session.cwd', () => ({ value: '/repo' }))
    on('fs.stat', ($$, e) => ({
      value: {
        kind: String(e.path).endsWith('/execution') ? ('dir' as const) : ('file' as const),
        size: 1,
        mtimeMs: String(e.path).endsWith('state.json') ? mtime : 1,
        isLink: false,
      },
    }))
    on('process.run', ($$, e) => {
      calls.push(e.argv.join(' '))
      const isLiveness = e.argv.some(a => a.endsWith('compound-v-liveness.py'))
      const stdout = isLiveness
        ? JSON.stringify({ 'docs-skills': { liveness: 'STALE', last_progress_s: 660 } })
        : JSON.stringify(e.argv.includes('--run') ? { run: { ...RUN, phase: 'MERGED', done: 3, running: 0 } } : hud)

      return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    })
    on('ui.toast', ($$, e) => {
      toasts.push(e.text)

      return { value: undefined }
    })
    on('ui.render', () => ({ type: 'Box', props: {}, children: [] }))

    await $.session.start({ cwd: '/repo', surface, isInteractive: true })
    await clock.settle()

    const ui = await $.ui.mount({ plugin: 'superpowers-v', surface, component: 'AbovePrompt', props: BAND })
    expect(await ui.find({ text: /2026-10-05-demo/ })).toBeDefined()
    expect(await ui.find({ text: /done 1\/3/ })).toBeDefined()
    expect(await ui.find({ text: /docs-skills.*codex·standard.*STALE.*11m/ })).toBeDefined()
    expect(await ui.find({ text: /wave 2\/2/ })).toBeDefined()
    expect(toasts).toEqual(['Compound V · docs-skills is STALE, no progress for 11m'])

    // the same state again: no second toast
    mtime = 2
    await clock.advance(5_000)
    expect(toasts).toHaveLength(1)

    // the run leaves the active set: one closing line, then nothing
    hud = { run: null }
    mtime = 3
    await clock.advance(5_000)
    await ui.redraw()
    expect(await ui.find({ text: /2026-10-05-demo · MERGED · 3\/3 done/ })).toBeDefined()
    expect(await ui.find({ text: /docs-skills/ })).toBeUndefined()

    await clock.advance(65_000)
    await ui.redraw()
    expect(await ui.find({ text: /2026-10-05-demo/ })).toBeUndefined()
  })
}

test('draws nothing when no run is active', async ($, on) => {
  const clock = mock.clock(on)
  on('session.start', () => ({ cwd: '/repo' }))
  on('env.get', () => ({ value: undefined }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('fs.stat', ($$, e) => ({
    value: {
      kind: String(e.path).endsWith('/execution') ? ('dir' as const) : ('file' as const),
      size: 1,
      mtimeMs: 1,
      isLink: false,
    },
  }))
  on('process.run', () => ({
    value: { exitCode: 0, stdout: '{"run": null}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
  }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine band'] }))

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.settle()
  const ui = await $.ui.mount({ plugin: 'superpowers-v', surface: 'terminal', component: 'AbovePrompt', props: BAND })
  expect(await ui.drawn()).toMatchObject({ type: 'Text' })
})

test('CV_DISABLED_HOOKS=run-band starts no poller', async ($, on) => {
  const clock = mock.clock(on)
  let runs = 0
  on('session.start', () => ({ cwd: '/repo' }))
  on('env.get', () => ({ value: 'memory-refresh, run-band' }))
  on('process.run', () => {
    runs += 1

    return { value: { exitCode: 0, stdout: '{"run": null}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.session.start({ cwd: '/repo', surface: 'terminal', isInteractive: true })
  await clock.advance(60_000)
  expect(runs).toBe(0)
})

test('a repository with no execution directory never starts the reader', async ($, on) => {
  const clock = mock.clock(on)
  let runs = 0
  on('session.start', () => ({ cwd: '/elsewhere' }))
  on('env.get', () => ({ value: undefined }))
  on('session.cwd', () => ({ value: '/elsewhere' }))
  on('fs.stat', () => {
    throw new Error('ENOENT')
  })
  on('process.run', () => {
    runs += 1

    return { value: { exitCode: 0, stdout: '{"run": null}', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })

  await $.session.start({ cwd: '/elsewhere', surface: 'terminal', isInteractive: true })
  await clock.advance(120_000)
  expect(runs).toBe(0)
})
