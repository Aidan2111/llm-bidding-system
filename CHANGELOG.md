# Changelog

All notable changes to this project are recorded here. The project follows a
pragmatic changelog style: user-visible behavior, public API changes, storage
migrations, provider changes, security posture, and operational docs belong in
this file.

## 0.2.0 - 2026-06-19

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
