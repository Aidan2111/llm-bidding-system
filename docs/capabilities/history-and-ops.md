---
name: History & Ops
summary: SQLite persistence with versioned migrations, plus the report/show/history/export/prune CLI surface.
module: src/llm_bidding/infrastructure/history_store.py
entrypoints: HistoryStore, llm-bid report, llm-bid show, llm-bid history, llm-bid export, llm-bid prune
read_when: changing the schema, adding a migration, or touching outcome reporting and ops commands
---

# History & Ops

`HistoryStore` (stdlib `sqlite3`) records auctions, bids, and outcomes, and
answers the per-agent/per-band stats queries that close the feedback loop.

## Schema and migrations

- Tables: `auctions`, `bids`, `outcomes`, `schema_version`.
- A migration runner upgrades older databases in place. `_MIGRATIONS[N]` holds
  the idempotent `ALTER`s from version N-1 → N; every added column is nullable
  so pre-upgrade rows keep working (`NULL` reads as "recorded before this
  version"). Current `_LATEST_SCHEMA_VERSION` is **3**.
- Connection hardening: `busy_timeout` always; `journal_mode = WAL` for file
  databases.

## Outcome reporting

`llm-bid report --auction-id X --success|--failure` records the result. With
`--diff`, the delivered diff is scored (`scoring.score_result_diff`), compared
against the stored intent for **scope drift**, and stored with a gate score.
`--actual-cost` feeds cost calibration. Drift is recorded and surfaced, never
auto-penalized.

## Ops commands

- `show --auction-id` — full stored auction, bids (incl. eligibility), outcome.
- `history [--limit N]` — recent auctions.
- `pending [--limit N]` — auctions that awarded a winner but never had an
  outcome reported, oldest first. Unreported outcomes starve calibration; the
  `stats` text output also flags each agent's `UNREPORTED` win count.
- `export [--output f.jsonl]` — every row as JSONL (`BrokenPipeError`-safe).
- `prune --keep-days N` — delete old auctions, cascading to bids/outcomes.

## Gotchas

- All `HistoryStore` access stays on the main thread (sqlite thread affinity);
  the auction pre-fetches stats before fanning out to worker threads.
- `prune` parses each `created_at` (`datetime.fromisoformat`; naive values are
  assumed UTC) rather than comparing strings; rows with unparseable timestamps
  are kept, never deleted.
