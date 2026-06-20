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
`llm_bidding.scoring` are compatibility wrappers. New code should import from
the deeper package that owns the behavior.

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
