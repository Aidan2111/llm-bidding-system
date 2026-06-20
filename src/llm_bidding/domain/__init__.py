"""Domain entities and pure scoring policy for LLM bidding."""

from .calibration import (
    brier_score,
    calibration_offset,
    clamp_unit,
    shrunk_cost_ratio,
    shrunk_success_rate,
)
from .models import (
    AgentProfile,
    AgentStats,
    AuctionResult,
    Bid,
    BidRequest,
    BidValidationError,
    IntentAssessment,
    OutcomeReport,
    ScoredBid,
)
from .policy import PolicyParams, apply_eligibility, select_winner
from .utility import compute_scored_bid, estimate_cost_usd, failed_bid

__all__ = [
    "AgentProfile",
    "AgentStats",
    "AuctionResult",
    "Bid",
    "BidRequest",
    "BidValidationError",
    "IntentAssessment",
    "OutcomeReport",
    "PolicyParams",
    "ScoredBid",
    "apply_eligibility",
    "brier_score",
    "calibration_offset",
    "clamp_unit",
    "compute_scored_bid",
    "estimate_cost_usd",
    "failed_bid",
    "select_winner",
    "shrunk_cost_ratio",
    "shrunk_success_rate",
]
