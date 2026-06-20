# Support

This project is maintained as an open source developer tool. It is suitable for
experimentation and supervised routing workflows, not as a managed hosted
service with an uptime commitment.

## Getting Help

- For installation, configuration, provider, or CLI usage questions, open a
  GitHub issue with the command, Python version, package version, and sanitized
  output.
- For reproducible bugs, use the bug report template and include a minimal
  config or command that does not require private API keys.
- For security concerns, follow `SECURITY.md` and avoid public details.
- For contribution process questions, see `CONTRIBUTING.md`.

## What To Include

Good support requests include:

- Python version and operating system.
- Installation command and whether the package is editable or installed from a
  wheel.
- The `llm-bid` command or Python API call.
- Config snippets with API keys removed.
- Whether the run used deterministic mocks, OpenAI-compatible APIs, Anthropic,
  or Ollama.
- The full error message or JSON output with private task text redacted.

## Scope

Maintainers can help with package behavior, documented workflows, and defects.
Maintainers cannot provide provider account support, guarantee model quality,
debug private production systems without a reproducer, or review proprietary
code through public issues.
