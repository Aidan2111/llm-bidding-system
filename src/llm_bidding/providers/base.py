"""Shared bid-provider protocol, prompt, and schema."""

from __future__ import annotations

import json
from typing import Protocol

from ..models import AgentProfile, Bid, BidRequest


MAX_TASK_CHARS = 60000


class BidProviderError(RuntimeError):
    """Base error for bid-provider failures."""


class MissingApiKeyError(BidProviderError):
    """Raised when a provider is used without its API key configured."""


class MissingDependencyError(BidProviderError):
    """Raised when an optional provider SDK is not installed."""


class BidProvider(Protocol):
    def request_bid(self, agent: AgentProfile, request: BidRequest) -> Bid:
        """Ask the model behind ``agent`` for a structured self-assessment."""


# Note: strict structured-output schemas do not support numeric minimum/maximum
# constraints, so range checks live in Bid.from_payload instead.
BID_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "confidence": {
            "type": "number",
            "description": (
                "Probability between 0 and 1 that you would complete this task"
                " successfully on the first attempt."
            ),
        },
        "approach": {
            "type": "string",
            "description": "Two or three sentences describing how you would do the work.",
        },
        "estimated_input_tokens": {
            "type": "integer",
            "description": "Estimated input tokens needed to perform the task (minimum 1).",
        },
        "estimated_output_tokens": {
            "type": "integer",
            "description": "Estimated output tokens needed to perform the task (minimum 1).",
        },
        "declared_effort": {
            "type": "string",
            "enum": ["trivial", "moderate", "substantial"],
            "description": "Overall effort class for the task.",
        },
    },
    "required": [
        "confidence",
        "approach",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "declared_effort",
    ],
}


SYSTEM_PROMPT = """You are one of several LLM agents bidding for a piece of software work.

You will receive:
- the task description
- a deterministic risk assessment of the task (score, band, and named signals)

Return an honest self-assessment of how well YOU would perform this task.
Overconfident bids are penalized later: reported outcomes are compared against
your stated confidence, and a poor calibration record lowers your future bids.
Be realistic about scope, risk, and the effort involved.
"""


def build_user_payload(request: BidRequest) -> str:
    truncated = len(request.task_text) > MAX_TASK_CHARS
    visible = request.task_text[:MAX_TASK_CHARS]
    payload = {
        "task": visible,
        "task_truncated": truncated,
        "deterministic_intent_assessment": request.intent.to_dict(),
    }
    return json.dumps(payload, indent=2, sort_keys=True)
