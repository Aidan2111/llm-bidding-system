"""Bid provider backed by an OpenAI-compatible Responses API."""

from __future__ import annotations

import json
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


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenAIBidProvider:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        if not api_key:
            raise MissingApiKeyError(
                "OPENAI_API_KEY is required to request bids from OpenAI models. "
                "Set it in your environment or run with --dry-run."
            )
        self.api_key = api_key
        self.base_url = base_url

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OpenAIBidProvider":
        kwargs = openai_client_kwargs_from_env(env)
        base_url = kwargs.get("base_url")
        return cls(
            api_key=str(kwargs["api_key"]),
            base_url=base_url if isinstance(base_url, str) else None,
        )

    def request_bid(self, agent: AgentProfile, request: BidRequest) -> Bid:
        OpenAI = _import_openai()
        kwargs: dict[str, object] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = OpenAI(**kwargs)
        try:
            response = client.responses.create(
                model=agent.model_id,
                input=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_payload(request)},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "llm_bid",
                        "schema": BID_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except AttributeError as exc:
            raise BidProviderError(
                'The installed OpenAI SDK does not expose the Responses API. '
                'Upgrade with: pip install -U "openai>=1.68.0"'
            ) from exc
        except Exception as exc:
            raise classify_provider_exception(exc, "OpenAI-compatible") from exc
        raw_text = getattr(response, "output_text", None)
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise BidProviderError("OpenAI response did not include output_text.")
        try:
            decoded = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise BidProviderError("OpenAI bid response was not valid JSON.") from exc
        try:
            return Bid.from_payload(decoded, agent_name=agent.name, model_id=agent.model_id)
        except BidValidationError as exc:
            raise BidProviderError(str(exc)) from exc


def _import_openai():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise MissingDependencyError(
            'The OpenAI SDK is required for openai agents. '
            'Install it with: pip install -e ".[openai]"'
        ) from exc
    return OpenAI


def openai_client_kwargs_from_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    active_env = env if env is not None else os.environ
    api_key = active_env.get("OPENAI_API_KEY") or active_env.get("OPENROUTER_API_KEY", "")
    base_url = active_env.get("OPENAI_BASE_URL") or None
    if not base_url and active_env.get("OPENROUTER_API_KEY"):
        base_url = OPENROUTER_BASE_URL
    if not api_key:
        raise MissingApiKeyError(
            "OPENAI_API_KEY or OPENROUTER_API_KEY is required to call "
            "OpenAI-compatible models. Set one in your environment or run with --dry-run."
        )
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return kwargs
