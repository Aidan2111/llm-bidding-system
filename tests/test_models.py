import unittest

from llm_bidding.models import AgentProfile, Bid, BidValidationError


GOOD_PAYLOAD = {
    "confidence": 0.8,
    "approach": "Make the change behind a feature flag.",
    "estimated_input_tokens": 1200,
    "estimated_output_tokens": 800,
    "declared_effort": "moderate",
}


class AgentProfileTests(unittest.TestCase):
    def test_from_dict_round_trip(self):
        profile = AgentProfile.from_dict(
            {
                "name": "claude-opus",
                "provider": "anthropic",
                "model_id": "claude-opus-4-8",
                "input_cost_per_mtok": 5.0,
                "output_cost_per_mtok": 25.0,
            }
        )
        self.assertEqual(profile.name, "claude-opus")
        self.assertTrue(profile.enabled)
        self.assertEqual(profile.to_dict()["model_id"], "claude-opus-4-8")

    def test_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            AgentProfile.from_dict(
                {
                    "name": "x",
                    "provider": "azure",
                    "model_id": "m",
                    "input_cost_per_mtok": 1,
                    "output_cost_per_mtok": 1,
                }
            )

    def test_rejects_negative_price(self):
        with self.assertRaises(ValueError):
            AgentProfile.from_dict(
                {
                    "name": "x",
                    "provider": "mock",
                    "model_id": "m",
                    "input_cost_per_mtok": -1,
                    "output_cost_per_mtok": 1,
                }
            )


class BidValidationTests(unittest.TestCase):
    def test_valid_payload(self):
        bid = Bid.from_payload(GOOD_PAYLOAD, agent_name="a", model_id="m")
        self.assertEqual(bid.confidence, 0.8)
        self.assertEqual(bid.declared_effort, "moderate")

    def test_rejects_confidence_out_of_range(self):
        payload = {**GOOD_PAYLOAD, "confidence": 1.5}
        with self.assertRaises(BidValidationError):
            Bid.from_payload(payload, agent_name="a", model_id="m")

    def test_rejects_boolean_confidence(self):
        payload = {**GOOD_PAYLOAD, "confidence": True}
        with self.assertRaises(BidValidationError):
            Bid.from_payload(payload, agent_name="a", model_id="m")

    def test_rejects_unknown_effort(self):
        payload = {**GOOD_PAYLOAD, "declared_effort": "heroic"}
        with self.assertRaises(BidValidationError):
            Bid.from_payload(payload, agent_name="a", model_id="m")

    def test_rejects_zero_tokens(self):
        payload = {**GOOD_PAYLOAD, "estimated_input_tokens": 0}
        with self.assertRaises(BidValidationError):
            Bid.from_payload(payload, agent_name="a", model_id="m")

    def test_rejects_empty_approach(self):
        payload = {**GOOD_PAYLOAD, "approach": "  "}
        with self.assertRaises(BidValidationError):
            Bid.from_payload(payload, agent_name="a", model_id="m")


if __name__ == "__main__":
    unittest.main()
