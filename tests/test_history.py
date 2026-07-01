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


class CountAndPendingTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore(":memory:")
        self.addCleanup(self.store.close)

    def _record(self, auction_id, task_text=RISKY_TASK, with_outcome=False):
        winner = make_scored_bid("a", utility=0.9)
        self.store.record_auction(
            make_auction(auction_id, task_text=task_text, bids=(winner,), winner=winner)
        )
        if with_outcome:
            self.store.record_outcome(
                OutcomeReport(
                    auction_id=auction_id,
                    success=True,
                    reported_at="2026-06-11T00:00:00+00:00",
                )
            )

    def test_count_auctions_total_and_by_band(self):
        self.assertEqual(self.store.count_auctions(), 0)
        self._record("h1", task_text=RISKY_TASK)
        self._record("h2", task_text=SAFE_TASK)
        self.assertEqual(self.store.count_auctions(), 2)
        self.assertEqual(self.store.count_auctions(band="High Risk"), 1)
        self.assertEqual(self.store.count_auctions(band="Low Risk"), 1)
        self.assertEqual(self.store.count_auctions(band="Medium Risk"), 0)

    def test_list_unreported_returns_only_outcome_less_winners(self):
        self._record("reported", with_outcome=True)
        self._record("open1")
        # A winnerless auction is not "pending" — there is nothing to report.
        failed = make_scored_bid("a", error="boom")
        self.store.record_auction(make_auction("nowin", bids=(failed,), winner=None))
        rows = self.store.list_unreported()
        self.assertEqual([r["auction_id"] for r in rows], ["open1"])
        self.assertEqual(rows[0]["winner"], "a")


class PruneRobustnessTests(unittest.TestCase):
    def test_unparseable_timestamps_are_kept_not_deleted(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        old = make_scored_bid("a", utility=0.9)
        store.record_auction(
            make_auction("old", bids=(old,), winner=old,
                         created_at="2026-01-01T00:00:00+00:00")
        )
        weird = make_scored_bid("a", utility=0.9)
        store.record_auction(
            make_auction("weird", bids=(weird,), winner=weird,
                         created_at="not-a-timestamp")
        )
        deleted = store.prune(30, now="2026-06-10T00:00:00+00:00")
        self.assertEqual(deleted, 1)  # only the genuinely old auction
        remaining = {r["auction_id"] for r in store.list_recent()}
        self.assertIn("weird", remaining)

    def test_naive_timestamps_are_treated_as_utc(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        naive = make_scored_bid("a", utility=0.9)
        store.record_auction(
            make_auction("naive", bids=(naive,), winner=naive,
                         created_at="2026-01-01T00:00:00")  # no offset
        )
        deleted = store.prune(30, now="2026-06-10T00:00:00+00:00")
        self.assertEqual(deleted, 1)


if __name__ == "__main__":
    unittest.main()
