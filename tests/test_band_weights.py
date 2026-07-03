import json
import tempfile
import unittest
from pathlib import Path

from llm_bidding.config import ConfigError, load_config
from llm_bidding.infrastructure.configuration import UtilityWeights


def _write(data: dict) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, handle)
    handle.close()
    return handle.name


class BandWeightsConfigTests(unittest.TestCase):
    def test_default_has_no_band_overrides(self):
        config = load_config()
        self.assertEqual(config.band_weights, {})
        # weights_for falls back to global for every band and for None.
        self.assertEqual(config.weights_for("High Risk"), config.weights)
        self.assertEqual(config.weights_for(None), config.weights)

    def test_band_override_is_used_for_that_band_only(self):
        path = _write(
            {
                "utility": {
                    "band_weights": {
                        # Low Risk: lean hard on price (cheap work, don't overpay).
                        "Low Risk": {"quality": 0.2, "price": 0.7, "risk_fit": 0.1},
                        # High Risk: lean on proven track record.
                        "High Risk": {"quality": 0.3, "price": 0.0, "risk_fit": 0.7},
                    }
                }
            }
        )
        self.addCleanup(Path(path).unlink)
        config = load_config(path)
        self.assertEqual(
            config.weights_for("Low Risk"),
            UtilityWeights(quality=0.2, price=0.7, risk_fit=0.1),
        )
        self.assertEqual(
            config.weights_for("High Risk"),
            UtilityWeights(quality=0.3, price=0.0, risk_fit=0.7),
        )
        # Medium Risk wasn't overridden -> global weights.
        self.assertEqual(config.weights_for("Medium Risk"), config.weights)

    def test_partial_override_inherits_configured_globals_not_defaults(self):
        """Regression (PR #2 review): a band entry that omits keys must inherit
        the user's configured global weights, not the built-in defaults."""
        path = _write(
            {
                "utility": {
                    # Custom globals, different from the built-in 0.5/0.2/0.3.
                    "weights": {"quality": 0.6, "price": 0.1, "risk_fit": 0.3},
                    # Only quality overridden; price/risk_fit must come from above.
                    "band_weights": {"Low Risk": {"quality": 0.6}},
                }
            }
        )
        self.addCleanup(Path(path).unlink)
        config = load_config(path)
        self.assertEqual(
            config.weights_for("Low Risk"),
            UtilityWeights(quality=0.6, price=0.1, risk_fit=0.3),
        )

    def test_band_weights_must_sum_to_one(self):
        path = _write(
            {"utility": {"band_weights": {"Low Risk": {"quality": 0.5, "price": 0.5, "risk_fit": 0.5}}}}
        )
        self.addCleanup(Path(path).unlink)
        with self.assertRaises(ConfigError):
            load_config(path)

    def test_unknown_band_is_rejected(self):
        path = _write(
            {"utility": {"band_weights": {"Catastrophic Risk": {"quality": 1.0, "price": 0.0, "risk_fit": 0.0}}}}
        )
        self.addCleanup(Path(path).unlink)
        with self.assertRaises(ConfigError):
            load_config(path)


class BandWeightsScoringTests(unittest.TestCase):
    """Per-band weights actually change the utility a bid receives."""

    def test_low_risk_price_lean_changes_utility(self):
        import dataclasses
        from llm_bidding.models import AgentProfile, AgentStats, Bid
        from llm_bidding.utility import compute_scored_bid

        base = load_config()
        price_lean = dataclasses.replace(
            base,
            band_weights={
                "Low Risk": UtilityWeights(quality=0.0, price=1.0, risk_fit=0.0)
            },
        )
        agent = AgentProfile(
            name="a", provider="mock", model_id="m",
            input_cost_per_mtok=5.0, output_cost_per_mtok=25.0,
        )
        bid = Bid(
            agent_name="a", model_id="m", confidence=0.8, approach="x",
            estimated_input_tokens=1000, estimated_output_tokens=1000,
            declared_effort="trivial",
        )
        low_band_stats = AgentStats(
            agent_name="a", band="Low Risk", auctions_entered=0, wins=0,
            outcomes_reported=0, successes=0, win_rate=0.0, success_rate=0.5,
            brier_score=None, calibration_offset=0.0,
        )
        stats = dataclasses.replace(low_band_stats, band=None)
        scored = compute_scored_bid(bid, agent, stats, low_band_stats, price_lean)
        # With price weight 1.0, utility must equal the price score exactly.
        self.assertAlmostEqual(scored.utility, scored.price_score)


if __name__ == "__main__":
    unittest.main()
