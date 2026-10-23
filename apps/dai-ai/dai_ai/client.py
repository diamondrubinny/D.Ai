# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Client for daid, used by dai-ai, D.Ai Command and D.Ai Tune."""

from __future__ import annotations

import json
import socket
import sys
from typing import Any, Iterator

from . import __author__, __version__
from .paths import daid_socket


class AIUnavailable(RuntimeError):
    pass


def _request(payload: dict[str, Any], timeout: float = 600) -> Iterator[dict[str, Any]]:
    path = daid_socket()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(path))
    except OSError as exc:
        sock.close()
        raise AIUnavailable(f"D.Ai AI service is not running ({exc})") from exc
    with sock, sock.makefile("rwb") as stream:
        stream.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        stream.flush()
        for line in stream:
            message = json.loads(line)
            if "error" in message:
                raise AIUnavailable(message["error"])
            yield message


def status() -> dict[str, Any]:
    """daid's status plus who serves each task (docs/PROVIDERS.md §2.5)."""
    from . import providers

    info = next(_request({"op": "status"}, timeout=5))
    info["where"] = providers.where()
    return info


def where(task: str = "general") -> str:
    """"local", or the provider's name, for this task; what a window shows next to an answer."""
    from . import providers

    return providers.where().get(task, "local")


def chat(
    messages: list[dict[str, str]], schema: dict | None = None, max_tokens: int = 512, task: str = "general"
) -> Iterator[str]:
    """An answer, as pieces of text: from the provider chosen for this task, else from the local Diamond."""
    from . import providers

    config = providers.load()
    provider = config.for_task(task)
    if provider is not None:
        started = False
        try:
            if schema:
                yield providers.chat(provider, messages, schema, max_tokens)
            else:
                for piece in providers.stream(provider, messages, max_tokens):
                    started = True
                    yield piece
            return
        except providers.ProviderError as exc:
            if started or not config.fallback:     # a half-shown answer cannot be swapped for another one
                raise AIUnavailable(str(exc)) from exc
            print(f"dai-ai: {exc}; answering with the local Diamond instead", file=sys.stderr)
    payload = {"op": "chat", "messages": messages, "schema": schema, "max_tokens": max_tokens, "task": task}
    for message in _request(payload):
        if message.get("done"):
            return
        if "delta" in message:
            yield message["delta"]


def ask(question: str, max_tokens: int = 512) -> Iterator[str]:
    system = (
        "You are D.Ai, the built-in assistant of D.Ai OS (Debian based, LXQt on labwc). "
        "Answer briefly and accurately. Reply in the language of the question (Hebrew or English). "
        "When suggesting commands, explain what they do; never claim you ran anything."
    )
    return chat([{"role": "system", "content": system}, {"role": "user", "content": question}], max_tokens=max_tokens)


def main(argv: list[str]) -> int:
    """dai-ai "question"  |  dai-ai status  |  dai-ai where"""
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print('usage: dai-ai "question"  |  dai-ai status  |  dai-ai where  |  dai-ai --version')
        return 0
    if args[0] == "where":
        from . import providers

        for task, who in providers.where().items():
            print(f"{task:8} {who}")
        return 0
    if args[0] == "--version":
        print(f"dai-ai {__version__} — {__author__}")
        return 0
    try:
        if args[0] == "status":
            info = status()
            served = info.get("where", {})
            remote = sorted({who for who in served.values() if who != "local"})
            print(f"model: {info.get('model') or 'none (dai-models install qwen2.5-0.5b)'}  running: {info.get('running')}"
                  f"  provider: {', '.join(remote) if remote else 'local'}")
            return 0
        for delta in ask(" ".join(args)):
            sys.stdout.write(delta)
            sys.stdout.flush()
        print()
        return 0
    except AIUnavailable as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
