import unittest

from llm_bidding.policy import (
    NO_VALID_BIDS_REASON,
    PolicyParams,
    apply_eligibility,
    select_winner,
)

from helpers import make_scored_bid


def _bid(name, *, utility=0.5, quality=0.5, cost=0.01, confidence=0.8, error=None):
    bid = make_scored_bid(name, confidence=confidence, utility=utility, cost=cost,
                          error=error)
    # helpers fixes quality_score at 0.5; rebuild when a test needs another value
    if quality != 0.5 and error is None:
        import dataclasses

        bid = dataclasses.replace(bid, quality_score=quality)
    return bid


class EligibilityTests(unittest.TestCase):
    def test_no_floor_configured_is_a_no_op(self):
        bids = [_bid("a"), _bid("b")]
        out = apply_eligibility(bids, "High Risk", PolicyParams())
        self.assertTrue(all(b.eligible for b in out))

    def test_floor_only_applies_to_high_risk(self):
        policy = PolicyParams(high_risk_min_band_success_rate=0.99)
        out = apply_eligibility([_bid("a")], "Low Risk", policy)
        self.assertTrue(out[0].eligible)

    def test_or_semantics_either_threshold_passes(self):
        # risk_fit_score is 0.5 in the fixture; confidence 0.8
        policy = PolicyParams(
            high_risk_min_band_success_rate=0.9,
            high_risk_min_calibrated_confidence=0.7,
        )
        out = apply_eligibility([_bid("a", confidence=0.8)], "High Risk", policy)
        self.assertTrue(out[0].eligible)  # fails sr floor, passes confidence floor

    def test_failing_both_thresholds_marks_ineligible_with_reason(self):
        policy = PolicyParams(
            high_risk_min_band_success_rate=0.9,
            high_risk_min_calibrated_confidence=0.95,
        )
        out = apply_eligibility([_bid("a", confidence=0.8)], "High Risk", policy)
        self.assertFalse(out[0].eligible)
        self.assertIn("High Risk floor", out[0].ineligible_reason)
        self.assertIn("band success rate", out[0].ineligible_reason)
        self.assertIn("calibrated confidence", out[0].ineligible_reason)

    def test_single_configured_threshold(self):
        policy = PolicyParams(high_risk_min_band_success_rate=0.9)
        out = apply_eligibility([_bid("a", confidence=0.99)], "High Risk", policy)
        self.assertFalse(out[0].eligible)  # confidence floor disabled, sr floor fails

    def test_failed_bids_pass_through_untouched(self):
        policy = PolicyParams(high_risk_min_band_success_rate=0.9)
        failed = _bid("a", error="boom")
        out = apply_eligibility([failed], "High Risk", policy)
        self.assertIs(out[0], failed)


class SelectWinnerTests(unittest.TestCase):
    def test_default_policy_is_argmax_utility(self):
        bids = [_bid("a", utility=0.5), _bid("b", utility=0.7)]
        winner, reason = select_winner(bids, PolicyParams())
        self.assertEqual(winner.agent_name, "b")
        self.assertIsNone(reason)

    def test_no_valid_bids_reason_is_stable(self):
        winner, reason = select_winner([_bid("a", error="x")], PolicyParams())
        self.assertIsNone(winner)
        self.assertEqual(reason, NO_VALID_BIDS_REASON)

    def test_all_ineligible_abstains(self):
        policy = PolicyParams(high_risk_min_band_success_rate=0.99)
        bids = apply_eligibility([_bid("a"), _bid("b")], "High Risk", policy)
        winner, reason = select_winner(bids, policy)
        self.assertIsNone(winner)
        self.assertIn("High Risk floor", reason)

    def test_min_award_utility_abstains(self):
        policy = PolicyParams(min_award_utility=0.9)
        winner, reason = select_winner([_bid("a", utility=0.5)], policy)
        self.assertIsNone(winner)
        self.assertIn("min_award_utility", reason)

    def test_cheapest_adequate_picks_cheapest(self):
        policy = PolicyParams(selection_mode="cheapest_adequate",
                              adequacy_min_quality=0.4)
        bids = [
            _bid("expensive-best", utility=0.9, cost=0.50),
            _bid("cheap-enough", utility=0.6, cost=0.01),
        ]
        winner, reason = select_winner(bids, policy)
        self.assertEqual(winner.agent_name, "cheap-enough")
        self.assertIsNone(reason)

    def test_cheapest_adequate_abstains_when_nothing_adequate(self):
        policy = PolicyParams(selection_mode="cheapest_adequate",
                              adequacy_min_quality=0.95)
        winner, reason = select_winner([_bid("a", quality=0.5)], policy)
        self.assertIsNone(winner)
        self.assertIn("adequacy threshold", reason)

    def test_ineligible_bids_never_win(self):
        policy = PolicyParams(high_risk_min_band_success_rate=0.99,
                              high_risk_min_calibrated_confidence=0.9)
        bids = apply_eligibility(
            [_bid("strong-but-unproven", utility=0.9, confidence=0.5),
             _bid("proven", utility=0.4, confidence=0.95)],
            "High Risk",
            policy,
        )
        winner, _ = select_winner(bids, policy)
        self.assertEqual(winner.agent_name, "proven")


if __name__ == "__main__":
    unittest.main()
