export type StepMark = 'pass' | 'fail' | 'stale' | 'missing' | 'waived' | 'error'

/** `compound-v.py hud` output: the active run's stage, receipt state and measured cost. */
export type Hud = {
  run: string
  stage: string
  tier: string
  steps: Record<string, StepMark>
  review_round: number
  outcome: string
  /** null while no cost-state was read, or a model's cost is unknown: drawn as `$?`. */
  cost_usd: number | null
  /** 'estimate' while it includes requests the CLI has not priced yet (mid-turn): drawn as `~$`;
   *  'unpriced' when a request's model or price modifier is not in the cited price list. */
  cost_basis: 'cli' | 'estimate' | 'unpriced'
}

/** One account rate-limit window, as percent used: when this run was first seen, and now. */
export type Quota = { kind: string; start: number; now: number; resetsAt?: string }

export type Band = {
  hud: Hud | null
  quota: Quota[]
  /** Set when the reader could not answer; drawn dim, never as data. */
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'compound-v': { band: Band | null }
  }
}
