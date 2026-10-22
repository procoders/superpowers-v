# Does the reviewer actually consult V-memory?

3.3.3 added a Step 0 to five agents telling them to query the recall layer. It was
verified by selftests and by a before/after comparison of the index, not by watching
an agent do it.

`spec-reviewer` is the ONE agent Engine C spawns by role (`agentType`), so it is the
only one a dispatch can test end to end. This run does that.
