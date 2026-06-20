# Security Policy

This project routes task text, repository context, and optional diffs to
configured LLM providers. Treat that data as sensitive. Do not send private
source code, credentials, customer data, or internal incident details to a live
provider unless your organization has approved that provider and model route.

## Supported Versions

The `main` branch receives security fixes. Tagged releases should be treated as
snapshots; if a vulnerability affects an older release, upgrade to the latest
release or current `main` after validating the change in your environment.

## Reporting a Vulnerability

Use GitHub private vulnerability reporting for this repository when available:

https://github.com/Aidan2111/llm-bidding-system/security/advisories/new

If private reporting is unavailable, open a public issue with only a minimal
request for a private disclosure channel. Do not include exploit details,
secrets, private prompts, private diffs, or vulnerable production URLs in a
public issue.

## Security Baseline

- CI runs the offline test suite, package build, and wheel install smoke test.
- The security workflow runs `pip-audit` for Python dependency advisories.
- The security workflow runs `gitleaks` to detect committed credentials.
- Provider API keys must come from the environment or an untracked secret store.
- Actor workflows only propose patches. They do not apply code or execute
  commands by themselves.

## Maintainer Response

Security reports should be acknowledged as soon as practical. A fix should add
or update a regression test when the behavior is testable without publishing
sensitive details. Release notes should describe the impact at a level that
helps users upgrade without enabling exploitation.
