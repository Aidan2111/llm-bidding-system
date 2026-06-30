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

from typing import Protocol

from .calibration import clamp_unit
from .models import AgentProfile, AgentStats, Bid, ScoredBid


class _WeightsLike(Protocol):
    quality: float
    price: float
    risk_fit: float


class _CalibrationLike(Protocol):
    min_band_samples: int


class UtilityConfigLike(Protocol):
    quality_mix_confidence: float
    quality_mix_history: float
    cost_ceiling_usd: float
    weights: _WeightsLike
    calibration: _CalibrationLike


def estimate_cost_usd(bid: Bid, agent: AgentProfile) -> float:
    input_cost = bid.estimated_input_tokens / 1_000_000 * agent.input_cost_per_mtok
    output_cost = bid.estimated_output_tokens / 1_000_000 * agent.output_cost_per_mtok
    return input_cost + output_cost


def compute_scored_bid(
    bid: Bid,
    agent: AgentProfile,
    stats: AgentStats,
    band_stats: AgentStats,
    config: UtilityConfigLike,
) -> ScoredBid:
    calibrated = clamp_unit(bid.confidence + stats.calibration_offset)

    quality = (
        config.quality_mix_confidence * calibrated
        + config.quality_mix_history * stats.success_rate
    )

    # cost_ratio corrects for the agent's historical estimate bias
    # (actual / raw estimate over reported outcomes); neutral 1.0 cold start.
    raw_cost = estimate_cost_usd(bid, agent)
    cost = raw_cost * stats.cost_ratio
    price = 1.0 - min(cost / config.cost_ceiling_usd, 1.0)

    if band_stats.outcomes_reported >= config.calibration.min_band_samples:
        risk_fit = band_stats.success_rate
    else:
        risk_fit = stats.success_rate

    # Per-band weight overrides when the config supports them; the band comes
    # from the band-scoped stats. Falls back to the global weights otherwise.
    weights_for = getattr(config, "weights_for", None)
    weights = weights_for(band_stats.band) if weights_for else config.weights
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
        raw_estimated_cost_usd=raw_cost,
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
