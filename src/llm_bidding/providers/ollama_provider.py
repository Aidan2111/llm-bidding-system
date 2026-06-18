"""Bid provider backed by a local Ollama chat API."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib import error, request

from ..models import AgentProfile, Bid, BidRequest, BidValidationError
from .base import (
    BID_SCHEMA,
    SYSTEM_PROMPT,
    BidProviderError,
    RetryableProviderError,
    build_user_payload,
)


OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_TIMEOUT_SECONDS = 120.0
VSCODE_CHAT_MODELS_PATH = (
    "~/Library/Application Support/Code/User/chatLanguageModels.json"
)

PostJson = Callable[[str, Mapping[str, object], float], Mapping[str, object]]


class OllamaBidProvider:
    def __init__(
        self,
        *,
        base_url: str = OLLAMA_DEFAULT_BASE_URL,
        timeout_seconds: float = OLLAMA_DEFAULT_TIMEOUT_SECONDS,
        post_json: PostJson | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OllamaBidProvider":
        active_env = env if env is not None else os.environ
        timeout_raw = active_env.get("OLLAMA_TIMEOUT_SECONDS")
        timeout_seconds = OLLAMA_DEFAULT_TIMEOUT_SECONDS
        if timeout_raw:
            try:
                timeout_seconds = float(timeout_raw)
            except ValueError as exc:
                raise BidProviderError("OLLAMA_TIMEOUT_SECONDS must be a number.") from exc
            if timeout_seconds <= 0:
                raise BidProviderError("OLLAMA_TIMEOUT_SECONDS must be greater than 0.")
        base_url = (
            active_env.get("OLLAMA_BASE_URL")
            or _vscode_ollama_base_url(active_env)
            or OLLAMA_DEFAULT_BASE_URL
        )
        return cls(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def request_chat(
        self,
        agent: AgentProfile,
        messages: Sequence[Mapping[str, str]],
        *,
        response_format: object | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": agent.model_id,
            "messages": list(messages),
            "stream": False,
        }
        if response_format is not None:
            payload["format"] = response_format
        response = self._post_json(
            f"{self.base_url}/api/chat",
            payload,
            self.timeout_seconds,
        )
        content = _message_content(response)
        if not content.strip():
            raise BidProviderError("Ollama response did not include message content.")
        return content

    def request_bid(self, agent: AgentProfile, request_data: BidRequest) -> Bid:
        schema_text = json.dumps(BID_SCHEMA, indent=2, sort_keys=True)
        raw_text = self.request_chat(
            agent,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        build_user_payload(request_data)
                        + "\n\nReturn only JSON matching this schema:\n"
                        + schema_text
                    ),
                },
            ],
            response_format=BID_SCHEMA,
        )
        try:
            decoded = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise BidProviderError("Ollama bid response was not valid JSON.") from exc
        try:
            return Bid.from_payload(
                decoded,
                agent_name=agent.name,
                model_id=agent.model_id,
            )
        except BidValidationError as exc:
            raise BidProviderError(str(exc)) from exc


def request_ollama_chat(
    *,
    agent: AgentProfile,
    messages: Sequence[Mapping[str, str]],
    env: Mapping[str, str] | None = None,
) -> str:
    provider = OllamaBidProvider.from_env(env)
    return provider.request_chat(agent, messages)


def _normalize_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/api"):
        stripped = stripped[:-4]
    if not stripped:
        raise BidProviderError("OLLAMA_BASE_URL must not be empty.")
    return stripped


def _vscode_ollama_base_url(env: Mapping[str, str]) -> str | None:
    raw_path = env.get("VSCODE_CHAT_MODELS_PATH", VSCODE_CHAT_MODELS_PATH)
    path = Path(raw_path).expanduser()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    for entry in payload:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("vendor") != "ollama":
            continue
        url = entry.get("url")
        if isinstance(url, str) and url.strip():
            return url
    return None


def _message_content(payload: Mapping[str, object]) -> str:
    message = payload.get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str):
            return content
    response = payload.get("response")
    if isinstance(response, str):
        return response
    raise BidProviderError("Ollama response did not include message.content.")


def _post_json(url: str, payload: Mapping[str, object], timeout: float) -> Mapping[str, object]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = _read_error_detail(exc)
        message = f"Ollama request failed with HTTP {exc.code}: {detail}"
        if exc.code == 429 or exc.code >= 500:
            raise RetryableProviderError(message) from exc
        raise BidProviderError(message) from exc
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise RetryableProviderError(f"Ollama request failed: {exc}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BidProviderError("Ollama response was not valid JSON.") from exc
    if not isinstance(decoded, Mapping):
        raise BidProviderError("Ollama response JSON must be an object.")
    return decoded


def _read_error_detail(exc: error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        return str(exc)
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw or str(exc)
    if isinstance(decoded, Mapping) and isinstance(decoded.get("error"), str):
        return decoded["error"]
    return raw or str(exc)
