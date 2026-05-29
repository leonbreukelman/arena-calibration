"""OpenAI-compatible API adapters for live Verifier model calls.

These adapters preserve the existing Worker/Judge protocols and prompt text
from arena.llm while routing requests to low-cost OpenAI-compatible providers
such as xAI, Gemini, and OpenRouter.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from arena.llm import (
    JUDGE_MAX_TOKENS,
    JUDGE_TEMPERATURE,
    WORKER_MAX_TOKENS,
    WORKER_TEMPERATURE,
    _JUDGE_SYSTEM,
    _REGEN_SYSTEM,
    build_judge_prompt,
    build_regen_prompt,
)

XAI_MODEL = "grok-4.3"
GEMINI_MODEL = "gemini-2.5-flash-lite"
OPENROUTER_MODEL = "x-ai/grok-4.3"
DEFAULT_TIMEOUT_SECONDS = 180


class ApiModelError(RuntimeError):
    """Raised when an API-backed model call cannot produce visible text."""


@dataclass(frozen=True)
class ApiProviderConfig:
    provider: str
    base_url: str
    key_env_names: tuple[str, ...]
    default_worker_model: str
    default_judge_model: str


PROVIDER_CONFIGS: dict[str, ApiProviderConfig] = {
    "xai": ApiProviderConfig(
        provider="xai",
        base_url="https://api.x.ai/v1",
        key_env_names=("XAI_API_KEY",),
        default_worker_model=XAI_MODEL,
        default_judge_model=XAI_MODEL,
    ),
    "gemini": ApiProviderConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_env_names=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        default_worker_model=GEMINI_MODEL,
        default_judge_model=GEMINI_MODEL,
    ),
    "openrouter": ApiProviderConfig(
        provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        key_env_names=("OPENROUTER_API_KEY",),
        default_worker_model=OPENROUTER_MODEL,
        default_judge_model=OPENROUTER_MODEL,
    ),
}


def _resolve_api_key(
    provider: str,
    key_env_names: tuple[str, ...],
    explicit_api_key: str | None,
) -> str:
    if explicit_api_key:
        return explicit_api_key
    for name in key_env_names:
        value = os.environ.get(name)
        if value:
            return value
    names = ", ".join(key_env_names)
    raise ApiModelError(f"{provider}: missing API key; set one of: {names}")


def _endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _message_fragments(messages: list[dict[str, str]]) -> list[str]:
    fragments: list[str] = []
    for message in messages:
        content = message.get("content", "")
        fragments.append(content)
        fragments.extend(line.strip() for line in content.splitlines() if line.strip())
    return fragments


def _sanitize(text: str, sensitive: Iterable[str]) -> str:
    sanitized = text
    for fragment in sensitive:
        if fragment:
            sanitized = sanitized.replace(fragment, "[REDACTED]")
    return sanitized[:500]


def _verify_served_model(
    payload: dict[str, Any],
    *,
    provider: str,
    requested_model: str,
    accepted_served_models: tuple[str, ...],
    sensitive: Iterable[str],
) -> None:
    """Require the API response to name an explicitly accepted served model.

    Exact requested-model equality is the default anti-redirect policy. Providers
    that legitimately return normalized/versioned IDs must be opted in with an
    explicit accepted_served_models entry; there are no prefix heuristics.
    """
    served_model = payload.get("model")
    if not isinstance(served_model, str) or not served_model.strip():
        raise ApiModelError(f"{provider}: served model missing from response")

    accepted = {requested_model, *accepted_served_models}
    if served_model not in accepted:
        safe_requested = _sanitize(requested_model, sensitive)
        safe_served = _sanitize(served_model, sensitive)
        raise ApiModelError(
            f"{provider}: served model mismatch; "
            f"requested {safe_requested!r}; served {safe_served!r}"
        )


def _parse_visible_message_content(payload: dict[str, Any], provider: str) -> str:
    try:
        choices = payload["choices"]
        choice = choices[0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiModelError(f"{provider}: malformed chat-completions response") from exc
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        raise ApiModelError(f"{provider}: response truncated at max_tokens")
    if not isinstance(message, dict):
        raise ApiModelError(f"{provider}: malformed chat-completions response")

    content = message.get("content")
    if content is None:
        raise ApiModelError(
            f"{provider}: response did not contain visible message content"
        )
    if isinstance(content, str):
        if content.strip():
            return content
        raise ApiModelError(
            f"{provider}: response did not contain visible message content"
        )
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        joined = "".join(parts)
        if joined.strip():
            return joined
        raise ApiModelError(
            f"{provider}: response did not contain visible message content"
        )
    raise ApiModelError(f"{provider}: unsupported visible message content type")


@dataclass
class OpenAICompatibleClient:
    provider: str
    base_url: str
    key_env_names: tuple[str, ...]
    api_key: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def complete_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        accepted_served_models: tuple[str, ...] = (),
    ) -> str:
        key = _resolve_api_key(self.provider, self.key_env_names, self.api_key)
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            _endpoint(self.base_url),
            data=data,
            method="POST",
        )
        request.add_header("Authorization", f"Bearer {key}")
        request.add_header("Content-Type", "application/json")
        sensitive = [key, *_message_fragments(messages)]
        try:
            with urllib.request.urlopen(  # noqa: S310 - provider URLs are fixed configs
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ApiModelError(
                f"{self.provider}: HTTP {exc.code} from chat completions; "
                "upstream body omitted"
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = _sanitize(str(exc), sensitive)
            raise ApiModelError(f"{self.provider}: request failed: {reason}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiModelError(
                f"{self.provider}: malformed JSON chat-completions response"
            ) from exc
        _verify_served_model(
            payload,
            provider=self.provider,
            requested_model=model,
            accepted_served_models=accepted_served_models,
            sensitive=sensitive,
        )
        return _parse_visible_message_content(payload, self.provider)


@dataclass
class OpenAICompatibleWorker:
    provider: str
    base_url: str
    key_env_names: tuple[str, ...]
    model: str
    api_key: str | None = None
    max_tokens: int = WORKER_MAX_TOKENS
    temperature: float = WORKER_TEMPERATURE
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    accepted_served_models: tuple[str, ...] = ()

    def regenerate_patch(
        self,
        file_contents: str,
        reasoning: str,
        target_path: str,
    ) -> str:
        prompt = build_regen_prompt(
            target_path=target_path,
            file_contents=file_contents,
            reasoning=reasoning,
        )
        return OpenAICompatibleClient(
            provider=self.provider,
            base_url=self.base_url,
            key_env_names=self.key_env_names,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        ).complete_chat(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            accepted_served_models=self.accepted_served_models,
            messages=[
                {"role": "system", "content": _REGEN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )


@dataclass
class OpenAICompatibleJudge:
    provider: str
    base_url: str
    key_env_names: tuple[str, ...]
    model: str
    api_key: str | None = None
    max_tokens: int = JUDGE_MAX_TOKENS
    temperature: float = JUDGE_TEMPERATURE
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    accepted_served_models: tuple[str, ...] = ()

    def summarize(self, fixture_id: str, per_component_summary: str) -> str:
        prompt = build_judge_prompt(fixture_id, per_component_summary)
        return OpenAICompatibleClient(
            provider=self.provider,
            base_url=self.base_url,
            key_env_names=self.key_env_names,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        ).complete_chat(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            accepted_served_models=self.accepted_served_models,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )


class XAIWorker(OpenAICompatibleWorker):
    def __init__(
        self,
        model: str = XAI_MODEL,
        api_key: str | None = None,
        max_tokens: int = WORKER_MAX_TOKENS,
        temperature: float = WORKER_TEMPERATURE,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        accepted_served_models: tuple[str, ...] = (),
    ) -> None:
        config = PROVIDER_CONFIGS["xai"]
        super().__init__(
            provider=config.provider,
            base_url=config.base_url,
            key_env_names=config.key_env_names,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            accepted_served_models=accepted_served_models,
        )


class XAIJudge(OpenAICompatibleJudge):
    def __init__(
        self,
        model: str = XAI_MODEL,
        api_key: str | None = None,
        max_tokens: int = JUDGE_MAX_TOKENS,
        temperature: float = JUDGE_TEMPERATURE,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        accepted_served_models: tuple[str, ...] = (),
    ) -> None:
        config = PROVIDER_CONFIGS["xai"]
        super().__init__(
            provider=config.provider,
            base_url=config.base_url,
            key_env_names=config.key_env_names,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            accepted_served_models=accepted_served_models,
        )


def _generic_worker(
    config: ApiProviderConfig,
    model: str,
    api_key: str | None,
    timeout_seconds: int,
) -> OpenAICompatibleWorker:
    return OpenAICompatibleWorker(
        provider=config.provider,
        base_url=config.base_url,
        key_env_names=config.key_env_names,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def _generic_judge(
    config: ApiProviderConfig,
    model: str,
    api_key: str | None,
    timeout_seconds: int,
) -> OpenAICompatibleJudge:
    return OpenAICompatibleJudge(
        provider=config.provider,
        base_url=config.base_url,
        key_env_names=config.key_env_names,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


def build_api_models(
    provider: str,
    worker_model: str | None = None,
    judge_model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
):
    """Build API-backed Worker/Judge adapters for an OpenAI-compatible provider."""
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(f"unknown API provider: {provider}")
    config = PROVIDER_CONFIGS[provider]
    worker_name = worker_model or config.default_worker_model
    judge_name = judge_model or config.default_judge_model
    if provider == "xai":
        return (
            XAIWorker(
                model=worker_name,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            ),
            XAIJudge(
                model=judge_name,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            ),
        )
    return (
        _generic_worker(config, worker_name, api_key, timeout_seconds),
        _generic_judge(config, judge_name, api_key, timeout_seconds),
    )
