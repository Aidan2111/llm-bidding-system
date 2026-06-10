"""LLM work auction: agents bid on tasks scored by agent-autonomy-score."""

from .auction import run_auction
from .config import BiddingConfig, ConfigError, load_config
from .history import HistoryError, HistoryStore
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
    "ScoredBid",
    "load_config",
    "run_auction",
]
__version__ = "0.1.0"
