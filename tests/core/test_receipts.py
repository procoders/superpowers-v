from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import receipts, run, snapshot  # noqa: E402

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
        receipts.KEY_PATH = self.tmp / "home/receipt.key"
        self.repo = helpers.make_repo(self.tmp, {
            "src/a.js": "export const a = 1\n", "tests/test_a.py": "t\n",
            ".gitignore": "live.rc\n.env\n"})
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

    def review(self, severity=None, snap=None):
        findings = [] if severity is None else [{
            "id": "F1", "severity": severity, "title": "form drops the date",
            "evidence": "src/a.js:1", "reproduce": None, "file": "src/a.js",
            "line_start": 1, "line_end": 1, "confidence": 0.8, "recommendation": "keep it"}]
        path = self.tmp / "findings.json"
        path.write_text(json.dumps({"snapshot": snap or snapshot.tree(self.repo),
                                    "summary": "s", "findings": findings}))
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

    def test_ignored_env_change_stales(self):
        helpers.write(self.repo, {".env": "A=1\n"})
        self.steps()
        self.review()
        helpers.write(self.repo, {".env": "A=2\n"})
        s = self.status()
        self.assertEqual(["tests", "review", "live", "scope"], s["stale"])

    def test_cli_status_exit_codes(self):
        home = {"HOME": str(self.tmp / "clihome")}
        import os
        import subprocess
        env = dict(os.environ, **home)
        cmd = [sys.executable, str(helpers.SCRIPTS / "compound-v.py")]
        r = subprocess.run(cmd + ["status"], cwd=self.repo, env=env, capture_output=True,
                           text=True)
        self.assertEqual(3, r.returncode, r.stderr)
        for step in ("tests", "live", "scope"):
            r = subprocess.run(cmd + ["receipt", step], cwd=self.repo, env=env,
                               capture_output=True, text=True)
            self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue((self.tmp / "clihome/.claude/compound-v/receipt.key").is_file())
        r = subprocess.run(cmd + ["status"], cwd=self.repo, env=env, capture_output=True,
                           text=True)
        self.assertEqual(["review"], json.loads(r.stdout)["missing"])


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
