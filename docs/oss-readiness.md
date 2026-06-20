# OSS Readiness

This checklist maps the repository to public Microsoft guidance and adjacent
OpenSSF supply-chain guidance. It is not a claim that this project is a
Microsoft project. It uses those standards as an engineering bar for a public,
inspectable OSS repository.

## Standards Read

- Microsoft Engineering Fundamentals Playbook, Source Control:
  https://microsoft.github.io/code-with-engineering-playbook/source-control/
- Microsoft Engineering Fundamentals Playbook, Maintainability:
  https://microsoft.github.io/code-with-engineering-playbook/non-functional-requirements/maintainability/
- Microsoft Engineering Fundamentals Playbook, Documentation:
  https://microsoft.github.io/code-with-engineering-playbook/documentation/
- Microsoft Open Source Program:
  https://opensource.microsoft.com/program/
- Microsoft Open Source Code of Conduct FAQ:
  https://opensource.microsoft.com/codeofconduct/faq/
- Microsoft Secure Supply Chain Consumption Framework:
  https://www.microsoft.com/en-us/securityengineering/sdl/s2c2f
- OpenSSF S2C2F project:
  https://github.com/ossf/s2c2f

## Repository Health

- Root `LICENSE`, `README.md`, and `CONTRIBUTING.md` are present.
- `README.md` links contribution, security, support, code of conduct,
  governance, changelog, architecture, operations, and OSS readiness docs.
- `.github/PULL_REQUEST_TEMPLATE.md` and issue templates make contribution and
  review expectations visible.
- `GOVERNANCE.md` names the maintainer model, release policy, and compatibility
  decision rules.
- `CODE_OF_CONDUCT.md` defines behavior expectations and reporting direction.

## Engineering Health

- CI runs Python 3.10, 3.11, and 3.12.
- CI runs the offline unit suite, scoring dependency compatibility canary,
  package build, metadata check, wheel install, and CLI smoke check.
- `src/llm_bidding/py.typed` marks the package typed for downstream consumers.
- Repository-health tests guard required OSS files, CI gates, public metadata,
  architecture sections, and domain layering rules.
- `docs/architecture.md` defines public contracts, dependency boundaries, and
  compatibility policy.
- `docs/operations.md` documents exit codes, failure modes, storage behavior,
  and production integration checks.

## Supply Chain Health

S2C2F is consumption-focused, so this repository cannot make an adopting
organization compliant by itself. It can still provide practical controls:

- Inventory: dependencies are declared in `pyproject.toml`; the scoring
  dependency is pinned to a commit.
- Scan: `.github/workflows/security.yml` runs `pip-audit` and `gitleaks`.
- Update: `.github/dependabot.yml` requests weekly Python and GitHub Actions
  updates.
- Enforce: CI fails on tests, build, metadata, compatibility, and security
  checks before merge.
- Fix: `SECURITY.md` gives a private vulnerability reporting path and expected
  maintainer response.

## Current Limits

- The project is alpha and should be integrated under supervision.
- The default provider price table is example data and must be checked against
  current provider pricing.
- Live model quality is not deterministic; production consumers should use
  policy gates, dry-run tests, outcome reporting, and human review for risky
  work.
- Repository branch protection is a GitHub repository setting. The expected
  policy is documented in `CONTRIBUTING.md`; maintainers should enforce it in
  GitHub before broad public use.
