"""Shared fixtures for the test suite."""

from __future__ import annotations

from llm_bidding.config import load_config
from llm_bidding.scoring import score_task_intent
from llm_bidding.models import AuctionResult, Bid, ScoredBid

CONFIG = load_config()

RISKY_TASK = (
    "Refactor the global auth token persistence architecture: migrate to a new"
    " database schema with a destructive migration and concurrency-safe rollback."
)
SAFE_TASK = "Update the profile screen button label copy in ProfileView."


def make_scored_bid(
    agent_name: str,
    *,
    confidence: float = 0.8,
    utility: float = 0.5,
    cost: float = 0.01,
    error: str | None = None,
) -> ScoredBid:
    bid = None
    if error is None:
        bid = Bid(
            agent_name=agent_name,
            model_id="test-model",
            confidence=confidence,
            approach="Test approach.",
            estimated_input_tokens=1000,
            estimated_output_tokens=1000,
            declared_effort="moderate",
        )
    return ScoredBid(
        agent_name=agent_name,
        bid=bid,
        stats=None,
        estimated_cost_usd=cost if error is None else 0.0,
        calibrated_confidence=confidence if error is None else 0.0,
        quality_score=0.5,
        price_score=0.5,
        risk_fit_score=0.5,
        utility=utility if error is None else 0.0,
        error=error,
    )


def make_auction(
    auction_id: str,
    *,
    task_text: str = RISKY_TASK,
    bids: tuple[ScoredBid, ...],
    winner: ScoredBid | None,
    created_at: str = "2026-06-10T00:00:00+00:00",
) -> AuctionResult:
    return AuctionResult(
        auction_id=auction_id,
        created_at=created_at,
        task_text=task_text,
        intent=score_task_intent(task_text),
        weights=CONFIG.weights.to_dict(),
        bids=bids,
        winner=winner,
        summary="test",
    )
