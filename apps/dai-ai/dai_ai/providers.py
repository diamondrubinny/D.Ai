# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""External AI providers with your own key (docs/PROVIDERS.md): off by default, one consent per provider.

Three request shapes cover them all: OpenAI-compatible chat completions (OpenAI, Mistral, Groq, DeepSeek,
xAI, OpenRouter, Ollama, LM Studio), Anthropic Messages, and Google Gemini generateContent. HTTPS only
(plain http only for a custom LAN server, with a warning). The key is never printed, logged or sent anywhere
but the provider.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterator

from .paths import config_file

TASKS = ("code", "general")
KINDS = ("openai", "anthropic", "gemini")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
TIMEOUT = 120
MAX_REPLY = 200_000
# Defaults that each provider's own documentation decides; model names change (docs/PROVIDERS.md §4).
KNOWN: dict[str, dict[str, str]] = {
    "anthropic": {"kind": "anthropic", "base_url": "https://api.anthropic.com/v1", "model": "claude-sonnet-5-5"},
    "openai": {"kind": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-5"},
    "google": {"kind": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "model": "gemini-2.5-flash"},
    "mistral": {"kind": "openai", "base_url": "https://api.mistral.ai/v1", "model": "mistral-large-latest"},
    "groq": {"kind": "openai", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "deepseek": {"kind": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "xai": {"kind": "openai", "base_url": "https://api.x.ai/v1", "model": "grok-4"},
    "openrouter": {"kind": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "anthropic/claude-sonnet-4.5"},
}
Opener = Callable[[urllib.request.Request, float], Any]


class ProviderError(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    kind: str
    base_url: str
    model: str
    key: str = ""
    tasks: tuple[str, ...] = ("code", "general")
    consented: str = ""          # the date "yes" was typed, "" until then

    def masked_key(self) -> str:
        key = self.key or os.environ.get(f"DAI_PROVIDER_KEY_{self.name.upper().replace('-', '_')}", "")
        if not key:
            return "(no key)"
        return key[:3] + "…" + key[-2:] if len(key) > 8 else "…"

    def resolved_key(self) -> str:
        return os.environ.get(f"DAI_PROVIDER_KEY_{self.name.upper().replace('-', '_')}", "") or self.key

    def public(self) -> dict[str, Any]:
        """For listing and status: never the key."""
        return {"name": self.name, "kind": self.kind, "base_url": self.base_url, "model": self.model,
                "tasks": list(self.tasks), "consented": self.consented, "key": self.masked_key()}


@dataclass
class Config:
    active: str = ""             # "" means local Diamond for everything
    fallback: bool = True        # back to local Diamond when the provider fails
    providers: dict[str, Provider] = field(default_factory=dict)

    def for_task(self, task: str) -> Provider | None:
        """The provider that serves this task, or None for local Diamond (always None under a forbidding policy)."""
        provider = self.providers.get(self.active)
        if provider is None or not provider.consented or task not in provider.tasks or policy_forbids():
            return None
        return provider


POLICY_AI_ENV = "/etc/dai/policy-ai.env"   # written by D.Ai Tune's ai.providers_policy (docs/PROVIDERS.md §4c)


def policy_forbids(root: Path | None = None) -> bool:
    """True when an organization policy forbids external providers on this computer."""
    path = (root or Path(os.environ.get("DAI_ROOT", "/"))) / POLICY_AI_ENV.lstrip("/")
    try:
        return any(line.strip() == "DAI_AI_PROVIDERS=forbidden" for line in path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return False


def config_path() -> Path:
    return config_file().with_name("providers.json")


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Config()
    if not isinstance(data, dict):
        return Config()
    config = Config(active=str(data.get("active") or ""), fallback=data.get("fallback", True) is not False)
    for name, raw in (data.get("providers") or {}).items():
        if not isinstance(raw, dict) or not NAME_RE.match(str(name)) or raw.get("kind") not in KINDS:
            continue
        tasks = tuple(t for t in raw.get("tasks", TASKS) if t in TASKS) or TASKS
        config.providers[name] = Provider(name, raw["kind"], str(raw.get("base_url", "")), str(raw.get("model", "")),
                                          str(raw.get("key", "")), tasks, str(raw.get("consented", "")))
    if config.active not in config.providers:
        config.active = ""
    return config


def save(config: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": 1, "active": config.active, "fallback": config.fallback,
            "providers": {name: {"kind": p.kind, "base_url": p.base_url, "model": p.model, "key": p.key,
                                 "tasks": list(p.tasks), "consented": p.consented} for name, p in config.providers.items()}}
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


def make(name: str, kind: str = "", base_url: str = "", model: str = "") -> Provider:
    """A provider from the known table or from explicit parts; validated."""
    if not NAME_RE.match(name):
        raise ProviderError("the name: lowercase letters, digits and dashes, up to 32")
    known = KNOWN.get(name, {})
    kind = kind or known.get("kind", "openai")
    base_url = (base_url or known.get("base_url", "")).rstrip("/")
    model = model or known.get("model", "")
    if kind not in KINDS:
        raise ProviderError(f"kind: one of {', '.join(KINDS)}")
    if not base_url or not model:
        raise ProviderError("a custom provider needs --url and --model")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise ProviderError("the URL must start with https:// (or http:// for a server on your own network)")
    if parsed.scheme == "http" and not _local_host(parsed.hostname):
        raise ProviderError("plain http is allowed only for a server on your own network")
    return Provider(name, kind, base_url, model)


def _local_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local") or host.endswith(".lan") \
        or re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", host) is not None


def consent_text(provider: Provider, lang: str) -> str:
    from dai_i18n import pick

    return pick(lang,
                "The text of your requests to Diamond (questions, code, app descriptions; not files, not passwords) "
                "will be sent to {name}'s servers ({url}) under that provider's terms and privacy policy. Speech stays "
                "on the computer. Back to the local Diamond at any time: dai-models provider use local.",
                "הטקסט של הבקשות ל־Diamond (שאלות, קוד, תיאורי אפליקציות; לא קבצים ולא סיסמאות) יישלח לשרתים של "
                "{name} ({url}) ויהיה כפוף לתנאים ולמדיניות הפרטיות של הספק. דיבור נשאר במחשב. אפשר לחזור "
                "ל־Diamond המקומי בכל רגע: dai-models provider use local.").format(name=provider.name, url=provider.base_url)


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


def _system_and_rest(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
    rest = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
    return system, rest


def build_request(provider: Provider, messages: list[dict[str, str]], schema: dict | None, max_tokens: int) -> tuple[str, dict, dict]:
    """(url, headers, body) for the provider's kind. A schema asks for JSON in the way each API offers."""
    key = provider.resolved_key()
    if not key:
        raise ProviderError(f"{provider.name}: no key (dai-models provider key {provider.name})")
    system, rest = _system_and_rest(messages)
    if schema:
        system = (system + "\n\n" if system else "") + "Answer with one JSON object only, matching this JSON schema: " + json.dumps(schema)
    if provider.kind == "anthropic":
        body: dict[str, Any] = {"model": provider.model, "max_tokens": max_tokens, "messages": rest or [{"role": "user", "content": ""}]}
        if system:
            body["system"] = system
        return (provider.base_url + "/messages",
                {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, body)
    if provider.kind == "gemini":
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in rest]
        body = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if schema:
            body["generationConfig"]["responseMimeType"] = "application/json"
        return (f"{provider.base_url}/models/{urllib.parse.quote(provider.model)}:generateContent",
                {"x-goog-api-key": key, "content-type": "application/json"}, body)
    body = {"model": provider.model, "max_tokens": max_tokens,
            "messages": ([{"role": "system", "content": system}] if system else []) + rest}
    if schema:
        body["response_format"] = {"type": "json_object"}
    return (provider.base_url + "/chat/completions",
            {"authorization": f"Bearer {key}", "content-type": "application/json"}, body)


def parse_reply(kind: str, data: Any) -> str:
    try:
        if kind == "anthropic":
            return "".join(part.get("text", "") for part in data["content"] if part.get("type") == "text")
        if kind == "gemini":
            return "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"unexpected answer from the provider ({exc.__class__.__name__})") from exc


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https or a LAN http chosen by the person


def stream_request(provider: Provider, messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict, dict]:
    """The same request, asking for the answer as server-sent events (docs/PROVIDERS.md §2b)."""
    url, headers, body = build_request(provider, messages, None, max_tokens)
    if provider.kind == "gemini":
        url = url.replace(":generateContent", ":streamGenerateContent?alt=sse")
    else:
        body["stream"] = True
    headers["accept"] = "text/event-stream"
    return url, headers, body


def parse_event(kind: str, data: Any) -> str:
    """The text one event carries ("" for events that carry none, such as usage or stop reasons)."""
    if not isinstance(data, dict):
        return ""
    try:
        if kind == "anthropic":
            delta = data.get("delta") or {}
            return delta.get("text", "") if data.get("type") == "content_block_delta" and delta.get("type") == "text_delta" else ""
        if kind == "gemini":
            candidates = data.get("candidates") or []
            parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
            return "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        choices = data.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        return delta.get("content") or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def _http_error(provider: Provider, exc: urllib.error.HTTPError) -> ProviderError:
    detail = ""
    try:
        detail = json.loads(exc.read().decode("utf-8", "replace")).get("error", {})
        detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    except Exception:  # noqa: BLE001 - the body is optional detail
        pass
    return ProviderError(f"{provider.name}: HTTP {exc.code}{': ' + detail[:200] if detail else ''}")


def stream(provider: Provider, messages: list[dict[str, str]], max_tokens: int = 512, opener: Opener = _open) -> Iterator[str]:
    """The answer as it arrives, piece by piece, from the provider's event stream (text only, no schema)."""
    url, headers, body = stream_request(provider, messages, max_tokens)
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    total = 0
    try:
        with opener(request, TIMEOUT) as response:
            for raw_line in response:
                total += len(raw_line)
                if total > MAX_REPLY:
                    raise ProviderError(f"{provider.name}: the answer is too large")
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and data.get("type") == "error":
                    raise ProviderError(f"{provider.name}: {str((data.get('error') or {}).get('message', 'error'))[:200]}")
                piece = parse_event(provider.kind, data)
                if piece:
                    yield piece
    except urllib.error.HTTPError as exc:
        raise _http_error(provider, exc) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProviderError(f"{provider.name}: {getattr(exc, 'reason', exc)}") from exc


def chat(provider: Provider, messages: list[dict[str, str]], schema: dict | None = None, max_tokens: int = 512,
         opener: Opener = _open) -> str:
    """One complete answer from the provider (what a JSON schema needs; plain text streams through stream())."""
    url, headers, body = build_request(provider, messages, schema, max_tokens)
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with opener(request, TIMEOUT) as response:
            raw = response.read(MAX_REPLY + 1)
    except urllib.error.HTTPError as exc:
        raise _http_error(provider, exc) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ProviderError(f"{provider.name}: {getattr(exc, 'reason', exc)}") from exc
    if len(raw) > MAX_REPLY:
        raise ProviderError(f"{provider.name}: the answer is too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider.name}: the answer is not JSON") from exc
    return parse_reply(provider.kind, data)


def where(config: Config | None = None) -> dict[str, str]:
    """Who serves each task: "local" or a provider name."""
    config = config or load()
    out = {}
    for task in TASKS:
        provider = config.for_task(task)
        out[task] = provider.name if provider else "local"
    out["speech"] = "local"
    return out


def record_consent(config: Config, name: str, today: date | None = None) -> None:
    config.providers[name].consented = (today or date.today()).isoformat()
    config.active = name
