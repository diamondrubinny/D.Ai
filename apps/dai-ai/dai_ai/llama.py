# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Run llama-server on a UNIX socket and talk to it (stdlib HTTP only)."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Iterator

from .paths import LLAMA_DIR, runtime_dir


class LlamaError(RuntimeError):
    pass


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float = 300) -> None:
        super().__init__("localhost", timeout=timeout)
        self.unix_path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.unix_path)
        self.sock = sock


class LlamaServer:
    """Starts llama-server lazily for a model and stops it when idle."""

    def __init__(self, model: Path, idle_seconds: int = 600, threads: int | None = None) -> None:
        self.model = model
        self.idle_seconds = idle_seconds
        self.threads = threads or max(1, (os.cpu_count() or 2) // 2)
        self.socket_path = runtime_dir() / "llama.sock"
        self.process: subprocess.Popen | None = None
        self.last_used = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    def ensure_running(self, timeout: float = 180) -> None:
        self.last_used = time.monotonic()
        if self.process and self.process.poll() is None:
            return
        if not self.model.is_file():
            raise LlamaError(f"model not installed: {self.model.name} (run: dai-models install)")
        binary = LLAMA_DIR / "llama-server"
        if not binary.is_file():
            raise LlamaError(f"llama-server not found in {LLAMA_DIR}")
        if self.socket_path.exists():
            self.socket_path.unlink()
        env = {"PATH": "/usr/bin:/bin", "LD_LIBRARY_PATH": str(LLAMA_DIR), "HOME": str(Path.home())}
        self.process = subprocess.Popen(
            [
                str(binary),
                "-m", str(self.model),
                "--host", str(self.socket_path),
                "--no-webui",
                "-c", "8192",
                "-t", str(self.threads),
                "--parallel", "1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise LlamaError(f"llama-server exited with {self.process.returncode}")
            if self.socket_path.exists() and self._healthy():
                return
            time.sleep(0.5)
        self.stop()
        raise LlamaError("llama-server did not become ready in time")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def stop_if_idle(self) -> None:
        if self.process and time.monotonic() - self.last_used > self.idle_seconds:
            self.stop()

    # -- HTTP --------------------------------------------------------------

    def _healthy(self) -> bool:
        try:
            conn = UnixHTTPConnection(str(self.socket_path), timeout=2)
            conn.request("GET", "/health")
            ok = conn.getresponse().status == 200
            conn.close()
            return ok
        except OSError:
            return False

    def chat(self, messages: list[dict[str, str]], schema: dict | None = None, max_tokens: int = 512,
             temperature: float = 0.2) -> Iterator[str]:
        """Stream the assistant's reply as text deltas."""
        self.ensure_running()
        body: dict[str, Any] = {
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "schema": schema}
        conn = UnixHTTPConnection(str(self.socket_path))
        conn.request("POST", "/v1/chat/completions", body=json.dumps(body), headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise LlamaError(f"llama-server returned HTTP {response.status}")
        try:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                delta = event.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    self.last_used = time.monotonic()
                    yield delta
        finally:
            conn.close()
            self.last_used = time.monotonic()
