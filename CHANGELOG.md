# Changelog

All notable changes to this project are recorded here. The project follows a
pragmatic changelog style: user-visible behavior, public API changes, storage
migrations, provider changes, security posture, and operational docs belong in
this file.

## Unreleased

## 0.2.0 - 2026-08-23

- Updated the `agent-autonomy-score` source pin to the current tested `0.2.0`
  revision and added tag-driven GitHub release artifact automation.
- Corrected the README history documentation to identify schema v3.
- Documented schema v3's raw pre-calibration bid-cost column, which keeps cost
  calibration measurements from becoming self-referential.
- Fixed the README to name `infrastructure/autonomy_scoring.py` (not the
  pre-restructure `scoring.py` path) as the module that firewalls the
  `agent-autonomy-score` dependency, and clarified in `docs/architecture.md`
  that the layered packages are internal while the root modules are the
  stable public facade.
- Raised the dev extra's `twine` floor to 6.1.0, the first release that can
  validate the Metadata-Version 2.4 fields emitted by `setuptools>=77`.

- Restructured the package into `application`, `domain`, `infrastructure`,
  `interfaces`, and `providers` layers while keeping root compatibility modules.
- Added supervised actor proposal workflows for OpenAI-compatible and Ollama
  agents.
- Added local Ollama discovery, including VS Code local model registry support.
- Added historical cost-ratio calibration, scope-drift reporting, policy
  eligibility gates, and SQLite schema v2 migrations.
- Added architecture, operations, OSS-readiness, governance, support, security,
  and contribution documentation.
- Added repository-health tests, package build verification, typed package
  marker, Dependabot configuration, and security scanning workflow.

## 0.1.0 - Initial

- Built the first auction router that combines model self-assessment,
  deterministic autonomy-risk scoring, utility scoring, and SQLite history.
