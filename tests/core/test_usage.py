from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import receipts, run, usage  # noqa: E402

OTHER = json.dumps({"type": "assistant", "message": {"content": "x" * 80}})


def cost_line(total, session="s1", unknown=False):
    d = {"type": "cost-state", "sessionId": session, "totalCostUSD": total,
         "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "costUSD": total}}}
    if unknown:
        d["hasUnknownModelCost"] = True
    return json.dumps(d, separators=(",", ":"))


class UsageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._key = receipts.KEY_PATH
        self.repo = helpers.make_repo(self.tmp, {"a.txt": "a\n"})
        receipts.KEY_PATH = helpers.key_path(self.repo)
        self.transcript = self.tmp / "t.jsonl"

    def tearDown(self):
        receipts.KEY_PATH = self._key
        self._tmp.cleanup()

    def spend(self, rec, total, stage=None, unknown=False, session="s1"):
        if stage:
            rec["stage"] = stage
        with open(self.transcript, "a") as f:
            f.write(OTHER + "\n" + cost_line(total, session, unknown) + "\n")
        return usage.record(self.repo, rec, session, self.transcript)

    def test_last_cost_state_reads_newest(self):
        with open(self.transcript, "w") as f:
            for i, total in enumerate((1.0, 2.0, 3.25)):
                f.write((OTHER + "\n") * 16000)
                f.write(cost_line(total) + "\n")
            f.write((OTHER + "\n") * 2000)
        cs = usage.last_cost_state(self.transcript)
        self.assertEqual((3.25, "s1", False), (cs["total_usd"], cs["session"], cs["unknown_cost"]))
        self.assertEqual({"claude-opus-5-5": 3.25}, cs["per_model"])

    def test_last_cost_state_bad_json_none(self):
        self.transcript.write_text(OTHER + "\n" + cost_line(1.0)[:-5] + "\n")
        self.assertIsNone(usage.last_cost_state(self.transcript))
        self.assertIsNone(usage.last_cost_state(self.tmp / "missing.jsonl"))

    def test_last_cost_state_skips_quoted_needle(self):
        quoted = json.dumps({"type": "user", "content": cost_line(9.0)})
        self.transcript.write_text(cost_line(1.5) + "\n" + quoted + "\n")
        self.assertEqual(1.5, usage.last_cost_state(self.transcript)["total_usd"])

    def test_last_cost_state_tail_bound(self):
        with open(self.transcript, "w") as f:
            f.write(cost_line(1.0) + "\n")
            f.write((OTHER + "\n") * 200000)
        self.assertGreater(self.transcript.stat().st_size, 20_000_000)
        t0 = time.monotonic()
        self.assertIsNone(usage.last_cost_state(self.transcript, max_tail_bytes=1_000_000))
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_run_cost_excludes_pre_run_spend(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.assertIsNone(usage.run_cost(rec))
        self.spend(rec, 3.00)
        self.assertEqual(0, usage.run_cost(rec))
        self.spend(rec, 5.50)
        self.assertAlmostEqual(2.50, usage.run_cost(rec))
        self.spend(rec, 1.00, session="s2")
        self.spend(rec, 1.25, session="s2")
        self.assertAlmostEqual(2.75, usage.run_cost(run.load(self.repo, rec["id"])))

    def test_usage_by_stage_and_budget(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.spend(rec, 0.0, stage="plan")
        self.spend(rec, 1.0, stage="plan")
        self.spend(rec, 4.5, stage="build")
        self.assertEqual({"before_build": 1.0, "build": 3.5}, rec["usage_by_stage"])
        b = receipts.status(self.repo, run.load(self.repo, rec["id"]))["budget"]
        self.assertEqual((4.5, False, ["build"]), (b["spent"], b["exceeded"], b["stage_exceeded"]))
        self.spend(rec, 8.0, stage="verify")
        s = receipts.status(self.repo, run.load(self.repo, rec["id"]))
        self.assertTrue(s["budget"]["exceeded"])
        self.assertEqual("incomplete", s["outcome"])

    def test_unknown_cost_reports_unknown(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.spend(rec, 1.0)
        self.spend(rec, 20.0, unknown=True)
        self.assertIsNone(usage.run_cost(rec))
        b = receipts.status(self.repo, rec)["budget"]
        self.assertEqual((None, False, False), (b["spent"], b["exceeded"], b["known"]))

    def test_cli_usage(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.transcript.write_text(cost_line(2.0) + "\n")
        r = helpers.cli(self.repo, "usage", "--session", "s1", "--transcript",
                        str(self.transcript))
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(2.0, run.load(self.repo, rec["id"])["usage"]["s1"]["start_usd"])


if __name__ == "__main__":
    unittest.main()
