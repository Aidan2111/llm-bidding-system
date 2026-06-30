---
name: Auctioning
summary: Score a task, gather bids in parallel, apply policy, and pick a winner by utility.
module: src/llm_bidding/application/auctioning.py
entrypoints: run_auction
read_when: changing the auction lifecycle, bid orchestration, timeouts/retries, or the fast path
---

# Auctioning

`run_auction(task_text, config, providers, store, ...)` is the orchestrator and
the system's primary entrypoint (library and `llm-bid bid`).

## Lifecycle

1. **Score** the task via `scoring.score_task_intent` → `IntentScoreResult`.
2. **Pre-fetch history** for every agent on the calling thread (sqlite
   connections are thread-bound, so workers never touch the DB).
3. **Gather bids** — either the statistical fast path (Low Risk + opt-in) or a
   `ThreadPoolExecutor` fan-out with a shared per-wave timeout and
   retry-with-backoff on `RetryableProviderError`. One bad provider becomes a
   recorded failure, never a hung or aborted auction.
4. **Score bids** via `utility.compute_scored_bid` (pure).
5. **Apply policy** (`policy.apply_eligibility` + `policy.select_winner`) and
   build the summary, including the recommended supervision mode.
6. **Record** to the history store unless `record=False`.

## Determinism

Worker results are collected into a dict and rebuilt in original agent order
before sorting, so output is deterministic given fixed `clock`, `id_factory`,
and `sleeper` seams (see `tests/test_auction_parallel.py`).

## Test seams

`clock`, `id_factory`, and `sleeper` are injectable. Tests use a fake sleeper
(zero real waiting), an event-blocking provider for timeouts, and
`MockBidProvider(transient_failures=...)` for retries.
