# AGENTS.md

Operating guide for AI agents (and humans) working in this repository.
`llm-bidding-system` is an **auction router for LLM work**: multiple model
agents bid on a task, and a configurable utility function — informed by
`agent-autonomy-score` risk scoring and historical performance — picks the
winner. See [README.md](README.md) for the user-facing overview.

## How to use this file (progressive disclosure)

This file is an **index, not a manual**. Each capability below is listed by its
front matter only — name, one-line summary, owning module, and when to read it.
**Do not load every capability doc up front.** Read the summaries here, then
open the full `docs/capabilities/<name>.md` file *only* for the capability you
are about to change. Each capability doc begins with the same YAML front matter
shown here, followed by the detailed body.

The index is kept honest by `tests/test_capabilities.py`, which validates every
capability's front matter and asserts this file references every doc.

## Repository layout

Layered (vertical-slice) architecture; see
[`docs/architecture.md`](docs/architecture.md) for the dependency rules.

```
src/llm_bidding/
  domain/            # pure logic: models, utility, policy, calibration
  application/       # use cases: auctioning, patch_proposals
  infrastructure/    # adapters: autonomy_scoring, history_store, configuration
  interfaces/        # delivery: cli
  providers/         # bid backends: base, anthropic, openai, ollama, mock
  *.py               # thin compatibility shims re-exporting the above
docs/capabilities/   # one progressively-disclosed doc per capability
docs/                # architecture, operations, oss-readiness
tests/               # unittest; offline (mock providers, in-memory SQLite)
examples/            # config samples + manual smoke scripts
```

Top-level modules (`scoring.py`, `auction.py`, `history.py`, …) are
compatibility shims that re-export from the layers above; edit the canonical
module named in each capability doc, not the shim.

## Capabilities

Open the linked file for full detail; the lines under each are its front matter.

### [Scoring Integration](docs/capabilities/scoring-integration.md)
- **summary:** Firewalled adapter over agent-autonomy-score; the only place the dependency is imported.
- **module:** `src/llm_bidding/infrastructure/autonomy_scoring.py`
- **read_when:** changing how risk scores enter the system, bumping the agent-autonomy-score pin, or touching band/signal vocabulary

### [Auctioning](docs/capabilities/auctioning.md)
- **summary:** Score a task, gather bids in parallel, apply policy, and pick a winner by utility.
- **module:** `src/llm_bidding/application/auctioning.py`
- **read_when:** changing the auction lifecycle, bid orchestration, timeouts/retries, or the fast path

### [Bidding Providers](docs/capabilities/bidding-providers.md)
- **summary:** Pluggable backends that turn a task into a structured bid; live Anthropic/OpenAI plus a deterministic mock.
- **module:** `src/llm_bidding/providers`
- **read_when:** adding a model provider, changing the bid schema/prompt, or tuning transient-error classification

### [Decision Policy](docs/capabilities/decision-policy.md)
- **summary:** Eligibility floors, abstain rules, and selection modes applied after utility scoring.
- **module:** `src/llm_bidding/domain/policy.py`
- **read_when:** changing how a winner is chosen, adding award rules, or adjusting abstain behavior

### [Calibration](docs/capabilities/calibration.md)
- **summary:** Deterministic feedback that turns reported outcomes into success rates, confidence offsets, and cost ratios.
- **module:** `src/llm_bidding/domain/calibration.py`
- **read_when:** changing how history adjusts future bids or the cost/quality math

### [History & Ops](docs/capabilities/history-and-ops.md)
- **summary:** SQLite persistence with versioned migrations, plus the report/show/history/export/prune CLI surface.
- **module:** `src/llm_bidding/infrastructure/history_store.py`
- **read_when:** changing the schema, adding a migration, or touching outcome reporting and ops commands

## Conventions

- **Stdlib-only core.** No required runtime deps beyond `agent-autonomy-score`.
  Model SDKs (`anthropic`, `openai`) are optional extras with lazy imports.
- **Frozen dataclasses** for all domain types; `to_dict()` for serialization.
- **Determinism.** Keep the `clock` / `id_factory` / `sleeper` seams in
  `run_auction` intact; tests rely on them.
- **Backward-compatible config and schema.** New config keys default to the
  prior behavior; new DB columns are nullable with a migration.

## Public API and the shim layer (explicit policy)

The top-level modules (`llm_bidding.scoring`, `.auction`, `.history`,
`.models`, `.policy`, `.utility`, `.config`, plus `llm_bidding.__init__`
re-exports) are the **stable public façade** — external callers and tests
import from them. The layered packages (`domain/`, `application/`,
`infrastructure/`, `interfaces/`) are **internal** and may be reorganized
without notice.

Rules that follow:

- Shims contain **only** `import *` re-exports — never logic. If you're adding
  code to a top-level shim module, you're in the wrong file.
- New public symbols must be reachable through a façade module; new internal
  helpers should NOT be added to a façade.
- Internal code imports from the layers directly (relative imports), never
  through the façade — that keeps the dependency direction one-way.

## Working here

- Run tests: `python -m unittest discover -s tests` (fully offline).
- Drift check: `python -c "import llm_bidding.scoring as s; s.ensure_compatible()"`.
- Never add a second `import autonomy_score` — route everything through
  `infrastructure/autonomy_scoring.py`.
- After changing a capability, update its `docs/capabilities/<name>.md`.
