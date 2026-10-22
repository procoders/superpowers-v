from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import run  # noqa: E402

PLAN = """# Plan

```compound-v-plan
{BLOCK}
```

## Acceptance

| # | Check |
|---|---|
| 1 | booking form saves a booking |

## Tasks

- build it
"""

BLOCK = {"test_cmd": "python3 -m unittest", "change_set": ["src/**"], "is_web": True,
         "live_cmd": "npx playwright test"}


def write_plan(repo, block=None, body=PLAN, name="docs/compound-v/plans/p.md"):
    text = body.replace("{BLOCK}", json.dumps(BLOCK if block is None else block))
    helpers.write(repo, {name: text})
    return name


class RunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = helpers.make_repo(Path(self._tmp.name),
                                      {"src/a.js": "a\n", "tests/test_a.py": "t\n"})
        self.head = helpers.sh(self.repo, "rev-parse", "HEAD").decode().strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_start_full_and_light_stages(self):
        full = run.start(self.repo, tier="full", request="Add a booking page")
        light = run.start(self.repo, tier="light", request="fix typo")
        self.assertEqual("brainstorm", full["stage"])
        self.assertEqual("build", light["stage"])
        self.assertEqual(self.head, full["base_commit"])
        self.assertNotEqual(full["id"], light["id"])
        self.assertEqual(full, run.load(self.repo, full["id"]))
        self.assertIsNone(full["outcome"])
        self.assertEqual(0, full["review_round"])

    def test_stage_forward_only(self):
        rec = run.start(self.repo, tier="full", request="x")
        rec = run.set_stage(self.repo, rec, "plan")
        self.assertEqual("plan", run.load(self.repo, rec["id"])["stage"])
        with self.assertRaises(run.RunError):
            run.set_stage(self.repo, rec, "brainstorm")
        rec = run.set_stage(self.repo, rec, "verify")
        rec = run.set_stage(self.repo, rec, "build")
        self.assertEqual("build", rec["stage"])

    def test_attach_plan_parses_block_and_acceptance_rev(self):
        rec = run.start(self.repo, tier="full", request="booking")
        plan = write_plan(self.repo)
        rec = run.attach_plan(self.repo, rec, plan)
        self.assertEqual("npx playwright test", rec["live_cmd"])
        self.assertEqual(7, rec["budget_usd"])
        self.assertEqual(900, rec["timeout_s"])
        self.assertEqual(["tests/test_a.py"], sorted(rec["test_files"]))
        rev = rec["acceptance_rev"]
        write_plan(self.repo, body=PLAN.replace("- build it", "- build it well"))
        self.assertEqual(rev, run.attach_plan(self.repo, rec, plan)["acceptance_rev"])
        write_plan(self.repo, body=PLAN.replace("saves a booking", "saves two bookings"))
        self.assertNotEqual(rev, run.attach_plan(self.repo, rec, plan)["acceptance_rev"])

    def test_attach_plan_missing_key(self):
        rec = run.start(self.repo, tier="full", request="booking")
        block = {k: v for k, v in BLOCK.items() if k != "live_cmd"}
        with self.assertRaises(run.RunError) as cm:
            run.attach_plan(self.repo, rec, write_plan(self.repo, block))
        self.assertIn("live_cmd", str(cm.exception))
        with self.assertRaises(run.RunError) as cm:
            run.attach_plan(self.repo, rec, write_plan(
                self.repo, body=PLAN.replace("## Acceptance", "## Checks")))
        self.assertIn("Acceptance", str(cm.exception))

    def test_active_prefers_session_binding(self):
        a = run.start(self.repo, tier="full", request="a", session_id="s1")
        b = run.start(self.repo, tier="full", request="b", session_id="s2")
        self.assertEqual(a["id"], run.active(self.repo, "s1")["id"])
        self.assertEqual(b["id"], run.active(self.repo, "s2")["id"])
        self.assertIsNone(run.active(self.repo, "s3"))
        c = run.start(self.repo, tier="full", request="c")
        self.assertEqual(c["id"], run.active(self.repo, "s3")["id"])
        self.assertEqual(a["id"], run.active(self.repo, "s1")["id"])
        run.bind(self.repo, c, "s3")
        self.assertEqual(["s3"], run.load(self.repo, c["id"])["sessions"])

    def test_light_start_reads_live_cmd_from_config(self):
        helpers.write(self.repo, {".claude/compound-v.json": json.dumps(
            {"test_cmd": "true", "live_cmd": "npx playwright test", "is_web": True})})
        rec = run.start(self.repo, tier="light", request="copy")
        self.assertEqual(("npx playwright test", True), (rec["live_cmd"], rec["is_web"]))
        rec = run.start(self.repo, tier="light", request="copy", live_cmd="make smoke")
        self.assertEqual("make smoke", rec["live_cmd"])
        helpers.write(self.repo, {"req.txt": "copy"})
        r = helpers.cli(self.repo, "run", "start", "--tier", "light", "--request-file", "req.txt",
                        "--live-cmd", "make e2e")
        self.assertEqual("make e2e", json.loads(r.stdout)["live_cmd"])

    def test_cli_pick_refuses_ambiguous(self):
        a = run.start(self.repo, tier="light", request="a")
        run.start(self.repo, tier="light", request="b")
        r = helpers.cli(self.repo, "run", "show")
        self.assertEqual(2, r.returncode)
        self.assertIn("pass --id", r.stderr)
        self.assertEqual(0, helpers.cli(self.repo, "run", "show", "--id", a["id"]).returncode)

    def test_verified_stays_closed(self):
        rec = run.start(self.repo, tier="light", request="x")
        rec["outcome"] = "verified"
        run.save(self.repo, rec)
        with self.assertRaises(run.RunError):
            run.set_stage(self.repo, rec, "verify")
        self.assertEqual("verified", run.reopen(self.repo, rec, "test")["outcome"])
        rec2 = run.start(self.repo, tier="light", request="y")
        rec2["outcome"] = "incomplete"
        run.save(self.repo, rec2)
        rec2 = run.set_stage(self.repo, rec2, "verify")
        self.assertIsNone(rec2["outcome"])
        self.assertEqual("stage verify", rec2["outcomes"][0]["reason"])

    def test_closed_run_not_active(self):
        rec = run.start(self.repo, tier="light", request="x")
        rec["outcome"] = "verified"
        run.save(self.repo, rec)
        self.assertIsNone(run.active(self.repo))
        self.assertIsNone(run.active(self.repo, "s1"))

    def test_cli_run_cycle(self):
        helpers.write(self.repo, {"req.txt": "Add a booking page"})
        r = helpers.cli(self.repo, "run", "start", "--tier", "full", "--request-file", "req.txt")
        self.assertEqual(0, r.returncode, r.stderr)
        rid = json.loads(r.stdout)["id"]
        plan = write_plan(self.repo)
        r = helpers.cli(self.repo, "run", "plan", "--plan", plan)
        self.assertEqual(0, r.returncode, r.stderr)
        r = helpers.cli(self.repo, "run", "stage", "--to", "build", "--id", rid)
        self.assertEqual("build", json.loads(r.stdout)["stage"])
        r = helpers.cli(self.repo, "run", "stage", "--to", "plan")
        self.assertEqual(2, r.returncode)
        r = helpers.cli(self.repo, "run", "bind", "--session", "s9")
        self.assertEqual(["s9"], json.loads(r.stdout)["sessions"])


if __name__ == "__main__":
    unittest.main()
