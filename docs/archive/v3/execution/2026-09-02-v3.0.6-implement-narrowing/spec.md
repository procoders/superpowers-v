# v3.0.5 — routing that routes

**Problem.** Compound V has carried a tier vocabulary (`deep`/`standard`/`light`) since
1.1. It is validated by the manifest validator, documented in three places, and until
3.0.5 it never reached `agent()`. `resolve_job_model` was called only for external
backends, where `--model` is a required CLI argument; on `backend: claude` — every job in
every real run — `opts.model` was never set and every agent inherited the session model.

**Acceptance.** Two jobs in one wave, each declaring only a `tier` and no `model`, resolve
to two different concrete models, and both complete through the normal gate.
