"""Bid provider backed by the Anthropic Messages API."""

from __future__ import annotations

import os
from typing import Mapping

from ..models import AgentProfile, Bid, BidRequest, BidValidationError
from .base import (
    BID_SCHEMA,
    SYSTEM_PROMPT,
    BidProviderError,
    MissingApiKeyError,
    MissingDependencyError,
    build_user_payload,
    classify_provider_exception,
)


_BID_TOOL = {
    "name": "submit_bid",
    "description": "Submit your bid for the task.",
    "input_schema": BID_SCHEMA,
}


class AnthropicBidProvider:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        if not api_key:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is required to request bids from Anthropic models. "
                "Set it in your environment or run with --dry-run."
            )
        self.api_key = api_key
        self.base_url = base_url

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AnthropicBidProvider":
        active_env = env if env is not None else os.environ
        return cls(
            api_key=active_env.get("ANTHROPIC_API_KEY", ""),
            base_url=active_env.get("ANTHROPIC_BASE_URL") or None,
        )

    def request_bid(self, agent: AgentProfile, request: BidRequest) -> Bid:
        Anthropic = _import_anthropic()
        kwargs: dict[str, object] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = Anthropic(**kwargs)
        try:
            response = client.messages.create(
                model=agent.model_id,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_payload(request)}],
                tools=[_BID_TOOL],
                tool_choice={"type": "tool", "name": "submit_bid"},
            )
        except Exception as exc:
            raise classify_provider_exception(exc, "Anthropic") from exc
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_bid":
                try:
                    return Bid.from_payload(
                        block.input, agent_name=agent.name, model_id=agent.model_id
                    )
                except BidValidationError as exc:
                    raise BidProviderError(str(exc)) from exc
        raise BidProviderError("Anthropic response did not include a submit_bid tool call.")


def _import_anthropic():
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise MissingDependencyError(
            'The Anthropic SDK is required for anthropic agents. '
            'Install it with: pip install -e ".[anthropic]"'
        ) from exc
    return Anthropic
