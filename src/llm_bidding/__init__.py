"""LLM work auction: agents bid on tasks scored by agent-autonomy-score."""

from .auction import run_auction
from .config import BiddingConfig, ConfigError, load_config
from .history import HistoryError, HistoryStore
from .policy import PolicyParams
from .scoring import ScoringCompatibilityError
from .models import (
    AgentProfile,
    AgentStats,
    AuctionResult,
    Bid,
    BidRequest,
    BidValidationError,
    OutcomeReport,
    ScoredBid,
)

__all__ = [
    "AgentProfile",
    "AgentStats",
    "AuctionResult",
    "Bid",
    "BidRequest",
    "BidValidationError",
    "BiddingConfig",
    "ConfigError",
    "HistoryError",
    "HistoryStore",
    "OutcomeReport",
    "PolicyParams",
    "ScoredBid",
    "ScoringCompatibilityError",
    "load_config",
    "run_auction",
]
__version__ = "0.2.0"
