---
name: Calibration
summary: Deterministic feedback that turns reported outcomes into success rates, confidence offsets, and cost ratios.
module: src/llm_bidding/domain/calibration.py
entrypoints: shrunk_success_rate, calibration_offset, brier_score, shrunk_cost_ratio
read_when: changing how history adjusts future bids or the cost/quality math
---

# Calibration

Simple, inspectable formulas (no learned weights) in the spirit of the parent
scoring project. Consumed by `utility.compute_scored_bid` and surfaced in
`llm-bid stats`.

## Quantities

- **`shrunk_success_rate(successes, outcomes, params)`** — Laplace shrinkage
  toward a neutral prior (default 0.5, strength 4). Cold start is exactly the
  prior, so new agents are neither punished nor favored.
- **`calibration_offset(pairs, params)`** — mean `(outcome − stated
  confidence)` over won+reported auctions, clamped to `±max_calibration_shift`,
  applied only after `min_calibration_samples`. Overconfident agents get pushed
  down.
- **`brier_score(pairs)`** — surfaced for transparency; not in the utility
  formula.
- **`shrunk_cost_ratio(ratios, params)`** — mean `actual / raw estimate` shrunk
  toward 1.0 and clamped to `[cost_ratio_min, cost_ratio_max]`. Corrects each
  agent's habitual estimation bias before the price score.

## Critical invariant (v0.2.0 fix)

The cost ratio is measured against the bid's **raw** estimate
(`ScoredBid.raw_estimated_cost_usd`), not the ratio-adjusted
`estimated_cost_usd` that feeds the price score. Calibrating against the
adjusted value would be self-referential and never converge. Regression:
`tests/test_cost_ratio.py::test_ratio_is_measured_against_raw_not_adjusted_estimate`.
