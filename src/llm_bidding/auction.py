"""Auction orchestration: score the intent, gather bids, pick a winner."""

from __future__ import annotations

import datetime
from typing import Callable, Iterable, Mapping
import uuid

from autonomy_score import score_intent
from autonomy_score.scoring import load_config as load_autonomy_config

from .config import BiddingConfig, ConfigError
from .history import HistoryStore
from .models import AuctionResult, BidRequest, ScoredBid
from .providers import BidProvider, BidProviderError
from .utility import compute_scored_bid, failed_bid


def _default_clock() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def run_auction(
    task_text: str,
    config: BiddingConfig,
    providers: Mapping[str, BidProvider],
    store: HistoryStore,
    *,
    agent_names: Iterable[str] | None = None,
    record: bool = True,
    clock: Callable[[], str] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> AuctionResult:
    autonomy_config = load_autonomy_config(config.autonomy_score_config)
    intent = score_intent(task_text, autonomy_config)
    request = BidRequest(task_text=task_text, intent=intent)

    if agent_names is None:
        agents = [profile for profile in config.agents if profile.enabled]
    else:
        agents = [config.agent(name) for name in agent_names]
        disabled = [profile.name for profile in agents if not profile.enabled]
        if disabled:
            raise ConfigError("Requested agents are disabled: " + ", ".join(disabled))
    if not agents:
        raise ConfigError("No enabled agents to run an auction with.")

    scored: list[ScoredBid] = []
    for agent in agents:
        stats = store.agent_stats(agent.name, config.calibration)
        provider = providers.get(agent.provider)
        if provider is None:
            scored.append(
                failed_bid(agent.name, f"No provider configured for {agent.provider!r}.", stats)
            )
            continue
        try:
            bid = provider.request_bid(agent, request)
        except BidProviderError as exc:
            scored.append(failed_bid(agent.name, str(exc), stats))
            continue
        band_stats = store.agent_stats(agent.name, config.calibration, band=intent.band)
        scored.append(compute_scored_bid(bid, agent, stats, band_stats, config))

    valid = [item for item in scored if item.is_valid]
    failures = [item for item in scored if not item.is_valid]
    # Deterministic ordering: utility desc, then cheaper, then name.
    valid.sort(key=lambda item: (-item.utility, item.estimated_cost_usd, item.agent_name))
    winner = valid[0] if valid else None

    if winner is not None:
        summary = (
            f"{winner.agent_name} wins with utility {winner.utility:.3f}"
            f" (confidence {winner.bid.confidence:.2f}, calibrated"
            f" {winner.calibrated_confidence:.2f}, est. cost"
            f" ${winner.estimated_cost_usd:.4f}) on a {intent.band} task"
            f" (intent score {intent.score})."
        )
    else:
        summary = "No valid bids were received; the auction has no winner."

    result = AuctionResult(
        auction_id=(id_factory or _default_id_factory)(),
        created_at=(clock or _default_clock)(),
        task_text=task_text,
        intent=intent,
        weights=config.weights.to_dict(),
        bids=tuple(valid + failures),
        winner=winner,
        summary=summary,
    )
    if record:
        store.record_auction(result)
    return result
