import unittest

from llm_bidding.models import AgentProfile, AgentStats, Bid
from llm_bidding.utility import compute_scored_bid, estimate_cost_usd, failed_bid

from helpers import CONFIG


AGENT = AgentProfile(
    name="claude-opus",
    provider="anthropic",
    model_id="claude-opus-4-8",
    input_cost_per_mtok=5.0,
    output_cost_per_mtok=25.0,
)

BID = Bid(
    agent_name="claude-opus",
    model_id="claude-opus-4-8",
    confidence=0.8,
    approach="Do the thing.",
    estimated_input_tokens=1000,
    estimated_output_tokens=1000,
    declared_effort="moderate",
)


def _stats(
    *, success_rate=0.5, calibration_offset=0.0, outcomes=0, band=None
) -> AgentStats:
    return AgentStats(
        agent_name="claude-opus",
        band=band,
        auctions_entered=outcomes,
        wins=outcomes,
        outcomes_reported=outcomes,
        successes=0,
        win_rate=0.0,
        success_rate=success_rate,
        brier_score=None,
        calibration_offset=calibration_offset,
    )


class UtilityTests(unittest.TestCase):
    def test_cost_estimate(self):
        # 1000 in @ $5/M + 1000 out @ $25/M
        self.assertAlmostEqual(estimate_cost_usd(BID, AGENT), 0.03)

    def test_hand_computed_utility_cold_start(self):
        scored = compute_scored_bid(BID, AGENT, _stats(), _stats(band="High Risk"), CONFIG)
        # quality = 0.6*0.8 + 0.4*0.5 = 0.68
        self.assertAlmostEqual(scored.quality_score, 0.68)
        # price = 1 - 0.03/2.0 = 0.985
        self.assertAlmostEqual(scored.price_score, 0.985)
        # risk_fit falls back to overall (shrunk) success rate = 0.5
        self.assertAlmostEqual(scored.risk_fit_score, 0.5)
        # utility = 0.5*0.68 + 0.2*0.985 + 0.3*0.5
        self.assertAlmostEqual(scored.utility, 0.687)

    def test_band_stats_used_when_enough_samples(self):
        band = _stats(success_rate=0.9, outcomes=5, band="High Risk")
        scored = compute_scored_bid(BID, AGENT, _stats(), band, CONFIG)
        self.assertAlmostEqual(scored.risk_fit_score, 0.9)

    def test_calibration_offset_shifts_confidence(self):
        overconfident = _stats(calibration_offset=-0.2)
        scored = compute_scored_bid(
            BID, AGENT, overconfident, _stats(band="High Risk"), CONFIG
        )
        self.assertAlmostEqual(scored.calibrated_confidence, 0.6)

    def test_calibrated_confidence_is_clamped(self):
        bid = Bid(**{**BID.to_dict(), "confidence": 0.95})
        underconfident = _stats(calibration_offset=0.2)
        scored = compute_scored_bid(
            bid, AGENT, underconfident, _stats(band="High Risk"), CONFIG
        )
        self.assertEqual(scored.calibrated_confidence, 1.0)

    def test_cost_above_ceiling_floors_price_at_zero(self):
        expensive_bid = Bid(
            **{
                **BID.to_dict(),
                "estimated_input_tokens": 10_000_000,
                "estimated_output_tokens": 10_000_000,
            }
        )
        scored = compute_scored_bid(
            expensive_bid, AGENT, _stats(), _stats(band="High Risk"), CONFIG
        )
        self.assertEqual(scored.price_score, 0.0)

    def test_failed_bid_shape(self):
        scored = failed_bid("claude-opus", "boom")
        self.assertFalse(scored.is_valid)
        self.assertEqual(scored.utility, 0.0)
        self.assertEqual(scored.error, "boom")


if __name__ == "__main__":
    unittest.main()
