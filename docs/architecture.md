# Architecture

`llm-bidding-system` is organized around small vertical workflows with explicit
dependency boundaries. The command-line surface stays stable through
compatibility modules at the package root, while implementation code lives in
folders that show its responsibility.

## Package Layout

```
src/llm_bidding/
  application/      End-to-end workflow services.
  domain/           Pure models, calibration math, policies, and utility scoring.
  infrastructure/   Config, SQLite history, and external autonomy-score adapter.
  interfaces/       User-facing CLI entry point.
  providers/        LLM provider adapters for Anthropic, OpenAI-compatible APIs,
                    Ollama, and deterministic mocks.
```

Top-level modules such as `llm_bidding.auction`, `llm_bidding.config`, and
`llm_bidding.scoring` are compatibility wrappers and form the stable public
facade. New code *inside this repository* should import from the deeper
package that owns the behavior; external callers should import from the root
`llm_bidding` exports or the wrapper modules, because the layered packages
are internal and may be reorganized. See the shim-layer policy in
[AGENTS.md](../AGENTS.md).

## Public Contracts

The supported Python surface is exported from `llm_bidding`: `run_auction`,
`load_config`, `HistoryStore`, the domain dataclasses, and the public error
types. Provider implementations must satisfy the `BidProvider` protocol:
`request_bid(agent, request) -> Bid`. Callers that need machine-readable output
should use `llm-bid --format json` rather than parsing text tables.

The supported CLI contract is:

- `llm-bid bid` returns `0` when a winner is selected and `2` when policy or
  provider results produce no winner.
- `llm-bid report` records exactly one outcome for a winning auction.
- `llm-bid stats`, `show`, `history`, `export`, and `agents list` are read-only
  inspection commands except for `prune`, which deletes old history.
- `llm-bid propose` asks an actor for a patch proposal only; it never edits the
  checkout.

The SQLite schema is internal to `HistoryStore`, but migrations are expected to
preserve old rows. Larger systems should use `export` or the Python API instead
of issuing their own SQL against private tables.

## Dependency Rules

- `domain` does not import providers, config loading, SQLite, or
  `agent-autonomy-score`.
- `application` coordinates a workflow by composing domain logic,
  infrastructure adapters, and providers.
- `infrastructure` owns external systems and persistence concerns.
- `interfaces` handles argument parsing, stdout/stderr, and exit codes.
- `providers` adapt external model APIs into the domain `BidProvider` contract.

These rules keep the blast radius small when a provider SDK changes, a storage
migration is added, or the CLI grows another command.

## Vertical Workflows

Auction workflow:

```
interfaces.cli
  -> application.auctioning.run_auction
    -> infrastructure.autonomy_scoring
    -> providers
    -> domain.utility and domain.policy
    -> infrastructure.history_store
```

Supervised patch proposal workflow:

```
interfaces.cli
  -> application.patch_proposals
    -> providers.openai_provider or providers.ollama_provider
```

Each workflow can be tested through the public CLI, the application service, or
the smaller domain/infrastructure units underneath it.

## Compatibility Policy

While the package is in alpha, minor releases may add fields to JSON output,
add SQLite columns, or add new config keys. They should not remove root
compatibility imports, change exit-code meaning, or change existing JSON field
meaning without a changelog entry and tests. Breaking public import, CLI, JSON,
or database behavior requires a version bump and migration notes.

Provider SDKs and model APIs are intentionally isolated. A provider change
should be contained inside `providers` unless it requires a new domain concept.
Changes to `agent-autonomy-score` must pass the compatibility canary before an
auction is allowed to run.

## Well-Architected Mapping

- Operational excellence: CLI commands have stable exit codes, deterministic
  dry-run paths, and explicit history operations.
- Reliability: provider calls are isolated behind retry and timeout handling;
  SQLite schema migrations are tested.
- Security: prompt construction is explicit, context is file-scoped, and actor
  workflows propose patches rather than applying code directly.
- Cost optimization: cost estimates, historical cost ratios, and selection
  policy are pure domain logic and easy to audit.
- Performance efficiency: auction bid collection is parallelized while SQLite
  access stays on the caller thread.
- Maintainability: dependency direction is documented and guarded by tests,
  especially around the `agent-autonomy-score` anti-corruption layer.
