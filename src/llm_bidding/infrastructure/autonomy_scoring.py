"""Anti-corruption layer around the agent-autonomy-score dependency.

This is the ONLY module in llm_bidding that imports ``autonomy_score``.
Everything else consumes the typed wrappers and canonical constants defined
here, so an upstream rename or behavior change surfaces as one loud
``ScoringCompatibilityError`` instead of silently corrupting history
bucketing (risk bands and signal names are persisted in the auction
database and must stay stable).
"""

from __future__ import annotations

import os
import stat
import warnings

import autonomy_score
from autonomy_score import (
    GateResult,
    IntentScoreResult,
    ScoreResult,
    combine_intent_and_diff,
    score_change,
    score_intent,
)
from autonomy_score.diff_parser import parse_unified_diff
from autonomy_score.scoring import load_config as _load_autonomy_config

__all__ = [
    "BANDS",
    "EFFORT_BY_BAND",
    "GateResult",
    "IntentScoreResult",
    "KNOWN_SIGNAL_PREFIXES",
    "PINNED_COMMIT",
    "RECOMMENDED_MODES",
    "ScoreResult",
    "ScoringCompatibilityError",
    "band_rank",
    "detect_scope_drift",
    "ensure_compatible",
    "gate_intent_vs_diff",
    "load_trusted_scoring_config",
    "score_result_diff",
    "score_task_intent",
    "scoring_version",
]


class ScoringCompatibilityError(RuntimeError):
    """The installed agent-autonomy-score no longer matches this tool's API."""


# Canonical vocabulary this tool was built (and records history) against.
BANDS = ("Low Risk", "Medium Risk", "High Risk")
RECOMMENDED_MODES = ("Unsupervised", "Guided Autonomy", "Pair Programming")
EFFORT_BY_BAND = {
    "Low Risk": "trivial",
    "Medium Risk": "moderate",
    "High Risk": "substantial",
}
KNOWN_SIGNAL_PREFIXES = (
    "intent:",
    "blast-radius:",
    "big-o:",
    "validation:",
    "state-or-persistence",
    "critical-content",
    "algorithmic-risk",
    "presentation-only-cap",
)

# The commit pinned in pyproject.toml; named in compatibility errors so the
# remediation (re-pin or upgrade) is obvious.
PINNED_COMMIT = "5bc49198489778d45b05a65711e30b2e1287d12e"

_PROBE_TEXT = "Update the button label text."

_REQUIRED_ATTRS = (
    "score_intent",
    "score_change",
    "combine_intent_and_diff",
    "IntentScoreResult",
    "ScoreResult",
    "GateResult",
)

_compat_checked = False


def scoring_version() -> str:
    return getattr(autonomy_score, "__version__", "unknown")


def band_rank(band: str) -> int:
    try:
        return BANDS.index(band)
    except ValueError:
        raise ScoringCompatibilityError(
            f"Unknown risk band {band!r}; expected one of {BANDS}. "
            + _drift_hint()
        ) from None


def _drift_hint() -> str:
    return (
        f"The installed agent-autonomy-score (version {scoring_version()}, pinned"
        f" commit {PINNED_COMMIT[:12]}) no longer matches the API this tool was"
        " built against. Re-pin the dependency or upgrade llm-bidding-system."
    )


def ensure_compatible(*, force: bool = False) -> None:
    """Verify the dependency's API surface and scoring vocabulary.

    Cheap (one probe scoring of a constant string) and cached after the first
    successful run; ``force=True`` re-runs the check (used by tests).
    """
    global _compat_checked
    if _compat_checked and not force:
        return

    for attr in _REQUIRED_ATTRS:
        if not hasattr(autonomy_score, attr):
            raise ScoringCompatibilityError(
                f"autonomy_score is missing required attribute {attr!r}. " + _drift_hint()
            )
    if not callable(_load_autonomy_config) or not callable(parse_unified_diff):
        raise ScoringCompatibilityError(
            "autonomy_score config/diff helpers are not callable. " + _drift_hint()
        )

    try:
        probe = autonomy_score.score_intent(_PROBE_TEXT)
    except Exception as exc:
        raise ScoringCompatibilityError(
            f"score_intent probe raised {exc!r}. " + _drift_hint()
        ) from exc

    score = getattr(probe, "score", None)
    if not isinstance(score, int) or not 1 <= score <= 10:
        raise ScoringCompatibilityError(
            f"score_intent probe returned score {score!r}; expected an int in 1..10. "
            + _drift_hint()
        )
    band = getattr(probe, "band", None)
    if band not in BANDS:
        raise ScoringCompatibilityError(
            f"score_intent probe returned band {band!r}; expected one of {BANDS}. "
            + _drift_hint()
        )
    mode = getattr(probe, "recommended_mode", None)
    if mode not in RECOMMENDED_MODES:
        raise ScoringCompatibilityError(
            f"score_intent probe returned recommended_mode {mode!r}; expected one of"
            f" {RECOMMENDED_MODES}. " + _drift_hint()
        )
    signals = getattr(probe, "signals", None)
    if signals is None or not all(
        isinstance(getattr(signal, "name", None), str) for signal in signals
    ):
        raise ScoringCompatibilityError(
            "score_intent probe returned signals without string names. " + _drift_hint()
        )
    if not isinstance(getattr(probe, "word_count", None), int):
        raise ScoringCompatibilityError(
            "score_intent probe result is missing an integer word_count. " + _drift_hint()
        )

    _compat_checked = True


def load_trusted_scoring_config(path: str | None) -> dict[str, object] | None:
    """Load a custom autonomy-score config.

    The terms in this file drive risk banding, so it must come from a
    trusted, write-protected source (e.g. a protected branch or deploy
    artifact) — never from the work being evaluated. A best-effort warning
    is emitted when the file is group- or world-writable.
    """
    if not path:
        return None
    try:
        mode = os.stat(path).st_mode
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            warnings.warn(
                f"Scoring config {path!r} is group/world-writable; its terms drive"
                " risk banding and should come from a write-protected source.",
                stacklevel=2,
            )
    except OSError:
        pass  # load_config will raise a clearer error
    return _load_autonomy_config(path)


def score_task_intent(task_text: str, *, config_path: str | None = None) -> IntentScoreResult:
    ensure_compatible()
    return score_intent(task_text, load_trusted_scoring_config(config_path))


def score_result_diff(diff_text: str, *, config_path: str | None = None) -> ScoreResult:
    ensure_compatible()
    changed_files = parse_unified_diff(diff_text)
    return score_change(changed_files, load_trusted_scoring_config(config_path))


def gate_intent_vs_diff(intent: IntentScoreResult, diff: ScoreResult) -> GateResult:
    ensure_compatible()
    return combine_intent_and_diff(intent, diff)


def detect_scope_drift(
    intent_score: int,
    intent_band: str,
    diff_score: int,
    diff_band: str,
    *,
    score_threshold: int = 3,
) -> bool:
    """True when delivered work is markedly riskier than what was bid on.

    Deliberately computed from the stored auction columns (score + band)
    rather than a full GateResult, so drift is auditable from history alone.
    """
    if diff_score - intent_score >= score_threshold:
        return True
    return band_rank(diff_band) > band_rank(intent_band)
