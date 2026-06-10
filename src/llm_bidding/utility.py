"""Pure utility scoring: turns a raw bid plus history into a ScoredBid.

The formula (all components normalized to 0..1):

    quality  = mix_confidence * calibrated_confidence + mix_history * success_rate
    price    = 1 - min(estimated_cost_usd / cost_ceiling_usd, 1)
    risk_fit = band-scoped success rate when enough samples exist in the
               task's risk band, otherwise the agent's overall success rate
    utility  = w_quality * quality + w_price * price + w_risk_fit * risk_fit

Success rates are pre-shrunk toward a neutral prior (see calibration.py), so
agents with no history score exactly neutral rather than zero.
"""

from __future__ import annotations

from .calibration import clamp_unit
from .config import BiddingConfig
from .models import AgentProfile, AgentStats, Bid, ScoredBid


def estimate_cost_usd(bid: Bid, agent: AgentProfile) -> float:
    input_cost = bid.estimated_input_tokens / 1_000_000 * agent.input_cost_per_mtok
    output_cost = bid.estimated_output_tokens / 1_000_000 * agent.output_cost_per_mtok
    return input_cost + output_cost


def compute_scored_bid(
    bid: Bid,
    agent: AgentProfile,
    stats: AgentStats,
    band_stats: AgentStats,
    config: BiddingConfig,
) -> ScoredBid:
    calibrated = clamp_unit(bid.confidence + stats.calibration_offset)

    quality = (
        config.quality_mix_confidence * calibrated
        + config.quality_mix_history * stats.success_rate
    )

    cost = estimate_cost_usd(bid, agent)
    price = 1.0 - min(cost / config.cost_ceiling_usd, 1.0)

    if band_stats.outcomes_reported >= config.calibration.min_band_samples:
        risk_fit = band_stats.success_rate
    else:
        risk_fit = stats.success_rate

    weights = config.weights
    utility = (
        weights.quality * quality + weights.price * price + weights.risk_fit * risk_fit
    )

    return ScoredBid(
        agent_name=agent.name,
        bid=bid,
        stats=stats,
        estimated_cost_usd=cost,
        calibrated_confidence=calibrated,
        quality_score=quality,
        price_score=price,
        risk_fit_score=risk_fit,
        utility=utility,
    )


def failed_bid(agent_name: str, error: str, stats: AgentStats | None = None) -> ScoredBid:
    return ScoredBid(
        agent_name=agent_name,
        bid=None,
        stats=stats,
        estimated_cost_usd=0.0,
        calibrated_confidence=0.0,
        quality_score=0.0,
        price_score=0.0,
        risk_fit_score=0.0,
        utility=0.0,
        error=error,
    )
