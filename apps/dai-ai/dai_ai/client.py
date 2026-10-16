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
    return next(_request({"op": "status"}, timeout=5))


def chat(messages: list[dict[str, str]], schema: dict | None = None, max_tokens: int = 512) -> Iterator[str]:
    for message in _request({"op": "chat", "messages": messages, "schema": schema, "max_tokens": max_tokens}):
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
    """dai-ai "question"  |  dai-ai status"""
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print('usage: dai-ai "question"  |  dai-ai status  |  dai-ai --version')
        return 0
    if args[0] == "--version":
        print(f"dai-ai {__version__} — {__author__}")
        return 0
    try:
        if args[0] == "status":
            info = status()
            print(f"model: {info.get('model') or 'none (dai-models install qwen2.5-0.5b)'}  running: {info.get('running')}")
            return 0
        for delta in ask(" ".join(args)):
            sys.stdout.write(delta)
            sys.stdout.flush()
        print()
        return 0
    except AIUnavailable as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
