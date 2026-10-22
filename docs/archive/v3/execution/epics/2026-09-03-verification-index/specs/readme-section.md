# F2 `readme-section` — the "Verification program" section of README.md — spec

**Depends on F1** (`review-index`): the section reads its numbers from `docs/superpowers/dogfood/README.md`.

**Goal.** `README.md` gains a `## Verification program` section (placed before the last existing `##` section):
three sentences — what the program is (stages 1–8, each a dogfood cycle against native Claude Code mechanisms),
a link to `docs/superpowers/dogfood/README.md`, and the counts taken from that file's footer ("N review files,
A APPROVED"). The numbers must equal the footer at the time of writing; a test-shaped check is not required
(docs-only), but the reviewer verifies the equality by reading both files.

**Files.** Modify `README.md`. The run first regenerates `docs/superpowers/dogfood/README.md` with
`scripts/compound-v-dogfood-index.sh` (a separate job, its own lane) so F1's own review files are counted before
the numbers are read — pre-flight 1A measured the committed footer one row stale. The link is a real markdown
link whose target is written root-relative without a leading slash (a leading-slash link is exempt from the
dead-link CI gate, so a broken one would merge unnoticed).

**Acceptance criteria.** The section exists once; its link resolves to an existing file; its two numbers equal
the footer of `docs/superpowers/dogfood/README.md`; `/usr/bin/python3 -B scripts/lint-frontmatter.py .` green.
