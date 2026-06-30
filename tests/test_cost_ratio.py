import dataclasses
import datetime
import unittest

from llm_bidding.calibration import shrunk_cost_ratio
from llm_bidding.history import HistoryStore
from llm_bidding.models import AgentProfile, AgentStats, Bid, OutcomeReport
from llm_bidding.utility import compute_scored_bid

from helpers import CONFIG, make_auction, make_scored_bid


PARAMS = CONFIG.calibration


class ShrunkCostRatioTests(unittest.TestCase):
    def test_cold_start_is_exactly_neutral(self):
        self.assertEqual(shrunk_cost_ratio([], PARAMS), 1.0)

    def test_overrunning_agent_ratio_rises(self):
        # One outcome at 3x actual vs estimated: (3 + 4) / (1 + 4) = 1.4
        self.assertAlmostEqual(shrunk_cost_ratio([3.0], PARAMS), 1.4)

    def test_clamping(self):
        self.assertEqual(shrunk_cost_ratio([100.0] * 50, PARAMS), PARAMS.cost_ratio_max)
        self.assertEqual(shrunk_cost_ratio([0.0001] * 50, PARAMS), PARAMS.cost_ratio_min)


class HistoryCostRatioTests(unittest.TestCase):
    def test_agent_stats_computes_ratio_from_outcomes(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        winner = make_scored_bid("a", utility=0.9, cost=0.10)
        store.record_auction(make_auction("c1", bids=(winner,), winner=winner))
        store.record_outcome(
            OutcomeReport(
                auction_id="c1",
                success=True,
                reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                actual_cost_usd=0.30,  # 3x the estimate
            )
        )
        stats = store.agent_stats("a", PARAMS)
        self.assertAlmostEqual(stats.cost_ratio, shrunk_cost_ratio([3.0], PARAMS))

    def test_no_actual_costs_means_neutral_ratio(self):
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        winner = make_scored_bid("a", utility=0.9)
        store.record_auction(make_auction("c2", bids=(winner,), winner=winner))
        stats = store.agent_stats("a", PARAMS)
        self.assertEqual(stats.cost_ratio, 1.0)

    def test_ratio_is_measured_against_raw_not_adjusted_estimate(self):
        """Regression: an accurate estimate must yield ratio sample 1.0 even
        when the stored (price-facing) estimate was already ratio-adjusted."""
        store = HistoryStore(":memory:")
        self.addCleanup(store.close)
        # Simulate a later round: raw estimate 0.10, but a prior 2x ratio means
        # the stored/price-facing estimate is 0.20. The model nailed it: actual
        # equals the raw estimate, so the new ratio sample must be 1.0 (not 0.5).
        winner = dataclasses.replace(
            make_scored_bid("a", utility=0.9, cost=0.20),
            raw_estimated_cost_usd=0.10,
        )
        store.record_auction(make_auction("c3", bids=(winner,), winner=winner))
        store.record_outcome(
            OutcomeReport(
                auction_id="c3",
                success=True,
                reported_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                actual_cost_usd=0.10,
            )
        )
        stats = store.agent_stats("a", PARAMS)
        self.assertEqual(stats.cost_ratio, 1.0)


class UtilityCostRatioTests(unittest.TestCase):
    AGENT = AgentProfile(
        name="a", provider="mock", model_id="m",
        input_cost_per_mtok=5.0, output_cost_per_mtok=25.0,
    )
    BID = Bid(
        agent_name="a", model_id="m", confidence=0.8, approach="x",
        estimated_input_tokens=1000, estimated_output_tokens=1000,
        declared_effort="moderate",
    )

    def _stats(self, cost_ratio):
        return AgentStats(
            agent_name="a", band=None, auctions_entered=0, wins=0,
            outcomes_reported=0, successes=0, win_rate=0.0, success_rate=0.5,
            brier_score=None, calibration_offset=0.0, cost_ratio=cost_ratio,
        )

    def test_ratio_scales_the_cost_estimate(self):
        neutral = compute_scored_bid(
            self.BID, self.AGENT, self._stats(1.0), self._stats(1.0), CONFIG
        )
        doubled = compute_scored_bid(
            self.BID, self.AGENT, self._stats(2.0), self._stats(2.0), CONFIG
        )
        self.assertAlmostEqual(doubled.estimated_cost_usd, neutral.estimated_cost_usd * 2)
        self.assertLess(doubled.price_score, neutral.price_score)
        self.assertLess(doubled.utility, neutral.utility)

    def test_neutral_ratio_reproduces_v01_numbers(self):
        scored = compute_scored_bid(
            self.BID, self.AGENT, self._stats(1.0), self._stats(1.0), CONFIG
        )
        self.assertAlmostEqual(scored.estimated_cost_usd, 0.03)
        self.assertAlmostEqual(scored.utility, 0.687)


if __name__ == "__main__":
    unittest.main()
