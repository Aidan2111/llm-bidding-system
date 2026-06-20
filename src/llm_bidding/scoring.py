"""Compatibility wrapper for the autonomy-score adapter."""

from .infrastructure import autonomy_scoring as _adapter
from .infrastructure.autonomy_scoring import *  # noqa: F401,F403

autonomy_score = _adapter.autonomy_score
__all__ = [*_adapter.__all__, "autonomy_score"]
