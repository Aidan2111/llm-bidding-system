"""Bid providers: live Anthropic/OpenAI backends and a deterministic mock."""

from __future__ import annotations

from typing import Mapping

from ..config import BiddingConfig
from .base import (
    BID_SCHEMA,
    SYSTEM_PROMPT,
    BidProvider,
    BidProviderError,
    MissingApiKeyError,
    MissingDependencyError,
    build_user_payload,
)
from .mock import MockBidProvider

__all__ = [
    "BID_SCHEMA",
    "SYSTEM_PROMPT",
    "BidProvider",
    "BidProviderError",
    "MissingApiKeyError",
    "MissingDependencyError",
    "MockBidProvider",
    "build_user_payload",
    "build_providers",
]


def build_providers(
    config: BiddingConfig,
    *,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, BidProvider]:
    """Build one provider per provider type used by the enabled agents.

    With ``dry_run`` every provider type is served by the deterministic mock,
    so no API keys or network access are needed.
    """
    needed = {profile.provider for profile in config.agents if profile.enabled}
    providers: dict[str, BidProvider] = {}
    for provider_type in sorted(needed):
        if dry_run or provider_type == "mock":
            providers[provider_type] = MockBidProvider()
        elif provider_type == "anthropic":
            from .anthropic_provider import AnthropicBidProvider

            providers[provider_type] = AnthropicBidProvider.from_env(env)
        elif provider_type == "openai":
            from .openai_provider import OpenAIBidProvider

            providers[provider_type] = OpenAIBidProvider.from_env(env)
        else:  # pragma: no cover - config validation rejects unknown providers
            raise BidProviderError(f"Unknown provider type {provider_type!r}.")
    return providers
