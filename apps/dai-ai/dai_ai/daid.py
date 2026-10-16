# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""daid: the per-user local AI service.

Listens on $XDG_RUNTIME_DIR/dai/daid.sock (systemd socket activation, or its
own socket when started by hand). Protocol: one JSON request per connection,
newline-terminated; replies are JSON lines.

  {"op": "status"}                                   -> {"ok": true, "model": ..., "running": ...}
  {"op": "chat", "messages": [...], "schema": {...}?} -> {"delta": "..."}* then {"done": true}

Nothing is written to disk; requests are not logged.
"""

from __future__ import annotations

import json
import os
import socket
import socketserver
import sys
import threading
from typing import Any

from .llama import LlamaError, LlamaServer
from .models import ModelError, default_model_id, load_catalog
from .paths import daid_socket

MAX_REQUEST = 256 * 1024
MAX_MESSAGES = 32
MAX_TOKENS = 2048


class Backend:
    """Holds the llama-server for the default model; one request at a time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.server: LlamaServer | None = None

    def _server(self) -> LlamaServer:
        models = load_catalog()
        model_id = default_model_id(models)
        if model_id is None:
            raise ModelError("no model installed (run: dai-models install qwen2.5-0.5b)")
        model = models[model_id]
        if self.server is None or self.server.model != model.path:
            if self.server:
                self.server.stop()
            self.server = LlamaServer(model.path)
        return self.server

    def status(self) -> dict[str, Any]:
        try:
            models = load_catalog()
            model_id = default_model_id(models)
        except (OSError, ModelError, ValueError):
            model_id = None
        running = bool(self.server and self.server.process and self.server.process.poll() is None)
        return {"ok": True, "model": model_id, "running": running}

    def chat(self, messages: list[dict[str, str]], schema: dict | None, max_tokens: int):
        with self.lock:
            yield from self._server().chat(messages, schema=schema, max_tokens=max_tokens,
                                           temperature=0.0 if schema else 0.3)

    def reap(self) -> None:
        if self.server and self.lock.acquire(blocking=False):
            try:
                self.server.stop_if_idle()
            finally:
                self.lock.release()


def validate_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or request.get("op") not in ("status", "chat"):
        raise ValueError("unknown request")
    if request["op"] == "chat":
        messages = request.get("messages")
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= MAX_MESSAGES
            or not all(
                isinstance(m, dict) and m.get("role") in ("system", "user", "assistant") and isinstance(m.get("content"), str)
                for m in messages
            )
        ):
            raise ValueError("invalid messages")
        schema = request.get("schema")
        if schema is not None and not isinstance(schema, dict):
            raise ValueError("invalid schema")
        max_tokens = request.get("max_tokens", 512)
        if not isinstance(max_tokens, int) or not 1 <= max_tokens <= MAX_TOKENS:
            raise ValueError("invalid max_tokens")
        return {"op": "chat", "messages": messages, "schema": schema, "max_tokens": max_tokens}
    return {"op": "status"}


class Handler(socketserver.StreamRequestHandler):
    backend: Backend

    def send(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def handle(self) -> None:
        try:
            line = self.rfile.readline(MAX_REQUEST + 1)
            if len(line) > MAX_REQUEST:
                raise ValueError("request too large")
            request = validate_request(json.loads(line))
            if request["op"] == "status":
                self.send(self.backend.status())
                return
            for delta in self.backend.chat(request["messages"], request["schema"], request["max_tokens"]):
                self.send({"delta": delta})
            self.send({"done": True})
        except (ValueError, json.JSONDecodeError, ModelError, LlamaError, OSError) as exc:
            try:
                self.send({"error": str(exc)})
            except OSError:
                pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, listener: socket.socket | None, backend: Backend) -> None:
        Handler.backend = backend
        if listener is None:
            path = daid_socket()
            if path.exists():
                path.unlink()
            super().__init__(str(path), Handler)
            os.chmod(path, 0o600)
        else:  # systemd socket activation
            super().__init__(str(daid_socket()), Handler, bind_and_activate=False)
            self.socket = listener


def _activated_socket() -> socket.socket | None:
    if os.environ.get("LISTEN_PID") == str(os.getpid()) and int(os.environ.get("LISTEN_FDS", "0")) >= 1:
        return socket.socket(fileno=3)
    return None


def main(argv: list[str]) -> int:
    backend = Backend()
    server = Server(_activated_socket(), backend)

    def reaper() -> None:
        while True:
            threading.Event().wait(60)
            backend.reap()

    threading.Thread(target=reaper, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if backend.server:
            backend.server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
