"""Auction orchestration: score the intent, gather bids, pick a winner."""

from __future__ import annotations

import concurrent.futures
import datetime
import time
from typing import Callable, Iterable, Mapping
import uuid

from .config import BiddingConfig, ConfigError
from .history import HistoryStore
from .models import AgentProfile, AgentStats, AuctionResult, Bid, BidRequest, ScoredBid
from .policy import apply_eligibility, select_winner
from .providers import BidProvider, BidProviderError, RetryableProviderError
from .scoring import EFFORT_BY_BAND, score_task_intent, scoring_version
from .utility import compute_scored_bid, failed_bid

FAST_PATH_APPROACH_PREFIX = "Statistical fast path"


def _default_clock() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def _fast_path_bid(
    agent: AgentProfile,
    stats: AgentStats,
    band_stats: AgentStats,
    band: str,
    config: BiddingConfig,
) -> Bid:
    if band_stats.outcomes_reported >= config.calibration.min_band_samples:
        confidence = band_stats.success_rate
    else:
        confidence = stats.success_rate
    return Bid(
        agent_name=agent.name,
        model_id=agent.model_id,
        confidence=confidence,
        approach=(
            f"{FAST_PATH_APPROACH_PREFIX} (no LLM call): bid derived from"
            " historical success rate."
        ),
        estimated_input_tokens=config.fast_path.default_input_tokens,
        estimated_output_tokens=config.fast_path.default_output_tokens,
        declared_effort=EFFORT_BY_BAND[band],
    )


def _gather_bids(
    agents: list[AgentProfile],
    providers: Mapping[str, BidProvider],
    request: BidRequest,
    all_stats: dict[str, tuple[AgentStats, AgentStats]],
    config: BiddingConfig,
    sleeper: Callable[[float], None],
) -> dict[str, ScoredBid]:
    """Fan bid requests out in parallel with per-wave timeout and retry.

    Worker threads only ever call provider.request_bid — all sqlite access
    happens on the caller's thread (sqlite connections are thread-bound).
    """
    results: dict[str, ScoredBid] = {}
    pending = list(agents)
    attempts = config.providers.retries + 1
    timeout = config.providers.timeout_seconds

    # Not a `with` block: shutdown(wait=True) would block behind a hung
    # provider call. Abandon stragglers instead and record them as timeouts.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(agents)))
    try:
        for attempt in range(1, attempts + 1):
            futures = {
                agent.name: pool.submit(
                    providers[agent.provider].request_bid, agent, request
                )
                for agent in pending
            }
            wave_start = time.monotonic()
            retry_next: list[AgentProfile] = []
            for agent in pending:
                stats, band_stats = all_stats[agent.name]
                remaining = max(0.0, timeout - (time.monotonic() - wave_start))
                try:
                    bid = futures[agent.name].result(timeout=remaining)
                except concurrent.futures.TimeoutError:
                    results[agent.name] = failed_bid(
                        agent.name,
                        f"Provider call timed out after {timeout:g}s.",
                        stats,
                    )
                except RetryableProviderError as exc:
                    if attempt < attempts:
                        retry_next.append(agent)
                    else:
                        results[agent.name] = failed_bid(
                            agent.name,
                            f"Transient provider failure after {attempts} attempts: {exc}",
                            stats,
                        )
                except BidProviderError as exc:
                    results[agent.name] = failed_bid(agent.name, str(exc), stats)
                else:
                    results[agent.name] = compute_scored_bid(
                        bid, agent, stats, band_stats, config
                    )
            pending = retry_next
            if not pending:
                break
            sleeper(config.providers.retry_backoff_seconds)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


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
    sleeper: Callable[[float], None] | None = None,
) -> AuctionResult:
    intent = score_task_intent(task_text, config_path=config.autonomy_score_config)
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

    # Pre-fetch all history on this thread; sqlite connections are thread-bound.
    all_stats: dict[str, tuple[AgentStats, AgentStats]] = {
        agent.name: (
            store.agent_stats(agent.name, config.calibration),
            store.agent_stats(agent.name, config.calibration, band=intent.band),
        )
        for agent in agents
    }

    use_fast_path = (
        intent.band == "Low Risk" and config.fast_path.skip_bids_for_low_risk
    )
    scored: list[ScoredBid] = []
    if use_fast_path:
        for agent in agents:
            stats, band_stats = all_stats[agent.name]
            bid = _fast_path_bid(agent, stats, band_stats, intent.band, config)
            scored.append(compute_scored_bid(bid, agent, stats, band_stats, config))
    else:
        callable_agents = []
        for agent in agents:
            if agent.provider not in providers:
                stats, _ = all_stats[agent.name]
                scored.append(
                    failed_bid(
                        agent.name,
                        f"No provider configured for {agent.provider!r}.",
                        stats,
                    )
                )
            else:
                callable_agents.append(agent)
        results = _gather_bids(
            callable_agents,
            providers,
            request,
            all_stats,
            config,
            sleeper or time.sleep,
        )
        # Rebuild in original agent order so output is deterministic.
        scored.extend(results[agent.name] for agent in callable_agents)

    valid = apply_eligibility(
        [item for item in scored if item.is_valid], intent.band, config.policy
    )
    failures = [item for item in scored if not item.is_valid]
    valid.sort(key=lambda item: (-item.utility, item.estimated_cost_usd, item.agent_name))
    winner, abstain_reason = select_winner(valid, config.policy)

    supervision = f"Recommended supervision: {intent.recommended_mode}."
    if winner is not None:
        summary = (
            f"{winner.agent_name} wins with utility {winner.utility:.3f}"
            f" (confidence {winner.bid.confidence:.2f}, calibrated"
            f" {winner.calibrated_confidence:.2f}, est. cost"
            f" ${winner.estimated_cost_usd:.4f}) on a {intent.band} task"
            f" (intent score {intent.score}). {supervision}"
        )
    else:
        summary = f"No winner: {abstain_reason}. {supervision}"

    result = AuctionResult(
        auction_id=(id_factory or _default_id_factory)(),
        created_at=(clock or _default_clock)(),
        task_text=task_text,
        intent=intent,
        weights=config.weights.to_dict(),
        bids=tuple(valid + failures),
        winner=winner,
        summary=summary,
        scoring_version=scoring_version(),
    )
    if record:
        store.record_auction(result)
    return result
