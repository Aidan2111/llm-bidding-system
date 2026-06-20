"""Deterministic offline bid provider for tests, demos, and --dry-run."""

from __future__ import annotations

import hashlib
from typing import Iterable, Mapping

from ..domain.models import AgentProfile, Bid, BidRequest
from ..infrastructure.autonomy_scoring import EFFORT_BY_BAND
from .base import BidProviderError, RetryableProviderError


class MockBidProvider:
    """Derives stable pseudo-random bids from a hash of (seed, agent, task).

    The same inputs always produce the same bid, so auctions are fully
    reproducible without network access or API keys.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        confidence_overrides: Mapping[str, float] | None = None,
        fail_agents: Iterable[str] = (),
        transient_failures: Mapping[str, int] | None = None,
    ) -> None:
        self.seed = seed
        self.confidence_overrides = dict(confidence_overrides or {})
        self.fail_agents = frozenset(fail_agents)
        self._transient_remaining = dict(transient_failures or {})
        self.calls: list[str] = []  # append is GIL-atomic; safe across threads

    def request_bid(self, agent: AgentProfile, request: BidRequest) -> Bid:
        self.calls.append(agent.name)
        if agent.name in self.fail_agents:
            raise BidProviderError(f"Mock provider configured to fail for {agent.name!r}.")
        if self._transient_remaining.get(agent.name, 0) > 0:
            self._transient_remaining[agent.name] -= 1
            raise RetryableProviderError(
                f"Mock transient failure for {agent.name!r} (simulated 429)."
            )
        digest = hashlib.sha256(
            f"{self.seed}:{agent.name}:{request.task_text}".encode("utf-8")
        ).digest()
        confidence = self.confidence_overrides.get(
            agent.name, round(0.35 + (digest[0] / 255) * 0.6, 3)
        )
        word_count = max(request.intent.word_count, 1)
        estimated_input = 200 + word_count * 4 + digest[1] * 8
        estimated_output = 100 + request.intent.score * 120 + digest[2] * 4
        effort = EFFORT_BY_BAND.get(request.intent.band, "moderate")
        return Bid(
            agent_name=agent.name,
            model_id=agent.model_id,
            confidence=confidence,
            approach=(
                f"Mock plan from {agent.name}: address the task as a"
                f" {effort} change within the {request.intent.band} band."
            ),
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output,
            declared_effort=effort,
        )
