from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import hooks, receipts, run  # noqa: E402


class HooksTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = helpers.make_repo(self.tmp, {"src/a.js": "a\n",
                                                 ".claude/compound-v.json": "{}\n"})
        self._key = receipts.KEY_PATH
        receipts.KEY_PATH = helpers.key_path(self.repo)
        self.state = self.tmp / "state"

    def tearDown(self):
        receipts.KEY_PATH = self._key
        self._tmp.cleanup()

    def start(self, stage="build", session="s1", **kw):
        rec = run.start(self.repo, tier="light", request="fix typo", session_id=session, **kw)
        rec.update({"test_cmd": "true", "change_set": ["src/**"]})
        rec["stage"] = stage
        run.save(self.repo, rec)
        return rec

    def stop(self, session="s1", active=False, transcript=None):
        return hooks.stop_hook({"hook_event_name": "Stop", "session_id": session,
                                "stop_hook_active": active, "transcript_path": transcript,
                                "cwd": str(self.repo)}, self.repo, state_dir=self.state)

    def prompt(self, text, session="s1"):
        return hooks.prompt_hook({"hook_event_name": "UserPromptSubmit", "session_id": session,
                                  "prompt": text, "cwd": str(self.repo)}, self.repo,
                                 self.state)

    def load(self, rec):
        return run.load(self.repo, rec["id"])

    def verify(self, rec):
        for step in ("tests", "scope"):
            receipts.run_step(self.repo, self.load(rec), step)

    def test_stop_blocks_once_then_incomplete(self):
        rec = self.start()
        out = self.stop()
        self.assertEqual("block", out["decision"])
        self.assertIn("missing tests, scope", out["reason"])
        self.assertIn("/compound-v:verify", out["reason"])
        self.assertIsNone(self.stop())
        self.assertEqual("incomplete", self.load(rec)["outcome"])

    def test_stop_failed_outcome_when_a_step_failed(self):
        rec = self.start()
        rec["test_cmd"] = "false"
        run.save(self.repo, rec)
        self.verify(rec)
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())
        self.assertEqual("failed", self.load(rec)["outcome"])

    def test_stop_reblocks_after_new_edit(self):
        self.start()
        self.assertEqual("block", self.stop()["decision"])
        helpers.write(self.repo, {"src/a.js": "a2\n"})
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())

    def test_stop_hook_active_never_blocks(self):
        rec = self.start()
        self.assertIsNone(self.stop(active=True))
        self.assertIsNone(self.load(rec)["outcome"])

    def test_stop_verified_closes_run(self):
        rec = self.start()
        self.verify(rec)
        self.assertIsNone(self.stop())
        rec = self.load(rec)
        self.assertEqual(("verified", "done"), (rec["outcome"], rec["stage"]))

    def test_stop_after_done_never_blocks(self):
        rec = self.start()
        self.verify(rec)
        self.assertIsNone(self.stop())
        helpers.write(self.repo, {"src/a.js": "manual\n"})
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop())
        self.assertEqual("verified", self.load(rec)["outcome"])

    def test_stop_ignores_other_sessions_run(self):
        rec = self.start(session="other")
        self.assertIsNone(self.stop(session="s1"))
        self.assertEqual(["other"], self.load(rec)["sessions"])

    def test_stop_brainstorm_stage_never_blocks(self):
        self.start(stage="brainstorm")
        self.assertIsNone(self.stop())

    def test_stop_hook_under_budget_with_big_transcript(self):
        rec = self.start()
        t = self.tmp / "t.jsonl"
        line = json.dumps({"type": "assistant", "message": {"content": "x" * 200}}) + "\n"
        with open(t, "w") as f:
            f.write(json.dumps({"type": "cost-state", "sessionId": "s1", "totalCostUSD": 1.0,
                                "modelUsage": {}}) + "\n")
            f.write(line * 90000)
        t0 = time.monotonic()
        self.assertEqual("block", self.stop(transcript=str(t))["decision"])
        self.assertLess(time.monotonic() - t0, 7)
        self.assertEqual({}, self.load(rec)["usage"])

    def test_stop_records_usage(self):
        rec = self.start()
        t = self.tmp / "t.jsonl"
        t.write_text(json.dumps({"type": "cost-state", "sessionId": "s1", "totalCostUSD": 1.5,
                                 "modelUsage": {}}) + "\n")
        self.stop(transcript=str(t))
        self.assertEqual(1.5, self.load(rec)["usage"]["s1"]["start_usd"])

    def test_stop_blocks_once_when_change_request_but_no_run(self):
        self.assertIn("brainstorm", self.prompt("add a booking page"))
        out = self.stop()
        self.assertEqual("block", out["decision"])
        self.assertIn("no Compound V run was started", out["reason"])
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop(session="s2"))

    def test_change_marker_cleared_once_run_bound(self):
        self.prompt("add a booking page")
        rec = self.start(session=None)
        self.verify(rec)
        self.assertIsNone(self.stop())
        self.assertEqual("verified", self.load(rec)["outcome"])
        self.assertIsNone(self.stop())

    def test_prompt_binds_unbound_run(self):
        rec = self.start(session=None)
        self.assertEqual([], rec["sessions"])
        text = self.prompt("please continue with the booking form")
        self.assertEqual(["s1"], self.load(rec)["sessions"])
        self.assertTrue(text.startswith(f"Compound V run {rec['id']}"), text)

    def test_triage_log_has_no_prompt_text(self):
        secret = "add a booking page for maria.ivanova@example.com"
        self.prompt(secret)
        self.prompt("hi")
        log = (self.repo / "docs/compound-v/runs/triage.log").read_text()
        self.assertNotIn("maria", log)
        rows = [json.loads(x) for x in log.splitlines()]
        self.assertEqual(["full", None], [r["tier"] for r in rows])
        self.assertEqual(len(secret), rows[0]["prompt_chars"])
        self.assertEqual({"at", "session", "tier", "reason", "prompt_chars"}, set(rows[0]))

    def test_prompt_filters(self):
        for text in ("hi", "/compound-v:init", "what is this?", "explain src/a.js",
                     "Thanks!"):
            self.assertIsNone(self.prompt(text), text)
        self.assertEqual(hooks.FULL_TEXT, self.prompt("add a booking page"))
        self.assertEqual(hooks.LIGHT_TEXT, self.prompt("fix typo in README", session="s2"))

    def test_prompt_nudges_capped_per_session(self):
        got = [self.prompt(f"implement feature {i}") for i in range(5)]
        self.assertEqual([hooks.FULL_TEXT] * 3 + [None] * 2, got)

    def test_prompt_not_set_up_notice_once(self):
        (self.repo / ".claude/compound-v.json").unlink()
        self.assertEqual(hooks.SETUP_TEXT, self.prompt("add a booking page"))
        self.assertIsNone(self.prompt("add a booking page"))
        self.assertFalse((self.repo / "docs/compound-v").exists())

    def test_session_hook_brief(self):
        self.assertIsNone(hooks.session_hook({"hook_event_name": "SessionStart",
                                              "session_id": "s1"}, self.repo))
        rec = self.start()
        text = hooks.session_hook({"hook_event_name": "SessionStart", "session_id": "s1"},
                                  self.repo)
        self.assertIn(rec["id"], text)

    def test_guard_denies_run_record_edit(self):
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            for path in ("docs/compound-v/runs/x.json",
                         str(self.repo / "docs/compound-v/runs/x.json")):
                out = hooks.guard_hook({"hook_event_name": "PreToolUse", "tool_name": tool,
                                        "tool_input": {key: path}, "cwd": str(self.repo)})
                self.assertEqual("deny", out["hookSpecificOutput"]["permissionDecision"])

    def test_guard_allows_other_paths(self):
        for path in ("src/a.js", "docs/compound-v/plans/p.md", "docs/compound-v/runs-old/x"):
            self.assertIsNone(hooks.guard_hook({
                "hook_event_name": "PreToolUse", "tool_name": "Write",
                "tool_input": {"file_path": path}, "cwd": str(self.repo)}))
        self.assertIsNone(hooks.guard_hook({
            "hook_event_name": "PreToolUse", "tool_name": "Read",
            "tool_input": {"file_path": "docs/compound-v/runs/x.json"}, "cwd": str(self.repo)}))


if __name__ == "__main__":
    unittest.main()
