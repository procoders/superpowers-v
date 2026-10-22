# Dogfood 1 — the derived test scope, in a real run

3.1.0 made `test_scope` derived rather than a hardcoded `full`. Selftests pin the
function. This run pins the *pipeline*: a manifest that declares an `impacted_map`, a job
that declares no `test_scope`, and the question of what the run actually resolves.
