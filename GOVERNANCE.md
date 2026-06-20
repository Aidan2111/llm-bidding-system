# Governance

`llm-bidding-system` is currently maintained by Aidan Marshall. Governance is
kept intentionally small while the project is alpha, but the project still has
explicit decision rules so external users can reason about stability.

## Decision Making

- The maintainer decides what merges to `main`.
- Changes that affect public imports, CLI output, JSON output, SQLite schema,
  config shape, provider behavior, or security posture require tests and docs.
- Compatibility wrappers at the package root should remain unless a major
  version explicitly removes them.
- Provider pricing in example configs is documentation, not a source of truth;
  users must verify current prices with their provider.

## Release Policy

Releases are cut from `main` after the full offline suite, package build, wheel
install smoke test, and security scans pass. Release notes go in `CHANGELOG.md`
and should call out migration, compatibility, provider, and security changes.

## Maintainer Responsibilities

- Keep project claims honest and conservative.
- Keep the test suite offline and deterministic by default.
- Review dependency updates for license, security, and behavior impact.
- Maintain clear docs for installation, integration, contribution, support, and
  security reporting.
- Avoid accepting autonomous code execution behavior without explicit design,
  review, and security analysis.

## Contributor Path

Frequent contributors can be given triage or review responsibility after they
demonstrate sound judgment in tests, docs, security, and compatibility. Merge
rights should remain limited until the project has a broader maintainer base.
