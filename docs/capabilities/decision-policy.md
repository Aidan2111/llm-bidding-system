---
name: Decision Policy
summary: Eligibility floors, abstain rules, and selection modes applied after utility scoring.
module: src/llm_bidding/domain/policy.py
entrypoints: PolicyParams, apply_eligibility, select_winner
read_when: changing how a winner is chosen, adding award rules, or adjusting abstain behavior
---

# Decision Policy

Pure functions over `ScoredBid`, slotted into `run_auction` after scoring and
before the winner is announced. All defaults are no-ops, so an unconfigured
system behaves as plain argmax-utility.

## Rules

- **High Risk floor** (`apply_eligibility`) — on High Risk tasks only, a bid
  must clear `high_risk_min_band_success_rate` **or**
  `high_risk_min_calibrated_confidence`. `None` disables a criterion (a `0.0`
  default would silently neutralize the OR). Failing bids stay in the result
  marked `eligible=False` with a human-readable reason.
- **Selection mode** (`select_winner`):
  - `"utility"` — argmax over `(-utility, cost, name)`.
  - `"cheapest_adequate"` — cheapest eligible bid whose `quality_score` clears
    `adequacy_min_quality`; abstains if none qualify. This is the
    "don't buy the flagship by default" mode.
- **Abstain** — if the chosen bid's utility is below `min_award_utility`,
  return no winner with a reason. The CLI maps no-winner to exit code 2.

## Per-band weights

Utility weights are resolved per risk band via `config.weights_for(band)`
(`utility.band_weights` in config; bands fall back to the global `weights`).
This lets price dominate cheap low-risk work while quality/risk-fit dominate
high-risk work, without changing the selection algorithm. The resolved weights
are stored on the `AuctionResult`.

## Gotchas

- `cheapest_adequate` can abstain rather than silently falling back to utility
  mode — operators must expect exit 2 when nothing meets the bar.
- Eligibility uses `risk_fit_score` (the shrunk band success rate) as the floor
  input, not raw confidence.
- Per-band weights still must each sum to 1.0; unknown band names are rejected
  at config load.
