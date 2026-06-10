import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from llm_bidding import cli
from llm_bidding.providers import MockBidProvider

from helpers import RISKY_TASK, SAFE_TASK


class CliTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
