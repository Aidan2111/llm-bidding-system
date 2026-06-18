import json
import tempfile
import unittest
from pathlib import Path

from llm_bidding.scoring import score_task_intent

from llm_bidding.models import AgentProfile, BidRequest
from llm_bidding.providers import (
    BidProviderError,
    MissingApiKeyError,
    MockBidProvider,
    build_providers,
)
from llm_bidding.providers.anthropic_provider import AnthropicBidProvider
from llm_bidding.providers.ollama_provider import (
    OLLAMA_DEFAULT_BASE_URL,
    OllamaBidProvider,
)
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

    def test_openrouter_key_defaults_to_openrouter_base_url(self):
        provider = OpenAIBidProvider.from_env(env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual(provider.api_key, "k")
        self.assertEqual(provider.base_url, "https://openrouter.ai/api/v1")

    def test_ollama_provider_defaults_to_localhost_without_key(self):
        provider = OllamaBidProvider.from_env(
            env={"VSCODE_CHAT_MODELS_PATH": "/tmp/missing-chat-models.json"}
        )
        self.assertEqual(provider.base_url, OLLAMA_DEFAULT_BASE_URL)

    def test_ollama_provider_reads_base_url(self):
        provider = OllamaBidProvider.from_env(
            env={"OLLAMA_BASE_URL": "http://spark.local:11434/"}
        )
        self.assertEqual(provider.base_url, "http://spark.local:11434")

    def test_ollama_provider_reads_vscode_model_registry_when_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chatLanguageModels.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "DGX Spark",
                            "vendor": "ollama",
                            "url": "http://192.168.0.220:11434",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            provider = OllamaBidProvider.from_env(
                env={"VSCODE_CHAT_MODELS_PATH": str(path)}
            )

        self.assertEqual(provider.base_url, "http://192.168.0.220:11434")


class BuildProvidersTests(unittest.TestCase):
    def test_dry_run_uses_mocks_everywhere(self):
        providers = build_providers(CONFIG, dry_run=True, env={})
        self.assertEqual(set(providers), {"anthropic", "openai"})
        for provider in providers.values():
            self.assertIsInstance(provider, MockBidProvider)

    def test_live_build_without_keys_raises(self):
        with self.assertRaises(MissingApiKeyError):
            build_providers(CONFIG, env={})

    def test_live_build_supports_ollama_without_key(self):
        config = type(
            "Config",
            (),
            {
                "agents": (
                    AgentProfile(
                        name="spark",
                        provider="ollama",
                        model_id="spark",
                        input_cost_per_mtok=0.0,
                        output_cost_per_mtok=0.0,
                    ),
                )
            },
        )()
        providers = build_providers(config, env={})
        self.assertIsInstance(providers["ollama"], OllamaBidProvider)


class OllamaProviderTests(unittest.TestCase):
    def test_request_bid_posts_structured_chat_and_parses_response(self):
        seen = {}

        def fake_post_json(url, payload, timeout):
            seen["url"] = url
            seen["payload"] = payload
            seen["timeout"] = timeout
            return {
                "message": {
                    "content": (
                        '{"confidence":0.7,"approach":"Use local reasoning.",'
                        '"estimated_input_tokens":123,'
                        '"estimated_output_tokens":456,'
                        '"declared_effort":"trivial"}'
                    )
                }
            }

        agent = AgentProfile(
            name="spark",
            provider="ollama",
            model_id="spark",
            input_cost_per_mtok=0.0,
            output_cost_per_mtok=0.0,
        )
        provider = OllamaBidProvider(
            base_url="http://localhost:11434",
            post_json=fake_post_json,
        )

        bid = provider.request_bid(agent, _request(SAFE_TASK))

        self.assertEqual(bid.agent_name, "spark")
        self.assertEqual(bid.confidence, 0.7)
        self.assertEqual(seen["url"], "http://localhost:11434/api/chat")
        self.assertEqual(seen["payload"]["model"], "spark")
        self.assertFalse(seen["payload"]["stream"])
        self.assertIn("format", seen["payload"])


if __name__ == "__main__":
    unittest.main()
