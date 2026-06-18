import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from llm_bidding import cli
from llm_bidding.providers import MockBidProvider

from helpers import RISKY_TASK, SAFE_TASK


class _CliBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = str(Path(tmp.name) / "history.db")
        self.providers = {
            "anthropic": MockBidProvider(),
            "openai": MockBidProvider(),
        }

    def _run(self, *argv: str, providers=None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.run(
                ["--db", self.db_path, *argv],
                providers=providers if providers is not None else self.providers,
                env={},
            )
        return code, stdout.getvalue(), stderr.getvalue()


class CliTestCase(_CliBase):
    def test_bid_text_output_and_exit_code(self):
        code, out, _ = self._run("bid", "--intent-text", SAFE_TASK)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("WINNER", out)
        self.assertIn("Auction", out)

    def test_bid_json_output(self):
        code, out, _ = self._run("--format", "json", "bid", "--intent-text", RISKY_TASK)
        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(out)
        self.assertEqual(payload["intent"]["band"], "High Risk")
        self.assertIsNotNone(payload["winner"])
        self.assertEqual(len(payload["bids"]), 3)

    def test_bid_no_valid_bids_exits_2(self):
        failing = MockBidProvider(fail_agents={"claude-opus", "claude-sonnet", "gpt"})
        code, _, _ = self._run(
            "bid", "--intent-text", SAFE_TASK,
            providers={"anthropic": failing, "openai": failing},
        )
        self.assertEqual(code, cli.EXIT_NO_WINNER)

    def test_full_feedback_loop(self):
        # 1. Run an auction and capture the auction id.
        code, out, _ = self._run("--format", "json", "bid", "--intent-text", RISKY_TASK)
        self.assertEqual(code, cli.EXIT_OK)
        auction = json.loads(out)
        auction_id = auction["auction_id"]
        winner = auction["winner"]["agent_name"]

        # 2. Report a failure for the winner.
        code, out, _ = self._run("report", "--auction-id", auction_id, "--failure")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("failure", out)

        # 3. Stats now reflect the outcome.
        code, out, _ = self._run("--format", "json", "stats", "--agent", winner)
        self.assertEqual(code, cli.EXIT_OK)
        stats = json.loads(out)[0]
        self.assertEqual(stats["outcomes_reported"], 1)
        self.assertEqual(stats["successes"], 0)
        self.assertLess(stats["success_rate"], 0.5)

        # 4. The next identical auction sees the lower history-driven utility.
        code, out, _ = self._run("--format", "json", "bid", "--intent-text", RISKY_TASK)
        self.assertEqual(code, cli.EXIT_OK)
        second = json.loads(out)
        winner_bid = next(b for b in second["bids"] if b["agent_name"] == winner)
        self.assertLess(winner_bid["stats"]["success_rate"], 0.5)
        first_bid = next(b for b in auction["bids"] if b["agent_name"] == winner)
        self.assertLess(winner_bid["utility"], first_bid["utility"])

    def test_report_with_diff_scores_it(self):
        code, out, _ = self._run("--format", "json", "bid", "--intent-text", SAFE_TASK)
        auction_id = json.loads(out)["auction_id"]
        diff = (
            "--- a/views/profile.css\n"
            "+++ b/views/profile.css\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        diff_file = Path(self.db_path).parent / "work.diff"
        diff_file.write_text(diff, encoding="utf-8")
        code, out, _ = self._run(
            "--format", "json", "report", "--auction-id", auction_id,
            "--success", "--diff", str(diff_file),
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIsInstance(json.loads(out)["diff_score"], int)

    def test_report_unknown_auction_errors(self):
        code, _, err = self._run("report", "--auction-id", "missing", "--success")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("No auction", err)

    def test_dry_run_persists_nothing(self):
        code, _, _ = self._run("bid", "--intent-text", SAFE_TASK, "--dry-run")
        self.assertEqual(code, cli.EXIT_OK)
        code, out, _ = self._run("--format", "json", "stats")
        for row in json.loads(out):
            self.assertEqual(row["auctions_entered"], 0)

    def test_agents_list(self):
        code, out, _ = self._run("agents", "list")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("claude-opus", out)
        self.assertIn("claude-sonnet", out)
        self.assertIn("gpt", out)

    def test_agent_subset_flag(self):
        code, out, _ = self._run(
            "--format", "json", "bid", "--intent-text", SAFE_TASK,
            "--agents", "claude-sonnet,gpt",
        )
        self.assertEqual(code, cli.EXIT_OK)
        names = {b["agent_name"] for b in json.loads(out)["bids"]}
        self.assertEqual(names, {"claude-sonnet", "gpt"})

    def test_empty_intent_errors(self):
        code, _, err = self._run("bid", "--intent-text", "   ")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("empty", err)

    def test_propose_dry_run_outputs_actor_prompt(self):
        context_file = Path(self.db_path).parent / "README.md"
        context_file.write_text("# Project\n", encoding="utf-8")

        code, out, _ = self._run(
            "propose",
            "--task-text",
            "Improve the OSS quickstart.",
            "--agent",
            "gpt",
            "--context",
            str(context_file),
            "--dry-run",
        )

        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("gpt", out)
        self.assertIn("Improve the OSS quickstart.", out)
        self.assertIn("unified diff", out)
        self.assertIn("# Project", out)


RISKY_DIFF = (
    "--- a/db/migrations/001_auth.py\n"
    "+++ b/db/migrations/001_auth.py\n"
    "@@ -1,2 +1,4 @@\n"
    "-pass\n"
    "+def migrate(auth_store):\n"
    "+    auth_store.execute('DROP TABLE sessions')\n"
    "+    auth_store.commit_transaction()\n"
)


class CliV2TestCase(_CliBase):
    """Coverage for the v0.2.0 surface: policy, drift, and ops commands."""

    def _bid_json(self, task):
        code, out, _ = self._run("--format", "json", "bid", "--intent-text", task)
        self.assertEqual(code, cli.EXIT_OK)
        return json.loads(out)

    def test_bid_output_includes_supervision_line(self):
        code, out, _ = self._run("bid", "--intent-text", SAFE_TASK)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Supervision: Unsupervised", out)

    def test_auction_json_records_scoring_version(self):
        auction = self._bid_json(SAFE_TASK)
        self.assertNotEqual(auction["scoring_version"], "")

    def test_abstain_via_min_award_utility_exits_2(self):
        config_path = Path(self.db_path).parent / "strict.json"
        config_path.write_text(
            json.dumps({"policy": {"min_award_utility": 0.99}}), encoding="utf-8"
        )
        code, out, _ = self._run(
            "--config", str(config_path), "bid", "--intent-text", SAFE_TASK
        )
        self.assertEqual(code, cli.EXIT_NO_WINNER)
        self.assertIn("min_award_utility", out)

    def test_high_risk_floor_marks_ineligible(self):
        config_path = Path(self.db_path).parent / "floor.json"
        config_path.write_text(
            json.dumps(
                {"policy": {"high_risk_floor": {"min_band_success_rate": 0.99}}}
            ),
            encoding="utf-8",
        )
        code, out, _ = self._run(
            "--config", str(config_path), "bid", "--intent-text", RISKY_TASK
        )
        self.assertEqual(code, cli.EXIT_NO_WINNER)
        self.assertIn("INELIGIBLE", out)
        self.assertIn("High Risk floor", out)

    def test_report_diff_detects_scope_drift(self):
        auction = self._bid_json(SAFE_TASK)
        diff_file = Path(self.db_path).parent / "drift.diff"
        diff_file.write_text(RISKY_DIFF, encoding="utf-8")
        code, out, _ = self._run(
            "report", "--auction-id", auction["auction_id"],
            "--success", "--diff", str(diff_file),
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("SCOPE DRIFT", out)

        code, out, _ = self._run("show", "--auction-id", auction["auction_id"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("SCOPE DRIFT", out)

    def test_show_renders_full_auction(self):
        auction = self._bid_json(RISKY_TASK)
        code, out, _ = self._run("show", "--auction-id", auction["auction_id"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("WINNER", out)
        self.assertIn("Supervision: Pair Programming", out)
        self.assertIn("not reported yet", out)

    def test_show_unknown_auction_exits_1(self):
        code, _, err = self._run("show", "--auction-id", "missing")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("No auction", err)

    def test_history_lists_auctions(self):
        self._bid_json(SAFE_TASK)
        code, out, _ = self._run("--format", "json", "history", "--limit", "5")
        self.assertEqual(code, cli.EXIT_OK)
        rows = json.loads(out)
        self.assertEqual(len(rows), 1)
        self.assertIn("recommended_mode", rows[0])

    def test_export_produces_parseable_jsonl(self):
        auction = self._bid_json(SAFE_TASK)
        self._run("report", "--auction-id", auction["auction_id"], "--success")
        code, out, _ = self._run("export")
        self.assertEqual(code, cli.EXIT_OK)
        rows = [json.loads(line) for line in out.strip().splitlines()]
        types = {row["type"] for row in rows}
        self.assertEqual(types, {"auction", "bid", "outcome"})

    def test_export_to_file(self):
        self._bid_json(SAFE_TASK)
        out_file = Path(self.db_path).parent / "dump.jsonl"
        code, out, _ = self._run("export", "--output", str(out_file))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Exported", out)
        self.assertTrue(out_file.exists())

    def test_prune_reports_deleted_count(self):
        code, out, _ = self._run("prune", "--keep-days", "30")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Deleted 0", out)

    def test_stats_shows_cost_ratio_and_drifts(self):
        auction = self._bid_json(SAFE_TASK)
        self._run(
            "report", "--auction-id", auction["auction_id"],
            "--success", "--actual-cost", "0.5",
        )
        code, out, _ = self._run("stats", "--agent", auction["winner"]["agent_name"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("cost ratio", out)
        self.assertIn("scope drifts", out)


if __name__ == "__main__":
    unittest.main()
