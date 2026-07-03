---
name: Scoring Integration
summary: Firewalled adapter over agent-autonomy-score; the only place the dependency is imported.
module: src/llm_bidding/infrastructure/autonomy_scoring.py
entrypoints: score_task_intent, score_result_diff, gate_intent_vs_diff, detect_scope_drift, ensure_compatible
read_when: changing how risk scores enter the system, bumping the agent-autonomy-score pin, or touching band/signal vocabulary
---

# Scoring Integration

`infrastructure/autonomy_scoring.py` is an anti-corruption layer around
[`agent-autonomy-score`](https://github.com/aidan2111/agent-autonomy-score)
(re-exported as `llm_bidding.scoring` for convenience). It is the **only**
module permitted to `import autonomy_score`
(`tests/test_scoring_adapter.py` enforces this with a grep guard).

## Why it exists

Risk bands (`Low/Medium/High Risk`) and signal names
(`intent:critical-domain`, …) are persisted in the history database and drive
the risk-fit utility term. If an upstream rename or re-banding leaked in
silently, historical bucketing would corrupt without any error. This module
turns that failure mode into one loud, early exception.

## What it provides

- **Canonical constants** — `BANDS`, `RECOMMENDED_MODES`, `EFFORT_BY_BAND`,
  `KNOWN_SIGNAL_PREFIXES`, `band_rank()`. Everything else imports these
  instead of hard-coding band strings.
- **`ensure_compatible(force=False)`** — cached probe run on first use: asserts
  the required API surface exists and that scoring a known string returns a
  band/mode within the canonical vocabulary. Raises
  `ScoringCompatibilityError` (naming the installed version and pinned commit)
  on drift.
- **Typed wrappers** — `score_task_intent`, `score_result_diff`,
  `gate_intent_vs_diff`, plus `load_trusted_scoring_config` (warns if the
  config file is group/world-writable, since its terms drive banding).
- **`detect_scope_drift`** — pure rule comparing a delivered diff's score/band
  against the auction's stored intent.

## Invariants

- No other module imports `autonomy_score`.
- Every auction records `scoring_version()` so history stays auditable across
  dependency bumps.
