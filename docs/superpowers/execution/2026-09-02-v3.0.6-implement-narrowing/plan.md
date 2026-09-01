# Plan

One wave, two jobs, disjoint lanes. Each writes one file naming the tier that routed it.
The proof is not the file content — it is the emitted `opts.model` and the recorded
`model_source`, which the run's own dispatch script carries.
