from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import receipts, run, snapshot  # noqa: E402

COVER = [str(i) for i in range(10)] + ["F1"]
LIVE = "python3 -c \"import sys; sys.exit(int(open('live.rc').read()))\""
PLAN = """# Plan

```compound-v-plan
{block}
```

## Acceptance

| 1 | a booking is saved |
"""


def plan_text(**over):
    block = {"test_cmd": "python3 -c \"import sys; sys.exit(0)\"", "change_set": ["src/**"],
             "is_web": True, "live_cmd": LIVE, "timeout_s": 60}
    block.update(over)
    return PLAN.replace("{block}", json.dumps(block))


class Base(unittest.TestCase):
    tier = "full"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._key = receipts.KEY_PATH
        self.repo = helpers.make_repo(self.tmp, {
            "src/a.js": "export const a = 1\n", "tests/test_a.py": "t\n",
            ".gitignore": "live.rc\n.env\n"})
        receipts.KEY_PATH = helpers.key_path(self.repo)
        helpers.write(self.repo, {"live.rc": "0", "docs/compound-v/plans/p.md": plan_text()})
        self.rec = run.start(self.repo, tier=self.tier, request="add a booking page")
        if self.tier == "full":
            self.rec = run.attach_plan(self.repo, self.rec, "docs/compound-v/plans/p.md")
        else:
            self.rec.update({"test_cmd": "python3 -c \"import sys; sys.exit(0)\"",
                             "change_set": ["src/**"], "live_cmd": LIVE})
            run.save(self.repo, self.rec)

    def tearDown(self):
        receipts.KEY_PATH = self._key
        self._tmp.cleanup()

    def reload(self):
        self.rec = run.load(self.repo, self.rec["id"])
        return self.rec

    def steps(self, *names):
        for s in names or ("tests", "live", "scope"):
            receipts.run_step(self.repo, self.reload(), s)

    def review(self, severity=None, snap=None, checkout=True, stop=True):
        findings = [] if severity is None else [{
            "id": "F1", "severity": severity, "title": "form drops the date",
            "evidence": "src/a.js:1", "reproduce": None, "file": "src/a.js",
            "line_start": 1, "line_end": 1, "confidence": 0.8, "recommendation": "keep it"}]
        tid = snapshot.tree(self.repo)
        if checkout:
            receipts.note_checkout(self.repo, self.reload(), tid, self.tmp / "co")
        if stop:
            receipts.note_reviewer_stop(self.repo, self.reload(), "a1", "compound-v:reviewer")
        path = self.tmp / "findings.json"
        path.write_text(json.dumps({"snapshot": snap or tid, "summary": "s", "coverage": COVER,
                                    "findings": findings}))
        return receipts.record_review(self.repo, self.reload(), path, "claude")

    def status(self):
        return receipts.status(self.repo, self.reload())


class ReceiptsTest(Base):
    def test_pass_receipts_verify_full(self):
        self.steps()
        r = self.review()
        self.assertEqual("pass", r["result"])
        self.assertTrue((self.repo / f"docs/compound-v/runs/{self.rec['id']}-review-1.json")
                        .is_file())
        s = self.status()
        self.assertEqual("verified", s["outcome"], s)
        self.assertEqual({"limit": 7, "spent": None, "exceeded": False},
                         {k: s["budget"][k] for k in ("limit", "spent", "exceeded")})

    def test_review_findings_outside_repo_copied(self):
        self.steps()
        before = snapshot.tree(self.repo)
        r = self.review("low")
        copy = self.repo / r["findings_file"]
        self.assertEqual(f"docs/compound-v/runs/{self.rec['id']}-review-1.json",
                         r["findings_file"])
        self.assertEqual("F1", json.loads(copy.read_text())["findings"][0]["id"])
        self.assertEqual(before, snapshot.tree(self.repo))
        self.assertEqual("verified", self.status()["outcome"])

    def test_receipt_copied_to_other_slot_is_stale(self):
        self.steps()
        rec = self.reload()
        scope_receipt = dict(rec["receipts"]["scope"])
        rec["receipts"] = {s: dict(scope_receipt) for s in receipts.STEPS}
        run.save(self.repo, rec)
        s = self.status()
        self.assertEqual(["tests", "review", "live"], s["stale"])
        self.assertNotEqual("verified", s["outcome"])
        self.steps()
        rec = self.reload()
        rec["live_cmd"] = "true"
        run.save(self.repo, rec)
        self.assertIn("live", self.status()["stale"])

    def test_claude_review_needs_reviewer_run(self):
        self.steps()
        r = self.review(checkout=False)
        self.assertEqual(("error", "no reviewer run recorded"), (r["result"], r["reason"]))
        r = self.review(stop=False)
        self.assertEqual("error", r["result"])
        self.assertEqual(0, self.reload()["review_round"])

    def test_reviewer_stop_consumed_once(self):
        self.steps()
        self.assertEqual("fail", self.review("high")["result"])
        r = self.review(checkout=False, stop=False)
        self.assertEqual(("error", "no reviewer run recorded"), (r["result"], r["reason"]))
        self.assertTrue(self.reload()["reviewer_stops"][0]["consumed"])

    def subagent(self, base, aid="abc", kind="compound-v:reviewer", started=None, text=None,
                 finished=True):
        import time
        from datetime import datetime, timezone
        time.sleep(0.005)
        sub = Path(base) / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{aid}.meta.json").write_text(
            kind if kind.startswith("{") else json.dumps({"agentType": kind, "finished": True}))
        stamp = started or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        body = text if text is not None else f"CHECKOUT={self.tmp / 'co'}/tree"
        lines = [{"type": "user", "timestamp": stamp, "message": {"content": body}}]
        if finished:
            lines.append({"type": "assistant", "timestamp": stamp,
                          "message": {"stop_reason": "end_turn", "content": [{"type": "text"}]}})
        (sub / f"agent-{aid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))

    def test_reviewer_found_in_subagent_transcript(self):
        self.steps()
        rec = self.reload()
        rec["transcripts"] = {"s1": str(self.tmp / "proj/s1.jsonl")}
        run.save(self.repo, rec)
        receipts.note_checkout(self.repo, self.reload(), snapshot.tree(self.repo), self.tmp / "co")
        self.subagent(self.tmp / "proj/s1", aid="old", started="2020-01-01T00:00:00.000Z")
        self.subagent(self.tmp / "proj/s1", aid="other", text="no checkout path here")
        self.subagent(self.tmp / "proj/s1", aid="explore", kind="Explore")
        self.subagent(self.tmp / "proj/s1", aid="broken", kind="{not json")
        self.subagent(self.tmp / "proj/s1", aid="unfinished", finished=False)
        r = self.review(checkout=False, stop=False)
        self.assertEqual("error", r["result"])
        self.subagent(self.tmp / "proj/s1", aid="good")
        r = self.review(checkout=False, stop=False)
        self.assertEqual("pass", r["result"], r)
        stops = self.reload()["reviewer_stops"]
        self.assertEqual([("good", True, "transcript")],
                         [(s["agent_id"], s["consumed"], s["source"]) for s in stops])

    def test_reviewer_found_via_projects_dir(self):
        import os
        self.steps()
        cfg = self.tmp / "cfg"
        os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)
        try:
            receipts.note_checkout(self.repo, self.reload(), snapshot.tree(self.repo),
                                   self.tmp / "co")
            import re
            proj = cfg / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(self.repo)) / "sess"
            self.subagent(proj, aid="r1")
            self.assertEqual("pass", self.review(checkout=False, stop=False)["result"])
            self.assertEqual("error", self.review(checkout=False, stop=False)["result"])
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]

    def test_codex_reviewer_not_recordable_from_cli(self):
        f = self.tmp / "forged.json"
        f.write_text(json.dumps({"snapshot": snapshot.tree(self.repo), "summary": "x", "coverage": COVER,
                                 "findings": []}))
        r = helpers.cli(self.repo, "review", "record", "--findings", str(f), "--reviewer", "codex")
        self.assertEqual(2, r.returncode)
        self.assertEqual(0, self.reload()["review_round"])

    def test_codex_findings_need_a_codex_run(self):
        self.steps()
        f = self.tmp / "forged.json"
        f.write_text(json.dumps({"snapshot": snapshot.tree(self.repo), "summary": "x", "coverage": COVER,
                                 "findings": []}))
        r = receipts.record_review(self.repo, self.reload(), f, "codex")
        self.assertEqual(("error", "no reviewer run recorded"), (r["result"], r["reason"]))
        self.assertNotEqual("verified", self.status()["outcome"])

    def test_checkout_records_checkout(self):
        r = helpers.cli(self.repo, "checkout", "--dest", str(self.tmp / "co"))
        self.assertEqual(0, r.returncode, r.stderr)
        co = self.reload()["checkouts"]
        self.assertEqual(json.loads(r.stdout)["tree"], co[0]["tree"])

    def test_code_hidden_in_runs_dir_counts(self):
        self.steps()
        self.review()
        helpers.write(self.repo, {"docs/compound-v/runs/runtime.py": "value = 0\n"})
        self.assertIn("tests", self.status()["stale"])

    def test_reattach_keeps_deleted_test_evidence(self):
        (self.repo / "tests/test_a.py").unlink()
        run.attach_plan(self.repo, self.reload(), "docs/compound-v/plans/p.md")
        self.assertIn("tests/test_a.py", self.reload()["test_files"])
        r = receipts.run_step(self.repo, self.reload(), "tests")
        self.assertEqual("fail", r["result"])
        self.assertIn("tests removed", r["reason"])

    def test_edit_after_receipt_goes_stale(self):
        self.steps()
        self.review()
        with open(self.repo / "src/a.js", "a") as f:
            f.write("// more\n")
        s = self.status()
        self.assertEqual(["tests", "review", "live", "scope"], s["stale"])
        self.assertEqual("pending", s["outcome"])

    def test_hand_written_receipt_rejected(self):
        self.rec["test_cmd"] = "python3 -c \"import sys; sys.exit(1)\""
        run.save(self.repo, self.rec)
        self.steps("tests")
        rec = self.reload()
        self.assertEqual("fail", rec["receipts"]["tests"]["result"])
        rec["receipts"]["tests"]["result"] = "pass"
        run.save(self.repo, rec)
        self.assertIn("tests", self.status()["stale"])

    def test_failed_browser_form_refused(self):
        helpers.write(self.repo, {"live.rc": "1"})
        self.steps()
        self.review()
        self.assertEqual("fail", self.reload()["receipts"]["live"]["result"])
        s = self.status()
        self.assertEqual(["live"], s["failed"])
        self.assertNotEqual("verified", s["outcome"])

    def test_skipped_review_refused(self):
        self.steps()
        s = self.status()
        self.assertEqual(["review"], s["missing"])
        self.assertEqual("pending", s["outcome"])

    def test_review_rounds_bounded(self):
        self.steps()
        self.assertEqual("fail", self.review("high")["result"])
        self.assertEqual("fail", self.review("blocker")["result"])
        with self.assertRaises(run.RunError):
            self.review()
        self.assertEqual("incomplete", self.status()["outcome"])
        helpers.write(self.repo, {"src/a.js": "export const a = 2\n"})
        self.steps()
        self.assertEqual("incomplete", self.status()["outcome"])

    def test_second_review_pass_verifies(self):
        self.steps()
        self.review("high")
        helpers.write(self.repo, {"src/a.js": "export const a = 2\n"})
        self.steps()
        self.assertEqual("pass", self.review("medium")["result"])
        self.assertEqual("verified", self.status()["outcome"])

    def test_stale_review_rejected(self):
        self.steps()
        r = self.review(snap="0" * 40)
        self.assertEqual(("error", "stale review"), (r["result"], r["reason"]))
        self.assertEqual(0, self.reload()["review_round"])

    def test_tests_removed_flagged(self):
        (self.repo / "tests/test_a.py").unlink()
        r = receipts.run_step(self.repo, self.reload(), "tests")
        self.assertEqual("fail", r["result"])
        self.assertIn("tests removed", r["reason"])

    def test_missing_live_cmd_is_error(self):
        self.rec["live_cmd"] = None
        run.save(self.repo, self.rec)
        r = receipts.run_step(self.repo, self.reload(), "live")
        self.assertEqual(("error", "no live_cmd"), (r["result"], r["reason"]))
        self.assertEqual("incomplete", self.status()["outcome"])

    def test_live_waiver(self):
        self.steps("tests", "scope")
        self.review()
        receipts.waive(self.repo, self.reload(), "live", "no browser on this machine")
        s = self.status()
        self.assertEqual(("verified", ["live"]), (s["outcome"], s["waived"]))
        with self.assertRaises(run.RunError):
            receipts.waive(self.repo, self.reload(), "tests", "no")
        helpers.write(self.repo, {"live.rc": "1"})
        self.steps("live")
        s = self.status()
        self.assertEqual((["live"], []), (s["failed"], s["waived"]))
        self.assertNotEqual("verified", s["outcome"])

    def test_ignored_env_change_stales(self):
        helpers.write(self.repo, {".env": "A=1\n"})
        self.steps()
        self.review()
        helpers.write(self.repo, {".env": "A=2\n"})
        s = self.status()
        self.assertEqual(["tests", "review", "live", "scope"], s["stale"])

    def test_failing_assertion_with_listen_eperm_is_fail(self):
        rec = self.reload()
        for out in ("Browser started; AssertionError: page shows listen EPERM",
                    "  ✘ 1 failed: booking page\\n  error: listen EPERM 127.0.0.1:3000",
                    "3 passed, 1 failed\\nbootstrap_check_in denied"):
            rec["live_cmd"] = f"python3 -c \"print('{out}'); raise SystemExit(1)\""
            run.save(self.repo, rec)
            self.assertEqual("fail", receipts.run_step(self.repo, self.reload(), "live")["result"],
                             out)
        rec["live_cmd"] = "python3 -c \"print('Error: listen EPERM: operation not permitted 0.0.0.0:3000'); raise SystemExit(1)\""
        run.save(self.repo, rec)
        self.assertEqual("error", receipts.run_step(self.repo, self.reload(), "live")["result"])

    def test_review_without_coverage_is_incomplete(self):
        self.steps()
        for cover, summary in ((["0", "1", "2"], "s"), (COVER, "Budget exhausted after probe 4"),
                               (COVER[:4] + ["4 skipped: budget"], "s")):
            tid = snapshot.tree(self.repo)
            receipts.note_checkout(self.repo, self.reload(), tid, self.tmp / "co")
            receipts.note_reviewer_stop(self.repo, self.reload(), "a", "compound-v:reviewer")
            f = self.tmp / "f.json"
            f.write_text(json.dumps({"snapshot": tid, "summary": summary, "coverage": cover,
                                     "findings": []}))
            r = receipts.record_review(self.repo, self.reload(), f, "claude")
            self.assertEqual("error", r["result"], cover)
            self.assertIn("review incomplete", r["reason"])
        self.assertEqual(0, self.reload()["review_round"])
        self.assertNotEqual("verified", self.status()["outcome"])
        f.write_text(json.dumps({"snapshot": snapshot.tree(self.repo), "summary": "s",
                                 "findings": []}))
        with self.assertRaises(run.RunError):
            receipts.record_review(self.repo, self.reload(), f, "claude")

    def test_round_two_must_recheck_round_one(self):
        self.steps()
        self.assertEqual("fail", self.review("high")["result"])
        helpers.write(self.repo, {"src/a.js": "export const a = 2\n"})
        self.steps()
        global COVER
        saved, COVER = COVER, ["0", "1", "2", "3", "4"]
        try:
            r = self.review()
        finally:
            COVER = saved
        self.assertEqual(("error", 1), (r["result"], self.reload()["review_round"]))
        self.assertIn("F1 not re-checked", r["reason"])
        self.assertEqual("pass", self.review()["result"])

    def test_global_excludes_do_not_unexclude_evidence(self):
        ex = self.tmp / "global-ignore"
        ex.write_text("docs/compound-v/runs/\n")
        helpers.sh(self.repo, "config", "core.excludesFile", str(ex))
        self.steps()
        self.review()
        s = self.status()
        self.assertEqual(([], "verified"), (s["stale"], s["outcome"]))

    def test_sandbox_launch_failure_is_error(self):
        rec = self.reload()
        noise = "\\n".join(f"line {i}" for i in range(40))
        rec["live_cmd"] = ("python3 -c \"import sys; sys.stderr.write('[0101/x] failed to copy trust "
                           "settings\\n" + noise + "\\n'); sys.exit(1)\"")
        run.save(self.repo, rec)
        r = receipts.run_step(self.repo, self.reload(), "live")
        self.assertEqual("error", r["result"])
        self.assertIn("could not start inside the sandbox", r["reason"])
        self.assertIn(f"receipt live --id {rec['id']}", r["reason"])
        s = self.status()
        self.assertEqual((["live"], []), (s["errors"], s["failed"]))
        self.assertEqual("incomplete", s["outcome"])
        rec["live_cmd"] = "python3 -c \"import sys; print('assertion failed'); sys.exit(1)\""
        run.save(self.repo, rec)
        self.assertEqual("fail", receipts.run_step(self.repo, self.reload(), "live")["result"])

    def test_cli_output_is_terse(self):
        r = helpers.cli(self.repo, "receipt", "tests")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(1, len(r.stdout.strip().splitlines()), r.stdout)
        self.assertTrue(r.stdout.startswith("tests: pass (exit 0, "), r.stdout)
        r = helpers.cli(self.repo, "receipt", "scope", "--json")
        self.assertEqual("pass", json.loads(r.stdout)["result"])
        rec = self.reload()
        rec["live_cmd"] = "python3 -c \"import sys; print('\\n'.join(map(str, range(30)))); sys.exit(1)\""
        run.save(self.repo, rec)
        r = helpers.cli(self.repo, "receipt", "live")
        self.assertEqual(1, r.returncode)
        lines = r.stdout.strip().splitlines()
        self.assertTrue(lines[0].startswith("live: fail (exit 1, "), lines)
        self.assertEqual(["  25", "  26", "  27", "  28", "  29"], lines[1:])
        r = helpers.cli(self.repo, "status")
        self.assertEqual(1, len(r.stdout.strip().splitlines()))
        self.assertNotIn("tail", json.loads(r.stdout))
        r = helpers.cli(self.repo, "run", "show", "--brief")
        self.assertEqual(1, len(r.stdout.strip().splitlines()))
        self.assertIn(f"{rec['id']} · stage brainstorm (full)", r.stdout)

    def test_cli_review_record_is_terse(self):
        receipts.note_checkout(self.repo, self.reload(), snapshot.tree(self.repo), self.tmp / "co")
        receipts.note_reviewer_stop(self.repo, self.reload(), "a1", "compound-v:reviewer")
        f = self.tmp / "f.json"
        f.write_text(json.dumps({"snapshot": snapshot.tree(self.repo), "summary": "ok", "coverage": COVER,
                                 "findings": []}))
        r = helpers.cli(self.repo, "review", "record", "--findings", str(f), "--reviewer", "claude")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(
            f"review round 1: pass (0 blocker/high of 0 findings) "
            f"docs/compound-v/runs/{self.rec['id']}-review-1.json", r.stdout.strip())

    def test_long_step_does_not_clobber_review(self):
        self.steps()
        stale = self.reload()
        self.assertEqual("pass", self.review()["result"])
        receipts.run_step(self.repo, stale, "tests")
        rec = self.reload()
        self.assertEqual(1, rec["review_round"])
        self.assertEqual({"tests", "review", "live", "scope"}, set(rec["receipts"]))
        self.assertEqual(1, len(rec["reviews"]))
        self.assertEqual(rec, stale)

    def test_lock_not_held_during_step(self):
        lock = self.repo / ".git/compound-v/locks" / f"{self.rec['id']}.lock"
        rec = self.reload()
        rec["test_cmd"] = ("python3 -c \"import fcntl, os, sys; fd = os.open('%s', os.O_RDWR); "
                           "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\"" % lock)
        run.save(self.repo, rec)
        receipts.note_checkout(self.repo, self.reload(), "x", "/tmp/x")
        self.assertTrue(lock.exists())
        self.assertEqual("pass", receipts.run_step(self.repo, self.reload(), "tests")["result"])
        self.assertEqual(snapshot.tree(self.repo), receipts._current(self.repo, rec)["snapshot"])

    def test_lock_lives_outside_the_tree(self):
        receipts.note_checkout(self.repo, self.reload(), "x", "/tmp/x")
        self.assertFalse(list((self.repo / "docs/compound-v/runs").glob("*.lock")))
        self.assertNotIn(b".lock", helpers.sh(self.repo, "status", "--porcelain", "--untracked-files=all"))

    def test_concurrent_updates_keep_all(self):
        import threading
        rid = self.rec["id"]

        def worker(n):
            for i in range(10):
                receipts.note_reviewer_stop(self.repo, run.load(self.repo, rid), f"{n}-{i}",
                                            "compound-v:reviewer")
        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(80, len(self.reload()["reviewer_stops"]))

    def test_cli_status_exit_codes(self):
        r = helpers.cli(self.repo, "status")
        self.assertEqual(3, r.returncode, r.stderr)
        for step in ("tests", "live", "scope"):
            r = helpers.cli(self.repo, "receipt", step)
            self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(helpers.key_path(self.repo).is_file())
        r = helpers.cli(self.repo, "status")
        self.assertEqual(["review"], json.loads(r.stdout)["missing"])
        r = helpers.cli(self.repo, "waive", "live", "--reason", "no browser", "--id",
                        self.rec["id"])
        self.assertEqual(0, r.returncode, r.stderr)


class LightTest(Base):
    tier = "light"

    def test_light_requires_tests_scope(self):
        self.assertEqual(["tests", "scope"], receipts.required(self.reload(), self.repo))
        self.steps("tests", "scope")
        self.assertEqual("verified", self.status()["outcome"])

    def test_light_escalates_on_auth_diff(self):
        self.steps("tests", "scope")
        self.assertTrue(self.reload()["receipts"])
        helpers.write(self.repo, {"src/a.js": "export function login() {}\n"})
        req = receipts.required(self.reload(), self.repo)
        rec = self.reload()
        self.assertEqual("full", rec["tier"])
        self.assertEqual({}, rec["receipts"])
        self.assertIn("auth", rec["escalations"][0]["reasons"])
        self.assertEqual(["tests", "review", "live", "scope"], req)


if __name__ == "__main__":
    unittest.main()
