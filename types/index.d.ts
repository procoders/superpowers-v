export type HudJob = {
  id: string
  status: string
  backend: string | null
  tier: string | null
  model: string | null
  effort: string | null
  attention: boolean
}

export type HudWave = { n: string | null; jobs: HudJob[] }

export type HudRun = {
  id: string
  phase: string
  run_dir: string
  done: number
  total: number
  running: number
  /** Callers the lane guard could not tie to a job: their writes were not lane-checked. */
  unresolved: number
  state_error: boolean
  waves: HudWave[]
}

/** One account rate-limit window, as percent used: when this run was first seen, and now. */
export type Quota = { kind: string; start: number; now: number; resetsAt?: string }

export type Live = { liveness: string; idle_s: number | null }

export type Band = {
  run: HudRun | null
  /** job id -> liveness; null when the probe did not answer (ages print as `?`). */
  live: Record<string, Live> | null
  /** `<job>:<reason>` keys already toasted, so a transition is announced once. */
  alerted: string[]
  /** Account quota movement while this run has been open; empty off a subscription. */
  quota: Quota[]
  /** The closing line of a run that just left the active set, and when it expires (ms). */
  closing: { text: string; until: number } | null
  /** Set when the reader could not answer; drawn dim, never as data. */
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'superpowers-v': { band: Band | null; spin: number }
  }
}
