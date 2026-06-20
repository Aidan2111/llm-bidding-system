# Operations

This guide is for teams embedding `llm-bidding-system` in a larger supervised
workflow. The package is a router and record keeper. It does not execute the
winning work by itself.

## Runtime Surfaces

- CLI: `llm-bid bid`, `report`, `stats`, `agents list`, `show`, `history`,
  `export`, `prune`, and `propose`.
- Python API: `run_auction`, `load_config`, `HistoryStore`, domain models, and
  provider contracts exported from `llm_bidding`.
- Storage: SQLite history database, defaulting to `~/.llm-bidding/history.db`.
- Providers: Anthropic, OpenAI-compatible APIs, Ollama, and deterministic mocks.

## Exit Codes

- `0`: command completed and, for `bid`, a winner was selected.
- `1`: configuration, provider, storage, input, scoring compatibility, or file
  error.
- `2`: auction completed but no winner was selected because bids failed,
  eligibility removed every bid, or policy abstained.

Automation should treat exit code `2` as a valid routing outcome, not a process
crash. The correct fallback is usually human review, a different config, or a
later retry.

## History Database

Set `--db` or `LLM_BIDDING_DB` when running in CI, shared services, or tests.
The default home-directory database is appropriate for a single developer. File
databases use WAL mode and a busy timeout. SQLite still has process-level
limits, so high-concurrency systems should serialize write commands or export
events into their own durable store.

Schema migrations are automatic and backward compatible for existing rows. If a
future release needs a destructive migration, it must be called out in
`CHANGELOG.md` and guarded by tests.

## Failure Modes

- Missing API key: live cloud provider construction fails before an auction.
- Provider timeout: that provider is recorded as a failed bid and other bids
  can still compete.
- Retryable provider error: 429, 5xx, timeout, or connection errors are retried
  according to config.
- Malformed provider output: the bid is rejected and recorded as a provider
  failure.
- Scoring dependency drift: `ScoringCompatibilityError` stops the command
  rather than silently changing risk bands.
- No eligible winner: command exits `2` and prints the abstain reason.

## Production Integration Checklist

- Pin package and `agent-autonomy-score` versions.
- Keep provider API keys outside the repository and outside config files.
- Use `--format json` for machine consumers.
- Store a dedicated history database per environment.
- Report outcomes with `llm-bid report`; the feedback loop depends on it.
- Include delivered diffs in reports when possible so scope drift is visible.
- Decide whether `High Risk` tasks need policy floors before a model can win.
- Use `--dry-run` and deterministic mock providers in CI tests.
- Run `llm-bid --help` and one dry-run bid after installing a wheel.
- Monitor exit code `2` separately from infrastructure failures.

## Manual Smoke Paths

The scripts under `examples/` are intentionally manual because they use real
provider routes or local model servers. They are useful before a release or
provider change, but CI should stay offline and deterministic.
