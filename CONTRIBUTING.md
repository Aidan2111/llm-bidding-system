# Contributing

`llm-bidding-system` is a Python package and CLI for routing software work to
LLM agents under human or supervisor control. Contributions should keep the
project useful to downstream systems: stable public contracts, tested behavior,
clear docs, and no hidden provider side effects.

## Development Setup

Use Python 3.10 or newer. The CI matrix covers 3.10, 3.11, and 3.12.

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[all]"
PYTHONPATH=tests .venv/bin/python -m unittest discover -s tests -v
```

If you are using `uv`, this is the local verification path used by maintainers:

```bash
PYTHONPATH=tests uv run --python 3.12 --with-editable . \
  --with git+https://github.com/aidan2111/agent-autonomy-score@5bc49198489778d45b05a65711e30b2e1287d12e \
  python -m unittest discover -s tests -v
```

## Branch and PR Policy

- Work on a topic branch and open a pull request into `main`.
- Keep pull requests scoped to one behavior or documentation improvement.
- Use the pull request template and include the exact verification commands.
- Do not commit provider credentials, `.env` files, SQLite history databases,
  generated proposals, or local model registry files.
- Public behavior changes require docs updates in the same pull request.

## Architecture Rules

- New domain logic belongs in `src/llm_bidding/domain` and must not import
  providers, SQLite, config loading, CLI code, or `agent-autonomy-score`.
- Workflow orchestration belongs in `src/llm_bidding/application`.
- External systems and persistence belong in `src/llm_bidding/infrastructure`.
- User-facing argument parsing and exit codes belong in `src/llm_bidding/interfaces`.
- Provider SDK adapters belong in `src/llm_bidding/providers`.
- Top-level modules such as `llm_bidding.auction` are compatibility wrappers;
  keep them thin.

## Testing Expectations

Every behavior change needs a focused failing test first. Prefer offline tests
using deterministic providers and in-memory SQLite. Live provider smoke scripts
under `examples/` are useful before a release, but they are not a substitute for
unit tests because they depend on credentials and remote model behavior.

Run these before requesting review:

```bash
PYTHONPATH=tests python -m unittest discover -s tests -v
python -m build
gitleaks dir . --no-banner --redact --exit-code 1
```

## Documentation Expectations

Update `README.md` for common user workflows, `docs/architecture.md` for
boundary changes, and `docs/operations.md` for integration or production
behavior. If a change affects contribution, security, support, governance, or
release process, update the matching root document.
