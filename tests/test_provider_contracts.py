"""Contract tests for the live providers' request/response mapping.

These never hit the network and don't need the real SDKs installed: they patch
each provider's lazy SDK importer with a fake client, then assert the
JSON -> Bid mapping, the missing/invalid-response handling, and the
transient-vs-permanent error classification. This closes the gap where a
provider's mapping logic was otherwise only exercised by the mock provider.
"""

import json
import unittest
from unittest import mock

from llm_bidding.models import AgentProfile, BidRequest
from llm_bidding.providers import RetryableProviderError
from llm_bidding.providers.base import BidProviderError
from llm_bidding.providers import anthropic_provider, openai_provider
from llm_bidding.scoring import score_task_intent

VALID_PAYLOAD = {
    "confidence": 0.7,
    "approach": "Implement behind a flag and add tests.",
    "estimated_input_tokens": 1200,
    "estimated_output_tokens": 600,
    "declared_effort": "moderate",
}

ANTHROPIC_AGENT = AgentProfile(
    name="claude", provider="anthropic", model_id="claude-opus-4-8",
    input_cost_per_mtok=5.0, output_cost_per_mtok=25.0,
)
OPENAI_AGENT = AgentProfile(
    name="gpt", provider="openai", model_id="gpt-5.2",
    input_cost_per_mtok=1.25, output_cost_per_mtok=10.0,
)


def _request() -> BidRequest:
    text = "Update the profile button label copy."
    return BidRequest(task_text=text, intent=score_task_intent(text))


class _RateLimit(Exception):
    status_code = 429


class _BadRequest(Exception):
    status_code = 400


# ---- Anthropic fakes -------------------------------------------------------

class _AnthropicBlock:
    def __init__(self, **kw):
        self.type = kw.get("type")
        self.name = kw.get("name")
        self.input = kw.get("input")


def _fake_anthropic(*, blocks=None, raises=None):
    class _Messages:
        def create(self, **_kw):
            if raises is not None:
                raise raises
            resp = mock.Mock()
            resp.content = blocks or []
            return resp

    class _Client:
        def __init__(self, **_kw):
            self.messages = _Messages()

    return _Client


class AnthropicContractTests(unittest.TestCase):
    def _run(self, *, blocks=None, raises=None):
        provider = anthropic_provider.AnthropicBidProvider(api_key="k")
        with mock.patch.object(
            anthropic_provider, "_import_anthropic",
            return_value=_fake_anthropic(blocks=blocks, raises=raises),
        ):
            return provider.request_bid(ANTHROPIC_AGENT, _request())

    def test_tool_use_block_maps_to_bid(self):
        block = _AnthropicBlock(type="tool_use", name="submit_bid", input=VALID_PAYLOAD)
        bid = self._run(blocks=[block])
        self.assertEqual(bid.agent_name, "claude")
        self.assertEqual(bid.model_id, "claude-opus-4-8")
        self.assertEqual(bid.confidence, 0.7)
        self.assertEqual(bid.declared_effort, "moderate")

    def test_missing_tool_use_raises(self):
        text_block = _AnthropicBlock(type="text")
        with self.assertRaises(BidProviderError) as ctx:
            self._run(blocks=[text_block])
        self.assertIn("submit_bid", str(ctx.exception))

    def test_invalid_payload_raises_provider_error(self):
        bad = {**VALID_PAYLOAD, "confidence": 5}  # out of range
        block = _AnthropicBlock(type="tool_use", name="submit_bid", input=bad)
        with self.assertRaises(BidProviderError):
            self._run(blocks=[block])

    def test_rate_limit_is_retryable(self):
        with self.assertRaises(RetryableProviderError):
            self._run(raises=_RateLimit())

    def test_bad_request_is_permanent(self):
        with self.assertRaises(BidProviderError) as ctx:
            self._run(raises=_BadRequest())
        self.assertNotIsInstance(ctx.exception, RetryableProviderError)


# ---- OpenAI fakes ----------------------------------------------------------

def _fake_openai(*, output_text=None, raises=None):
    class _Responses:
        def create(self, **_kw):
            if raises is not None:
                raise raises
            resp = mock.Mock()
            resp.output_text = output_text
            return resp

    class _Client:
        def __init__(self, **_kw):
            self.responses = _Responses()

    return _Client


class OpenAIContractTests(unittest.TestCase):
    def _run(self, *, output_text=None, raises=None):
        provider = openai_provider.OpenAIBidProvider(api_key="k")
        with mock.patch.object(
            openai_provider, "_import_openai",
            return_value=_fake_openai(output_text=output_text, raises=raises),
        ):
            return provider.request_bid(OPENAI_AGENT, _request())

    def test_json_output_maps_to_bid(self):
        bid = self._run(output_text=json.dumps(VALID_PAYLOAD))
        self.assertEqual(bid.agent_name, "gpt")
        self.assertEqual(bid.model_id, "gpt-5.2")
        self.assertEqual(bid.estimated_input_tokens, 1200)

    def test_empty_output_raises(self):
        with self.assertRaises(BidProviderError) as ctx:
            self._run(output_text="")
        self.assertIn("output_text", str(ctx.exception))

    def test_non_json_output_raises(self):
        with self.assertRaises(BidProviderError) as ctx:
            self._run(output_text="not json")
        self.assertIn("valid JSON", str(ctx.exception))

    def test_invalid_payload_raises_provider_error(self):
        bad = {**VALID_PAYLOAD, "declared_effort": "heroic"}
        with self.assertRaises(BidProviderError):
            self._run(output_text=json.dumps(bad))

    def test_server_error_is_retryable(self):
        class _ServerError(Exception):
            status_code = 503

        with self.assertRaises(RetryableProviderError):
            self._run(raises=_ServerError())


if __name__ == "__main__":
    unittest.main()
