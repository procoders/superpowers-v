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

    def cost(self, total, name="t.jsonl"):
        t = self.tmp / name
        with open(t, "a") as f:
            f.write(json.dumps({"type": "cost-state", "sessionId": "s1", "totalCostUSD": total,
                                "modelUsage": {}}) + "\n")
        return str(t)

    def stop(self, session="s1", active=False, transcript=None):
        return hooks.stop_hook({"hook_event_name": "Stop", "session_id": session,
                                "stop_hook_active": active, "transcript_path": transcript,
                                "cwd": str(self.repo)}, self.repo, state_dir=self.state)

    def prompt(self, text, session="s1", transcript=None):
        return hooks.prompt_hook({"hook_event_name": "UserPromptSubmit", "session_id": session,
                                  "prompt": text, "cwd": str(self.repo),
                                  "transcript_path": transcript}, self.repo, self.state)

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
        self.assertIsNone(self.stop())
        helpers.write(self.repo, {"src/booking.js": "b\n"})
        out = self.stop()
        self.assertEqual("block", out["decision"])
        self.assertIn("no Compound V run was started", out["reason"])
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop(session="s2"))

    def test_question_with_action_verb_is_change_request(self):
        self.assertEqual(hooks.FULL_TEXT, self.prompt("Can you add a login page?"))
        self.assertIsNone(self.prompt("Why does the login fail?", session="s2"))
        helpers.write(self.repo, {"src/login.js": "l\n"})
        self.assertEqual("block", self.stop()["decision"])

    def test_unclassified_change_request_arms_refusal(self):
        self.assertEqual(hooks.FULL_TEXT, self.prompt("Fix the broken search"))
        self.assertEqual(hooks.LIGHT_TEXT, self.prompt("fix the wording of the footer",
                                                       session="s2"))
        helpers.write(self.repo, {"src/a.js": "search fixed\n"})
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())

    def test_new_request_rearms_refusal(self):
        self.prompt("add a booking page")
        helpers.write(self.repo, {"src/booking.js": "b\n"})
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())
        self.prompt("now add a calendar")
        self.assertIsNone(self.stop())
        helpers.write(self.repo, {"src/calendar.js": "c\n"})
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())

    def test_planning_only_turns_never_refuse(self):
        self.prompt("add a booking page")
        helpers.write(self.repo, {"docs/notes.md": "questions\n"})
        self.assertIsNone(self.stop())
        rec = self.start(stage="brainstorm")
        helpers.write(self.repo, {"docs/compound-v/specs/s.md": "spec\n"})
        self.assertIsNone(self.stop())
        self.assertIsNone(self.load(rec)["outcome"])

    def test_early_code_change_refused_once(self):
        rec = self.start(stage="plan")
        helpers.write(self.repo, {"src/a.js": "too early\n"})
        out = self.stop()
        self.assertEqual("block", out["decision"])
        self.assertIn(f"Code changed before the plan was attached to run {rec['id']}",
                      out["reason"])
        self.assertIsNone(self.stop())
        self.assertIsNone(self.stop(active=True))
        self.assertIsNone(self.load(rec)["outcome"])

    def test_receipt_after_incomplete_reopens_and_can_verify(self):
        rec = self.start()
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())
        self.assertEqual("incomplete", self.load(rec)["outcome"])
        self.verify(rec)
        rec = self.load(rec)
        self.assertIsNone(rec["outcome"])
        self.assertEqual("incomplete", rec["outcomes"][0]["outcome"])
        self.assertEqual(rec["id"], run.active(self.repo, "s1")["id"])
        self.assertIsNone(self.stop())
        self.assertEqual(("verified", "done"), (self.load(rec)["outcome"], self.load(rec)["stage"]))

    def test_reopened_run_still_refuses_new_snapshot(self):
        rec = self.start()
        self.stop()
        self.stop()
        rec = self.load(rec)
        rec["test_cmd"] = "false"
        run.save(self.repo, rec)
        helpers.write(self.repo, {"src/a.js": "a2\n"})
        receipts.run_step(self.repo, self.load(rec), "tests")
        self.assertEqual("block", self.stop()["decision"])
        self.assertIsNone(self.stop())
        self.assertEqual("failed", self.load(rec)["outcome"])

    def test_stop_hook_active_records_outcome(self):
        rec = self.start()
        self.verify(rec)
        self.assertIsNone(self.stop(active=True))
        self.assertEqual("verified", self.load(rec)["outcome"])
        rec2 = self.start(session="s2")
        self.assertEqual("block", self.stop(session="s2")["decision"])
        self.assertIsNone(self.stop(session="s2", active=True))
        self.assertEqual("incomplete", self.load(rec2)["outcome"])

    def test_hooks_record_transcript_path(self):
        rec = self.start(session=None)
        t = self.cost(1.0)
        self.prompt("please continue", transcript=t)
        self.assertEqual({"s1": t}, self.load(rec)["transcripts"])

    def test_prompt_records_baseline_before_work(self):
        t = self.cost(3.0)
        self.prompt("add a booking page", transcript=t)
        self.cost(4.0)
        rec = self.start(session=None)
        self.cost(5.5)
        self.prompt("yes, go on", transcript=t)
        self.assertAlmostEqual(2.5, receipts.usage.run_cost(self.load(rec)))

    def test_first_turn_baseline_is_zero(self):
        t = self.tmp / "fresh.jsonl"
        t.write_text("")
        self.prompt("add a booking page", transcript=str(t))
        rec = self.start(session=None)
        self.cost(1.25, name="fresh.jsonl")
        self.stop(transcript=str(t))
        self.assertAlmostEqual(1.25, receipts.usage.run_cost(self.load(rec)))

    def test_status_refreshes_usage(self):
        rec = self.start(session=None)
        t = self.cost(1.0)
        self.prompt("please continue", transcript=t)
        self.cost(3.0)
        self.assertEqual(2.0, receipts.status(self.repo, self.load(rec))["budget"]["spent"])

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

    def test_subagent_stop_records_reviewer(self):
        rec = self.start()
        for kind in ("Explore", "compound-v:spec-reviewer", "compound-v:reviewer"):
            hooks.subagent_stop_hook({"hook_event_name": "SubagentStop", "session_id": "s1",
                                      "agent_id": "a-" + kind, "agent_type": kind}, self.repo)
        stops = self.load(rec)["reviewer_stops"]
        self.assertEqual(["compound-v:reviewer"], [s["agent_type"] for s in stops])

    def test_subagent_stop_logged(self):
        self.start()
        for kind in ("Explore", "compound-v:reviewer"):
            hooks.subagent_stop_hook({"hook_event_name": "SubagentStop", "session_id": "s1",
                                      "agent_id": "a", "agent_type": kind}, self.repo)
        rows = [json.loads(x) for x in
                (self.repo / "docs/compound-v/runs/triage.log").read_text().splitlines()]
        self.assertEqual([("Explore", False), ("compound-v:reviewer", True)],
                         [(r["agent_type"], r["recorded"]) for r in rows])

    def test_harness_notices_ignored(self):
        for text in ("<task-notification>build finished</task-notification>",
                     "  <system-reminder>add a page</system-reminder>",
                     "[SYSTEM NOTIFICATION] Fix the broken search", "<local-command-stdout>x"):
            self.assertIsNone(self.prompt(text), text)
        self.assertFalse((self.state / "change-s1").exists())
        rows = (self.repo / "docs/compound-v/runs/triage.log").read_text()
        self.assertEqual(4, rows.count("harness notice"))

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
