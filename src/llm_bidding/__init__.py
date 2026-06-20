"""LLM work auction: agents bid on tasks scored by agent-autonomy-score."""

from .application.auctioning import run_auction
from .domain.models import (
    AgentProfile,
    AgentStats,
    AuctionResult,
    Bid,
    BidRequest,
    BidValidationError,
    OutcomeReport,
    ScoredBid,
)
from .domain.policy import PolicyParams
from .infrastructure.autonomy_scoring import ScoringCompatibilityError
from .infrastructure.configuration import BiddingConfig, ConfigError, load_config
from .infrastructure.history_store import HistoryError, HistoryStore

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
