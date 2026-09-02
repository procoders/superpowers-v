# CLI Machine-Readable Output Knowledge Base

Maintained by Compound V Phase 1B advisor. Append at the bottom on each pass.

---

## Updated 2026-09-02 — dual-consumer `--json` on an existing rendered command

Context: adding/hardening `--json` on a command whose other mode prints one prose line for a
human or a model. Generalized from `compound-v-dashboard.py resume`.

### The dual-consumer contract (reusable checklist)

| Rule | Why | Failure if ignored |
|---|---|---|
| Machine output on **stdout**, everything else on **stderr** | stdout is the API contract | Diagnostics corrupt the parse |
| Machine mode **always emits a document** (`{"active": []}`), even when empty | Consumers test the document, not the byte count | See "emptiness asymmetry" below |
| One render path, one vocabulary owner | Rendered line and JSON must never disagree | Two sources of truth drift silently |
| Version or freeze the key set | Field names become a contract on the second consumer | Skew breaks consumers with no signal |
| Compact/NDJSON for streams, pretty only for a TTY | `while read` consumers need one object per line | Pretty-printing breaks line-oriented readers |

**Sources, each fetched and quoted verbatim (2026-09-02):**

- [Command Line Interface Guidelines (clig.dev)](https://clig.dev/) — *"The primary output for
  your command should go to `stdout`. Anything that is machine readable should also go to
  `stdout`—this is where piping sends things by default."* and *"Log messages, errors, and so
  on should all be sent to `stderr`."* Also: *"Display output as formatted JSON if `--json` is
  passed."*
- [Designing a CLI for AI agents (Arcjet)](https://blog.arcjet.com/designing-a-cli-for-ai-agents/)
  — *"The most important design constraint is that commands, flags, and output fields become a
  contract once agents start using them."* (verbatim, confirmed on fetch)
- [Building a CLI That Works for Humans and Machines (openstatus)](https://www.openstatus.dev/blog/building-cli-for-human-and-agents)
  — supports only one claim here, verbatim: *"Every command supports `--json`. Not as an
  afterthought, as a parallel code path that returns complete, nested data structures."*
  **Correction logged:** an earlier draft of this entry cited this article for the
  stdout/stderr split and for JSON Lines guidance. On fetch it says neither. That grounding
  belongs to clig.dev above.
- **Not fetched, therefore not cited for any claim:** the Heroku CLI Style Guide and
  RFC 9457 both surfaced in search results for this topic and may well be relevant, but this
  pass did not read them.

### Emptiness asymmetry — the most common port bug

A rendered mode signals "nothing to report" by **printing nothing**. A JSON mode signals it
with an **empty collection inside a present document**. Shell callers written against the
first (`[ -n "$out" ]`) invert when pointed at the second: the document is always non-empty,
so the caller reports activity for zero records.

**Rule:** when porting a consumer from rendered to structured output, the emptiness test must
be rewritten at the same time, never carried over.

### argparse and version skew

An older build of the tool rejects a newly added flag with
`error: unrecognized arguments: --json` on **stderr**, **exit code 2**
([argparse docs](https://docs.python.org/3/library/argparse.html) — invalid arguments print to
stderr and exit 2). Any caller that may run against a lagging install (plugin caches, vendored
copies, distro packages) must treat *non-zero exit + empty stdout* as a normal degrade path,
not an error.

Two further argparse notes worth pinning:
- A subparser group without `required=True` yields `args.cmd is None` on a bare invocation;
  the common fallback is `parser.print_help()`, which writes **to stdout** — polluting the
  machine channel on exactly the path a confused caller takes.
- `exit_on_error=False` (Python 3.9+) does **not** cover unrecognized options
  ([cpython#85427](https://github.com/python/cpython/issues/85427)).

### `jq` is not ambient

`jq` ships by default on **neither macOS nor Linux**; it is a package-manager or binary
install on every platform ([jq installation wiki](https://github.com/jqlang/jq/wiki/Installation),
[downloads](https://jqlang.org/download/)). It has zero runtime dependencies, so it is trivial
to *ship*, but never assume it is *present*.

Consequence for shell consumers: a `jq` call inside a script running under `set -e` converts a
missing optional tool into total script failure. Either guard (`command -v jq >/dev/null || …`)
or parse in a language runtime the script already hard-requires. **If the script already
shells into Python, rendering in Python strictly dominates parsing in bash.**

### Emitting JSON *for a language model* is usually the wrong interface

When the consumer of a string is an LLM (a context-injection banner, a prompt fragment), prose
is already the native format. Converting structured data to JSON and back to prose adds a
parse step, a dependency, and a skew mode for no gain — unless the consumer computes something
new from the structure (filtering, ranking, thresholding). Ask what the structure *enables*
before adding it.
