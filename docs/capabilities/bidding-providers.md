---
name: Bidding Providers
summary: Pluggable backends that turn a task into a structured bid; live Anthropic/OpenAI plus a deterministic mock.
module: src/llm_bidding/providers
entrypoints: BidProvider, build_providers, MockBidProvider, RetryableProviderError
read_when: adding a model provider, changing the bid schema/prompt, or tuning transient-error classification
---

# Bidding Providers

A provider implements one method: `request_bid(agent, request) -> Bid`.

## Layout

- **`base.py`** — the `BidProvider` protocol, the shared `BID_SCHEMA` and
  `SYSTEM_PROMPT`, error classes (`BidProviderError`, `MissingApiKeyError`,
  `MissingDependencyError`, `RetryableProviderError`), and
  `classify_provider_exception` (maps SDK 429/5xx/connection errors to the
  retryable class; auth/dependency/validation stay permanent).
- **`anthropic_provider.py`** — Messages API with a forced `tool_choice` for
  structured output. Lazy SDK import behind the `[anthropic]` extra.
- **`openai_provider.py`** — Responses API with a strict `json_schema`. Lazy
  import behind the `[openai]` extra.
- **`mock.py`** — `MockBidProvider`: sha256-deterministic bids, no network.
  Supports `confidence_overrides`, `fail_agents`, `transient_failures`, and a
  `calls` log for tests and `--dry-run`.

## Adding a provider

1. Implement `request_bid`, funnelling the model's JSON through
   `Bid.from_payload` so validation is shared.
2. Map transient SDK errors via `classify_provider_exception`.
3. Register it in `build_providers` keyed on `AgentProfile.provider`.
4. Keep the SDK an optional extra with a lazy import.
