"""Supervised patch proposal helpers for actor/supervisor workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..domain.models import AgentProfile
from ..providers.base import (
    BidProviderError,
    MissingDependencyError,
    classify_provider_exception,
)
from ..providers.ollama_provider import request_ollama_chat
from ..providers.openai_provider import _import_openai, openai_client_kwargs_from_env


DEFAULT_MAX_CONTEXT_BYTES = 40_000

PATCH_SYSTEM_PROMPT = """You are an LLM coding actor working under supervisor review.

You do not have write access. Your job is to propose a patch that a supervisor
can inspect, modify, apply, test, and either accept or reject.
"""


@dataclass(frozen=True)
class ContextEntry:
    path: str
    text: str


def read_context_files(
    paths: Sequence[str],
    *,
    max_bytes_per_file: int = DEFAULT_MAX_CONTEXT_BYTES,
) -> list[ContextEntry]:
    """Read explicit context files for a patch proposal prompt."""
    entries: list[ContextEntry] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"Context path is not a file: {raw_path}")
        data = path.read_bytes()
        truncated = len(data) > max_bytes_per_file
        visible = data[:max_bytes_per_file].decode("utf-8", errors="replace")
        if truncated:
            visible += f"\n[truncated after {max_bytes_per_file} bytes]\n"
        entries.append(ContextEntry(path=str(path), text=visible))
    return entries


def build_patch_prompt(
    *,
    task_text: str,
    context_entries: Sequence[ContextEntry],
    actor_name: str,
    supervisor_name: str = "Codex",
    auction_summary: str | None = None,
) -> str:
    """Build the exact prompt sent to the coding actor."""
    sections = [
        f"Actor: {actor_name}",
        f"Supervisor: {supervisor_name}",
        "",
        "Task:",
        task_text.strip(),
        "",
        "Contract:",
        "- Propose changes only; do not claim that you applied them.",
        f"- {supervisor_name} will inspect, apply, edit, test, and report the outcome.",
        "- Return a concise rationale followed by a unified diff.",
        "- Keep the patch scoped to the task and avoid unrelated refactors.",
        "- Do not include secrets, credentials, or machine-specific paths.",
    ]
    if auction_summary:
        sections += ["", "Auction context:", auction_summary.strip()]
    if context_entries:
        sections += ["", "Repository context:"]
        for entry in context_entries:
            sections += [
                f"--- {entry.path} ---",
                entry.text.rstrip(),
            ]
    return "\n".join(sections).rstrip() + "\n"


def request_patch_proposal(
    *,
    agent: AgentProfile,
    prompt: str,
    env: Mapping[str, str] | None = None,
) -> str:
    """Ask an OpenAI-compatible actor for a supervised patch proposal."""
    if agent.provider == "ollama":
        return request_ollama_chat(
            agent=agent,
            messages=[
                {"role": "system", "content": PATCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            env=env,
        ).strip()
    if agent.provider != "openai":
        raise BidProviderError(
            "Patch proposals currently require an OpenAI-compatible or Ollama agent."
        )
    try:
        OpenAI = _import_openai()
    except MissingDependencyError:
        raise
    kwargs = openai_client_kwargs_from_env(env)
    client = OpenAI(**kwargs)
    try:
        response = client.responses.create(
            model=agent.model_id,
            input=[
                {"role": "system", "content": PATCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    except AttributeError as exc:
        raise BidProviderError(
            'The installed OpenAI SDK does not expose the Responses API. '
            'Upgrade with: pip install -U "openai>=1.68.0"'
        ) from exc
    except Exception as exc:
        raise classify_provider_exception(exc, "OpenAI-compatible patch proposal") from exc
    raw_text = getattr(response, "output_text", None)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise BidProviderError("OpenAI response did not include output_text.")
    return raw_text.strip()
