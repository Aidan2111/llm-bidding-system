import datetime
import unittest

from llm_bidding.history import HistoryError, HistoryStore
from llm_bidding.models import OutcomeReport

from helpers import CONFIG, RISKY_TASK, SAFE_TASK, make_auction, make_scored_bid


PARAMS = CONFIG.calibration


def _report(auction_id: str, success: bool) -> OutcomeReport:
    return OutcomeReport(
        auction_id=auction_id,
        success=success,
        reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def _record_auction(self, auction_id, winner_name="a", task_text=RISKY_TASK,
                        confidence=0.8):
        winner = make_scored_bid(winner_name, confidence=confidence, utility=0.9)
        loser = make_scored_bid("b", utility=0.4)
        result = make_auction(
            auction_id, task_text=task_text, bids=(winner, loser), winner=winner
        )
        self.store.record_auction(result)
        return result

    def test_record_and_stats_round_trip(self):
        self._record_auction("a1")
        self.store.record_outcome(_report("a1", success=True))

        stats = self.store.agent_stats("a", PARAMS)
        self.assertEqual(stats.auctions_entered, 1)
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.outcomes_reported, 1)
        self.assertEqual(stats.successes, 1)
        self.assertAlmostEqual(stats.success_rate, (1 + 4 * 0.5) / (1 + 4))
        self.assertEqual(stats.calibration_offset, 0.0)  # below min samples
        self.assertAlmostEqual(stats.brier_score, (0.8 - 1.0) ** 2)

        loser_stats = self.store.agent_stats("b", PARAMS)
        self.assertEqual(loser_stats.wins, 0)
        self.assertEqual(loser_stats.outcomes_reported, 0)
        self.assertEqual(loser_stats.success_rate, 0.5)

    def test_band_filter(self):
        self._record_auction("risky", task_text=RISKY_TASK)
        self._record_auction("safe", task_text=SAFE_TASK)
        self.store.record_outcome(_report("risky", success=False))

        high = self.store.agent_stats("a", PARAMS, band="High Risk")
        self.assertEqual(high.auctions_entered, 1)
        self.assertEqual(high.outcomes_reported, 1)
        self.assertEqual(high.successes, 0)

        low = self.store.agent_stats("a", PARAMS, band="Low Risk")
        self.assertEqual(low.auctions_entered, 1)
        self.assertEqual(low.outcomes_reported, 0)

    def test_signal_stats(self):
        result = self._record_auction("s1", task_text=RISKY_TASK)
        signal_names = [s.name for s in result.intent.signals]
        self.assertIn("intent:critical-domain", signal_names)
        stats = self.store.signal_stats("a", "intent:critical-domain", PARAMS)
        self.assertEqual(stats.auctions_entered, 1)
        missing = self.store.signal_stats("a", "intent:not-a-signal", PARAMS)
        self.assertEqual(missing.auctions_entered, 0)

    def test_failed_bids_do_not_count_as_entered(self):
        winner = make_scored_bid("a", utility=0.9)
        failed = make_scored_bid("c", error="provider exploded")
        result = make_auction("f1", bids=(winner, failed), winner=winner)
        self.store.record_auction(result)
        stats = self.store.agent_stats("c", PARAMS)
        self.assertEqual(stats.auctions_entered, 0)

    def test_outcome_for_unknown_auction_errors(self):
        with self.assertRaises(HistoryError):
            self.store.record_outcome(_report("missing", success=True))

    def test_duplicate_outcome_errors(self):
        self._record_auction("a1")
        self.store.record_outcome(_report("a1", success=True))
        with self.assertRaises(HistoryError):
            self.store.record_outcome(_report("a1", success=False))

    def test_outcome_for_winnerless_auction_errors(self):
        failed = make_scored_bid("a", error="boom")
        result = make_auction("nw", bids=(failed,), winner=None)
        self.store.record_auction(result)
        with self.assertRaises(HistoryError):
            self.store.record_outcome(_report("nw", success=True))

    def test_list_recent(self):
        self._record_auction("a1")
        self.store.record_outcome(_report("a1", success=True))
        rows = self.store.list_recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["auction_id"], "a1")
        self.assertEqual(rows[0]["winner"], "a")
        self.assertTrue(rows[0]["outcome"])


class DepIntegrationTests(unittest.TestCase):
    """Guard against upstream agent-autonomy-score renames on version bumps."""

    def test_risky_intent_band_and_signals_flow_into_history(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        winner = make_scored_bid("a", utility=0.9)
        result = make_auction("dep", task_text=RISKY_TASK, bids=(winner,), winner=winner)
        self.assertEqual(result.intent.band, "High Risk")
        store.record_auction(result)
        row = store.list_recent()[0]
        self.assertEqual(row["intent_band"], "High Risk")
        self.assertEqual(row["recommended_mode"], "Pair Programming")

    def test_scoring_version_and_drift_columns_round_trip(self):
        import dataclasses

        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        winner = make_scored_bid("a", utility=0.9)
        result = dataclasses.replace(
            make_auction("v2", bids=(winner,), winner=winner),
            scoring_version="0.2.0",
        )
        store.record_auction(result)
        store.record_outcome(
            OutcomeReport(
                auction_id="v2",
                success=True,
                reported_at="2026-06-10T00:00:00+00:00",
                diff_score=8,
                scope_drift=True,
                gate_score=9,
            )
        )
        record = store.get_auction("v2")
        self.assertEqual(record["scoring_version"], "0.2.0")
        self.assertEqual(record["recommended_mode"], "Pair Programming")
        self.assertEqual(record["outcome"]["scope_drift"], 1)
        self.assertEqual(record["outcome"]["gate_score"], 9)
        stats = store.agent_stats("a", PARAMS)
        self.assertEqual(stats.drifts, 1)


if __name__ == "__main__":
    unittest.main()
