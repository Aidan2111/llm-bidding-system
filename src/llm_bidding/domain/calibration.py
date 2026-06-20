"""Deterministic calibration math for agent history.

All adjustments are simple, inspectable formulas in the spirit of
agent-autonomy-score: no learned weights, no opaque state.
"""

from __future__ import annotations

from typing import Protocol, Sequence


class CalibrationParamsLike(Protocol):
    neutral_prior: float
    prior_strength: float
    max_calibration_shift: float
    min_calibration_samples: int
    cost_ratio_prior_strength: float
    cost_ratio_min: float
    cost_ratio_max: float


def shrunk_success_rate(
    successes: int, outcomes: int, params: CalibrationParamsLike
) -> float:
    """Success rate shrunk toward a neutral prior (Laplace-style).

    With zero reported outcomes this returns exactly the neutral prior, so
    new agents start neutral rather than punished.
    """
    numerator = successes + params.prior_strength * params.neutral_prior
    denominator = outcomes + params.prior_strength
    return numerator / denominator


def calibration_offset(
    confidence_outcome_pairs: Sequence[tuple[float, bool]],
    params: CalibrationParamsLike,
) -> float:
    """Mean (outcome - stated confidence), clamped.

    Positive when an agent is underconfident, negative when overconfident.
    Applies only once enough outcomes exist to be meaningful.
    """
    if len(confidence_outcome_pairs) < max(params.min_calibration_samples, 1):
        return 0.0
    total = sum(
        (1.0 if outcome else 0.0) - confidence
        for confidence, outcome in confidence_outcome_pairs
    )
    offset = total / len(confidence_outcome_pairs)
    limit = params.max_calibration_shift
    return max(-limit, min(limit, offset))


def shrunk_cost_ratio(
    ratios: Sequence[float], params: CalibrationParamsLike
) -> float:
    """Mean actual/estimated cost ratio shrunk toward a neutral 1.0, clamped.

    Cold start (no reported actual costs) returns exactly 1.0, leaving cost
    estimates untouched.
    """
    value = (sum(ratios) + params.cost_ratio_prior_strength * 1.0) / (
        len(ratios) + params.cost_ratio_prior_strength
    )
    return min(max(value, params.cost_ratio_min), params.cost_ratio_max)


def brier_score(
    confidence_outcome_pairs: Sequence[tuple[float, bool]],
) -> float | None:
    """Mean squared error between stated confidence and the binary outcome."""
    if not confidence_outcome_pairs:
        return None
    total = sum(
        (confidence - (1.0 if outcome else 0.0)) ** 2
        for confidence, outcome in confidence_outcome_pairs
    )
    return total / len(confidence_outcome_pairs)


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))
