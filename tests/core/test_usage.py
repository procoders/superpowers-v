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
            run.save(self.repo, rec)
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

    def test_last_cost_state_bad_json_none(self):
        self.transcript.write_text(OTHER + "\n" + cost_line(1.0)[:-5] + "\n")
        self.assertIsNone(usage.last_cost_state(self.transcript))
        self.assertIsNone(usage.last_cost_state(self.tmp / "missing.jsonl"))

    def test_last_cost_state_skips_quoted_needle(self):
        quoted = json.dumps({"type": "user", "content": cost_line(9.0)})
        self.transcript.write_text(cost_line(1.5) + "\n" + quoted + "\n")
        self.assertEqual(1.5, usage.last_cost_state(self.transcript)["total_usd"])

    def test_turn_longer_than_any_tail_keeps_counting(self):
        # Review F2: a turn whose transcript runs 20 MB past the last cost-state still finds it,
        # quickly, and keeps pricing what follows, so the budget can trip.
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        with open(self.transcript, "w") as f:
            f.write(cost_line(1.0) + "\n")
            f.write((OTHER + "\n") * 200000)
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m1", "claude-opus-5-5",
                                           {"output_tokens": 400_000})])
        self.assertGreater(self.transcript.stat().st_size, 20_000_000)
        t0 = time.monotonic()
        self.assertEqual(1.0, usage.last_cost_state(self.transcript)["total_usd"])
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual((8.0, "estimate"), (usage.run_cost(rec), usage.cost_basis(rec)))
        self.assertTrue(receipts.budget(rec)["exceeded"])

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

    # --- spending inside a turn: the CLI writes cost-state only when a turn ends ---

    def write_turn(self, path, rows, cost=None, mode="a"):
        """Append assistant responses (ts, msg_id, model, usage) and, optionally, a cost-state."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode) as f:
            for ts, mid, model, u in rows:
                f.write(json.dumps({"type": "assistant", "timestamp": ts, "message": {
                    "id": mid, "model": model, "usage": u}}) + "\n")
            if cost is not None:
                f.write(cost_line(cost) + "\n")

    def sub(self, name="agent-a1"):
        return self.tmp / "t" / "subagents" / f"{name}.jsonl"

    def test_single_long_turn_counts_subagents_and_trips_budget(self):
        # Turn 1 ends at $0.50. Turn 2 runs the whole build without a cost-state: the main thread
        # writes 100k output tokens and a subagent 300k on claude-opus-5-5 ($20 / MTok output).
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m0", "claude-opus-5-5",
                                           {"output_tokens": 1})], cost=0.50, mode="w")
        rec = run.start(self.repo, tier="full", request="x")
        rec.update(created_at="2026-10-27T10:05:00.000000+00:00", stage="build")
        run.save(self.repo, rec)
        out = {"output_tokens": 100_000}
        self.write_turn(self.transcript, [("2026-10-27T10:06:00.000Z", "m1", "claude-opus-5-5", out)])
        self.write_turn(self.sub(), [("2026-10-27T09:59:00.000Z", "old", "claude-opus-5-5", out)] + [
            (f"2026-10-27T10:1{i}:00.000Z", f"s{i}", "claude-opus-5-5", out) for i in range(3)])
        usage.record(self.repo, rec, "s1", self.transcript)
        u = rec["usage"]["s1"]
        self.assertEqual((0.5, 8.0, 8.5, 0), (u["start_usd"], u["estimated_usd"], u["last_usd"],
                                             u["unpriced"]))
        b = receipts.status(self.repo, run.load(self.repo, rec["id"]))["budget"]
        self.assertEqual((8.0, "estimate", True), (b["spent"], b["basis"], b["exceeded"]))
        # The turn ends with a main-thread reply; the CLI's own figure replaces the estimate.
        self.write_turn(self.transcript, [("2026-10-27T10:13:00.000Z", "m2", "claude-opus-5-5",
                                           {"output_tokens": 0})], cost=8.55)
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual((8.05, "cli"), (usage.run_cost(rec), usage.cost_basis(rec)))

    def test_run_started_mid_turn_excludes_earlier_spend(self):
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m0", "claude-opus-5-5",
                                           {"output_tokens": 1})], cost=1.0, mode="w")
        out = {"output_tokens": 50_000}  # $1.00 each
        self.write_turn(self.transcript, [("2026-10-27T10:10:00.000Z", "m1", "claude-opus-5-5", out)])
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T10:20:00.000000+00:00"
        run.save(self.repo, rec)
        self.write_turn(self.sub(), [("2026-10-27T10:30:00.000Z", "s1", "claude-opus-5-5", out)])
        usage.record(self.repo, rec, "s1", self.transcript)
        u = rec["usage"]["s1"]
        self.assertEqual((2.0, 3.0, True), (u["start_usd"], u["last_usd"], u["start_estimated"]))
        self.assertEqual((1.0, "estimate"), (usage.run_cost(rec), usage.cost_basis(rec)))

    def test_first_turn_without_cost_state_is_estimated(self):
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m1", "claude-opus-5-5", {
            "input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
            "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000,
                               "ephemeral_1h_input_tokens": 1_000_000},
            "server_tool_use": {"web_search_requests": 3}})], mode="w")
        usage.record(self.repo, rec, "s1", self.transcript)
        # $4 input + $5 + $8 cache writes + $0.20 cache read + 3 searches x $0.01
        self.assertAlmostEqual(17.23, usage.run_cost(rec))

    def test_streamed_blocks_count_once_with_the_last_usage(self):
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        self.write_turn(self.transcript, [
            ("2026-10-27T10:00:00.000Z", "m1", "claude-opus-5-5", {"output_tokens": 8}),
            ("2026-10-27T10:00:01.000Z", "m1", "claude-opus-5-5", {"output_tokens": 50_000})],
            mode="w")
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertAlmostEqual(1.0, usage.run_cost(rec))

    def test_unpriced_model_leaves_cost_unknown_until_the_turn_ends(self):
        self.write_turn(self.transcript, [], cost=1.0, mode="w")
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m1", "claude-new-9",
                                           {"output_tokens": 10})])
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual((None, 1), (usage.run_cost(rec), rec["usage"]["s1"]["unpriced"]))
        b = receipts.status(self.repo, rec)["budget"]
        self.assertEqual((None, False, "unpriced"), (b["spent"], b["known"], b["basis"]))
        with open(self.transcript, "a") as f:
            f.write(cost_line(1.5) + "\n")
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual(0.5, usage.run_cost(rec))

    def test_estimate_above_the_cli_figure_is_not_a_restart(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.spend(rec, 1.0)
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m1", "claude-opus-5-5",
                                           {"output_tokens": 100_000})])
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual(2.0, usage.run_cost(rec))
        self.spend(rec, 2.9)  # the CLI priced the turn a little below the estimate
        self.assertEqual((1.9, "cli"), (usage.run_cost(rec), usage.cost_basis(rec)))

    def test_brief_and_band_label_the_estimate(self):
        from cvcore import hud
        rec = run.start(self.repo, tier="full", request="x")
        self.write_turn(self.transcript, [("9999-01-01T00:00:00.000Z", "m1", "claude-opus-5-5",
                                           {"output_tokens": 50_000})], mode="w")
        run.update(self.repo, rec, lambda r: r.setdefault("transcripts", {}).update(
            s1=str(self.transcript)) or r["sessions"].append("s1"))
        self.assertEqual((1.0, "estimate"), tuple(hud.band(self.repo, "s1")[k]
                                                   for k in ("cost_usd", "cost_basis")))
        self.assertIn("cost ~$1.00 (estimate)", hud.brief(self.repo, "s1"))

    def test_workflow_agents_are_counted_once(self):
        # Review F1: Workflow agents write subagents/workflows/wf_*/agent-*.jsonl.
        self.write_turn(self.transcript, [], cost=0.0, mode="w")
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        out = {"output_tokens": 200_000}  # $4.00
        self.write_turn(self.sub(), [("2026-10-27T10:00:00.000Z", "s1", "claude-opus-5-5", out)])
        wf = self.tmp / "t" / "subagents" / "workflows" / "wf_x" / "agent-a2.jsonl"
        rows = [("2026-10-27T10:01:00.000Z", "w1", "claude-opus-5-5", out)]
        self.write_turn(wf, rows)
        self.write_turn(wf.with_name("agent-a3.jsonl"), rows)  # same message id seen twice
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual(8.0, usage.run_cost(rec))

    def test_unpriced_request_after_creation_keeps_the_start(self):
        # Review F3: priced $4 before the first look, then a fast-mode request: the start must stay
        # at creation, so the turn-end figure counts the $4 too.
        self.write_turn(self.transcript, [("2026-10-27T10:00:00.000Z", "m0", "claude-opus-5-5",
                                           {"output_tokens": 0})], cost=1.0, mode="w")
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T10:10:00.000000+00:00"
        self.write_turn(self.transcript, [
            ("2026-10-27T10:20:00.000Z", "m1", "claude-opus-5-5", {"output_tokens": 200_000}),
            ("2026-10-27T10:21:00.000Z", "m2", "claude-opus-5-5", {"output_tokens": 1,
                                                                    "speed": "fast"})])
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual((1.0, None), (rec["usage"]["s1"]["start_usd"], usage.run_cost(rec)))
        self.write_turn(self.transcript, [("2026-10-27T10:22:00.000Z", "m3", "claude-opus-5-5",
                                           {"output_tokens": 0})], cost=13.0)
        usage.record(self.repo, rec, "s1", self.transcript)
        self.assertEqual((12.0, "cli"), (usage.run_cost(rec), usage.cost_basis(rec)))

    def test_malformed_lines_are_skipped_not_fatal(self):
        # Review F4: no timestamp is skipped; a non-numeric count is unpriced; the rest still counts.
        rec = run.start(self.repo, tier="full", request="x")
        rec["created_at"] = "2026-10-27T09:00:00.000000+00:00"
        with open(self.transcript, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"id": "x", "usage": {}}}) + "\n")
        self.write_turn(self.transcript, [
            ("2026-10-27T10:00:00.000Z", "m1", "claude-opus-5-5", {"output_tokens": 50_000}),
            ("2026-10-27T10:01:00.000Z", "m2", "claude-opus-5-5", {"output_tokens": "many"})])
        cs = usage.cost_state("s1", self.transcript, rec["created_at"])
        self.assertEqual((1.0, 1), (cs["estimated_usd"], cs["unpriced"]))

    def test_cli_usage_prints_the_basis(self):
        # Review F5.
        run.start(self.repo, tier="full", request="x")
        self.write_turn(self.transcript, [("9999-01-01T00:00:00.000Z", "m1", "claude-opus-5-5",
                                           {"output_tokens": 50_000})], mode="w")
        r = helpers.cli(self.repo, "usage", "--session", "s1", "--transcript",
                        str(self.transcript))
        self.assertEqual(0, r.returncode, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((1.0, "estimate"), (out["run_cost_usd"], out["cost_basis"]))

    def test_cli_usage(self):
        rec = run.start(self.repo, tier="full", request="x")
        self.transcript.write_text(cost_line(2.0) + "\n")
        r = helpers.cli(self.repo, "usage", "--session", "s1", "--transcript",
                        str(self.transcript))
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(2.0, run.load(self.repo, rec["id"])["usage"]["s1"]["start_usd"])


if __name__ == "__main__":
    unittest.main()
