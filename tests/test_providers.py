import unittest

from llm_bidding.scoring import score_task_intent

from llm_bidding.models import AgentProfile, BidRequest
from llm_bidding.providers import (
    BidProviderError,
    MissingApiKeyError,
    MockBidProvider,
    build_providers,
)
from llm_bidding.providers.anthropic_provider import AnthropicBidProvider
from llm_bidding.providers.openai_provider import OpenAIBidProvider

from helpers import CONFIG, RISKY_TASK, SAFE_TASK


AGENT = AgentProfile(
    name="claude-opus",
    provider="anthropic",
    model_id="claude-opus-4-8",
    input_cost_per_mtok=5.0,
    output_cost_per_mtok=25.0,
)


def _request(task_text: str) -> BidRequest:
    return BidRequest(task_text=task_text, intent=score_task_intent(task_text))


class MockProviderTests(unittest.TestCase):
    def test_same_inputs_produce_identical_bids(self):
        provider = MockBidProvider(seed=7)
        first = provider.request_bid(AGENT, _request(RISKY_TASK))
        second = MockBidProvider(seed=7).request_bid(AGENT, _request(RISKY_TASK))
        self.assertEqual(first, second)

    def test_different_seeds_change_the_bid(self):
        a = MockBidProvider(seed=1).request_bid(AGENT, _request(RISKY_TASK))
        b = MockBidProvider(seed=2).request_bid(AGENT, _request(RISKY_TASK))
        self.assertNotEqual(a, b)

    def test_effort_tracks_intent_band(self):
        risky = MockBidProvider().request_bid(AGENT, _request(RISKY_TASK))
        self.assertEqual(risky.declared_effort, "substantial")
        safe = MockBidProvider().request_bid(AGENT, _request(SAFE_TASK))
        self.assertEqual(safe.declared_effort, "trivial")

    def test_confidence_override_and_failures(self):
        provider = MockBidProvider(
            confidence_overrides={"claude-opus": 0.91}, fail_agents={"gpt"}
        )
        bid = provider.request_bid(AGENT, _request(SAFE_TASK))
        self.assertEqual(bid.confidence, 0.91)
        gpt = AgentProfile(
            name="gpt", provider="openai", model_id="gpt-5.2",
            input_cost_per_mtok=1.25, output_cost_per_mtok=10.0,
        )
        with self.assertRaises(BidProviderError):
            provider.request_bid(gpt, _request(SAFE_TASK))


class LiveProviderConstructionTests(unittest.TestCase):
    """No-network checks of the live providers' configuration handling."""

    def test_anthropic_requires_api_key(self):
        with self.assertRaises(MissingApiKeyError):
            AnthropicBidProvider.from_env(env={})

    def test_openai_requires_api_key(self):
        with self.assertRaises(MissingApiKeyError):
            OpenAIBidProvider.from_env(env={})

    def test_from_env_reads_keys_and_base_url(self):
        provider = AnthropicBidProvider.from_env(
            env={"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "http://localhost:1"}
        )
        self.assertEqual(provider.base_url, "http://localhost:1")
        openai_provider = OpenAIBidProvider.from_env(env={"OPENAI_API_KEY": "k"})
        self.assertIsNone(openai_provider.base_url)


class BuildProvidersTests(unittest.TestCase):
    def test_dry_run_uses_mocks_everywhere(self):
        providers = build_providers(CONFIG, dry_run=True, env={})
        self.assertEqual(set(providers), {"anthropic", "openai"})
        for provider in providers.values():
            self.assertIsInstance(provider, MockBidProvider)

    def test_live_build_without_keys_raises(self):
        with self.assertRaises(MissingApiKeyError):
            build_providers(CONFIG, env={})


if __name__ == "__main__":
    unittest.main()
