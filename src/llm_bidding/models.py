"""Core domain models for the LLM bidding system."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Mapping

from autonomy_score import IntentScoreResult


EFFORT_LEVELS = ("trivial", "moderate", "substantial")
PROVIDER_TYPES = ("anthropic", "openai", "mock")


class BidValidationError(ValueError):
    """Raised when a provider returns a malformed bid payload."""


@dataclass(frozen=True)
class AgentProfile:
    name: str
    provider: str
    model_id: str
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AgentProfile":
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Agent 'name' must be a non-empty string.")
        provider = data.get("provider")
        if provider not in PROVIDER_TYPES:
            raise ValueError(
                f"Agent {name!r} has provider {provider!r}; expected one of: "
                + ", ".join(PROVIDER_TYPES)
            )
        model_id = data.get("model_id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError(f"Agent {name!r} needs a non-empty 'model_id'.")
        input_cost = data.get("input_cost_per_mtok")
        output_cost = data.get("output_cost_per_mtok")
        for label, value in (
            ("input_cost_per_mtok", input_cost),
            ("output_cost_per_mtok", output_cost),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Agent {name!r} field {label!r} must be a number >= 0.")
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"Agent {name!r} field 'enabled' must be a boolean.")
        return cls(
            name=name,
            provider=provider,
            model_id=model_id,
            input_cost_per_mtok=float(input_cost),
            output_cost_per_mtok=float(output_cost),
            enabled=enabled,
        )


@dataclass(frozen=True)
class BidRequest:
    """What an agent is asked to bid on: the task plus its deterministic risk score."""

    task_text: str
    intent: IntentScoreResult


@dataclass(frozen=True)
class Bid:
    """A raw self-assessment returned by an LLM provider."""

    agent_name: str
    model_id: str
    confidence: float
    approach: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    declared_effort: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_payload(
        cls, data: Mapping[str, object], *, agent_name: str, model_id: str
    ) -> "Bid":
        confidence = data.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise BidValidationError("Bid field 'confidence' must be a number.")
        if not 0.0 <= float(confidence) <= 1.0:
            raise BidValidationError("Bid field 'confidence' must be between 0 and 1.")
        approach = data.get("approach")
        if not isinstance(approach, str) or not approach.strip():
            raise BidValidationError("Bid field 'approach' must be a non-empty string.")
        tokens: dict[str, int] = {}
        for key in ("estimated_input_tokens", "estimated_output_tokens"):
            value = data.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise BidValidationError(f"Bid field {key!r} must be an integer >= 1.")
            tokens[key] = value
        effort = data.get("declared_effort")
        if effort not in EFFORT_LEVELS:
            raise BidValidationError(
                "Bid field 'declared_effort' must be one of: " + ", ".join(EFFORT_LEVELS)
            )
        return cls(
            agent_name=agent_name,
            model_id=model_id,
            confidence=float(confidence),
            approach=approach.strip(),
            estimated_input_tokens=tokens["estimated_input_tokens"],
            estimated_output_tokens=tokens["estimated_output_tokens"],
            declared_effort=effort,
        )


@dataclass(frozen=True)
class AgentStats:
    """Historical performance snapshot for one agent (optionally band-scoped)."""

    agent_name: str
    band: str | None
    auctions_entered: int
    wins: int
    outcomes_reported: int
    successes: int
    win_rate: float
    success_rate: float
    brier_score: float | None
    calibration_offset: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScoredBid:
    """A bid after utility scoring, or a recorded provider failure."""

    agent_name: str
    bid: Bid | None
    stats: AgentStats | None
    estimated_cost_usd: float
    calibrated_confidence: float
    quality_score: float
    price_score: float
    risk_fit_score: float
    utility: float
    error: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.bid is not None and self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_name": self.agent_name,
            "bid": self.bid.to_dict() if self.bid else None,
            "stats": self.stats.to_dict() if self.stats else None,
            "estimated_cost_usd": self.estimated_cost_usd,
            "calibrated_confidence": self.calibrated_confidence,
            "quality_score": self.quality_score,
            "price_score": self.price_score,
            "risk_fit_score": self.risk_fit_score,
            "utility": self.utility,
            "error": self.error,
        }


@dataclass(frozen=True)
class AuctionResult:
    auction_id: str
    created_at: str
    task_text: str
    intent: IntentScoreResult
    weights: dict[str, float]
    bids: tuple[ScoredBid, ...]
    winner: ScoredBid | None
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "auction_id": self.auction_id,
            "created_at": self.created_at,
            "task_text": self.task_text,
            "intent": self.intent.to_dict(),
            "weights": dict(self.weights),
            "bids": [bid.to_dict() for bid in self.bids],
            "winner": self.winner.to_dict() if self.winner else None,
            "summary": self.summary,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


@dataclass(frozen=True)
class OutcomeReport:
    auction_id: str
    success: bool
    reported_at: str
    notes: str = ""
    diff_score: int | None = None
    actual_cost_usd: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
