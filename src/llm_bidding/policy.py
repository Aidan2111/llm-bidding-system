"""Award policy: eligibility floors, abstain rules, and selection modes.

Applied after utility scoring and before winner selection. All defaults are
no-ops, reproducing plain argmax-utility selection.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Sequence

from .models import ScoredBid

SELECTION_MODES = ("utility", "cheapest_adequate")

NO_VALID_BIDS_REASON = "No valid bids were received"


@dataclass(frozen=True)
class PolicyParams:
    min_award_utility: float = 0.0
    selection_mode: str = "utility"
    adequacy_min_quality: float = 0.0
    # None disables a floor criterion. With OR semantics a 0.0 default would
    # silently neutralize the other configured threshold.
    high_risk_min_band_success_rate: float | None = None
    high_risk_min_calibrated_confidence: float | None = None


def apply_eligibility(
    bids: Sequence[ScoredBid], band: str, policy: PolicyParams
) -> list[ScoredBid]:
    """Mark valid bids that fail the High Risk floor as ineligible.

    A bid passes if it clears EITHER configured threshold. Failing bids stay
    in the result (with a reason) so the decision remains auditable.
    """
    sr_thr = policy.high_risk_min_band_success_rate
    conf_thr = policy.high_risk_min_calibrated_confidence
    if band != "High Risk" or (sr_thr is None and conf_thr is None):
        return list(bids)

    result = []
    for bid in bids:
        if not bid.is_valid:
            result.append(bid)
            continue
        passes = (sr_thr is not None and bid.risk_fit_score >= sr_thr) or (
            conf_thr is not None and bid.calibrated_confidence >= conf_thr
        )
        if passes:
            result.append(bid)
            continue
        checks = []
        if sr_thr is not None:
            checks.append(f"band success rate {bid.risk_fit_score:.2f} < {sr_thr:.2f}")
        if conf_thr is not None:
            checks.append(
                f"calibrated confidence {bid.calibrated_confidence:.2f} < {conf_thr:.2f}"
            )
        result.append(
            dataclasses.replace(
                bid,
                eligible=False,
                ineligible_reason="High Risk floor: " + "; ".join(checks),
            )
        )
    return result


def select_winner(
    bids: Sequence[ScoredBid], policy: PolicyParams
) -> tuple[ScoredBid | None, str | None]:
    """Pick a winner among eligible valid bids, or abstain with a reason."""
    valid = [bid for bid in bids if bid.is_valid]
    if not valid:
        return None, NO_VALID_BIDS_REASON
    eligible = [bid for bid in valid if bid.eligible]
    if not eligible:
        return None, "all valid bids failed the High Risk floor"

    if policy.selection_mode == "cheapest_adequate":
        adequate = [
            bid for bid in eligible if bid.quality_score >= policy.adequacy_min_quality
        ]
        if not adequate:
            return None, (
                "no eligible bid met the adequacy threshold"
                f" (quality >= {policy.adequacy_min_quality:.2f})"
            )
        chosen = min(
            adequate, key=lambda b: (b.estimated_cost_usd, -b.utility, b.agent_name)
        )
    else:
        chosen = min(
            eligible, key=lambda b: (-b.utility, b.estimated_cost_usd, b.agent_name)
        )

    if chosen.utility < policy.min_award_utility:
        return None, (
            f"best eligible utility {chosen.utility:.3f} is below"
            f" min_award_utility {policy.min_award_utility:.3f}"
        )
    return chosen, None
