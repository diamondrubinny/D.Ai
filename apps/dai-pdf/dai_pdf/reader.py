# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The window's side of the sandbox (docs/PDF.md §3): starts the helper, talks to it, and keeps the document's
facts. The helper does the parsing; this module only reads JSON and PNG bytes from it, with a deadline on
every request. A helper that died (a crash on a bad page, the time limit) is started again on the next request.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import sandbox
from .findings import Findings
from .text import readable

OPEN_TIMEOUT = 60.0     # seconds: parsing a large file, and the findings scan
RENDER_TIMEOUT = 40.0   # a page at high zoom under emulation
MAX_BODY = 400 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024 * 1024


class PdfError(Exception):
    """kind: "missing", "password", "broken", "sandbox", "dead", "timeout", "page"."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(kind if not detail else f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


@dataclass
class Document:
    path: str
    pages: list[tuple[float, float]]            # (width, height) in points
    labels: list[str]
    metadata: dict
    outline: list[dict]                          # {"title", "page", "level"}
    findings: Findings
    inspected: bool = True                       # False when pikepdf could not look at the file
    signatures: list[dict] = field(default_factory=list)   # signatures.py: signer, date, status, covers_all
    texts: dict[int, str] = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.pages)

    @property
    def title(self) -> str:
        return (self.metadata.get("title") or "").strip() or Path(self.path).name


class Reader:
    """One open PDF: a helper process (sandboxed unless told otherwise, for tests) and its answers."""

    def __init__(self, path: str, password: str = "", sandboxed: bool = True,
                 python: str = "/usr/bin/python3", binds: tuple[str, ...] = ()) -> None:
        self.path = str(Path(path))
        self.password = password
        self.sandboxed = sandboxed
        self.python, self.binds = python, binds
        self.proc: subprocess.Popen | None = None
        self.document: Document | None = None
        self.restarts = 0

    # --- the process -------------------------------------------------------------------------------------------

    def _argv(self) -> list[str]:
        if self.sandboxed:
            if not sandbox.available():
                raise PdfError("sandbox", "bubblewrap is missing: a PDF is never opened outside the sandbox")
            return sandbox.argv(self.path, self.python, self.binds)
        return sandbox.direct_argv(self.path, self.python)

    def _start(self) -> None:
        if not Path(self.path).is_file():
            raise PdfError("missing", self.path)
        if Path(self.path).stat().st_size > MAX_FILE:
            raise PdfError("broken", "larger than 2 GB")
        env = None
        if not self.sandboxed:  # the sandbox sets its own clean environment; the direct helper needs this one
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        self.proc = subprocess.Popen(self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, close_fds=True, env=env)

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _ensure(self) -> None:
        if self._alive():
            return
        if self.proc is not None:
            self.close()  # a helper that ended on its own: its pipes go too
            self.restarts += 1
        self._start()
        if self.document is not None:  # re-open after a crash, so the next request works
            answer, _ = self._request({"op": "open", "password": self.password}, OPEN_TIMEOUT)
            if not answer.get("ok"):
                raise PdfError(answer.get("error", "broken"), answer.get("detail", ""))

    # --- the wire ----------------------------------------------------------------------------------------------

    def _read(self, size: int, deadline: float) -> bytes:
        assert self.proc is not None and self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        out = bytearray()
        while len(out) < size:
            left = deadline - time.monotonic()
            if left <= 0:
                raise PdfError("timeout")
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                if not self._alive():
                    raise PdfError("dead")
                continue
            chunk = os.read(fd, min(65536, size - len(out)))
            if not chunk:
                raise PdfError("dead")
            out += chunk
        return bytes(out)

    def _read_line(self, deadline: float) -> bytes:
        assert self.proc is not None and self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        out = bytearray()
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise PdfError("timeout")
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                if not self._alive():
                    raise PdfError("dead")
                continue
            byte = os.read(fd, 1)
            if not byte:
                raise PdfError("dead")
            if byte == b"\n":
                return bytes(out)
            out += byte
            if len(out) > 64 * 1024 * 1024:
                raise PdfError("broken", "answer too long")

    def _request(self, request: dict, timeout: float) -> tuple[dict, bytes]:
        assert self.proc is not None and self.proc.stdin is not None
        deadline = time.monotonic() + timeout
        try:
            self.proc.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise PdfError("dead") from exc
        try:
            head = json.loads(self._read_line(deadline).decode("utf-8"))
        except ValueError as exc:
            raise PdfError("broken", "bad answer") from exc
        body = b""
        size = int(head.get("bytes", 0) or 0)
        if size:
            if size > MAX_BODY:
                self.close()
                raise PdfError("broken", "answer too large")
            body = self._read(size, deadline)
        return head, body

    def _ask(self, request: dict, timeout: float) -> tuple[dict, bytes]:
        """One request. A helper that died or hung is started again; the request is asked once more, except a
        drawing: a page that killed the helper (the memory or time limit) is reported as undrawable, not
        asked for again and again."""
        self._ensure()
        try:
            return self._request(request, timeout)
        except PdfError as exc:
            if exc.kind not in ("dead", "timeout"):
                raise
            self.close()
            self.restarts += 1
            if self.restarts > 3:
                raise
            self._start()
            if self.document is not None:
                answer, _ = self._request({"op": "open", "password": self.password}, OPEN_TIMEOUT)
                if not answer.get("ok"):
                    raise PdfError(answer.get("error", "broken"))
            if request.get("op") == "render":
                raise PdfError("page", "the helper stopped while drawing it") from exc
            return self._request(request, timeout)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 - nothing useful to do while being collected
            pass

    # --- what the window asks ----------------------------------------------------------------------------------

    def open(self) -> Document:
        self._ensure()
        answer, _ = self._request({"op": "open", "password": self.password}, OPEN_TIMEOUT)
        if not answer.get("ok"):
            raise PdfError(answer.get("error", "broken"), answer.get("detail", ""))
        raw = answer.get("findings") or {}
        self.document = Document(
            path=self.path,
            pages=[(float(w), float(h)) for w, h in answer.get("pages", [])],
            labels=[str(x) for x in answer.get("labels", [])],
            metadata=dict(answer.get("metadata") or {}),
            outline=[dict(x) for x in answer.get("outline", [])],
            findings=Findings.from_dict(raw),
            inspected=not raw.get("unknown", False),
            signatures=[dict(x) for x in answer.get("signatures", [])],
        )
        return self.document

    def render(self, page: int, width: int, height: int) -> tuple[bytes, int, int]:
        """PNG bytes of the page drawn at this size in pixels."""
        head, body = self._ask({"op": "render", "page": page, "width": width, "height": height}, RENDER_TIMEOUT)
        if not head.get("ok") or not body:
            raise PdfError("page", head.get("error", ""))
        return body, int(head.get("width", width)), int(head.get("height", height))

    def text(self, page: int, as_extracted: bool = False) -> str:
        assert self.document is not None
        if page not in self.document.texts:
            head, _ = self._ask({"op": "text", "page": page}, RENDER_TIMEOUT)
            if not head.get("ok"):
                raise PdfError("page", head.get("error", ""))
            self.document.texts[page] = str(head.get("text", ""))
        raw = self.document.texts[page]
        return raw if as_extracted else readable(raw)

    def select(self, page: int, start: int, length: int) -> list[tuple[float, float, float, float]]:
        head, _ = self._ask({"op": "select", "page": page, "start": start, "length": length}, RENDER_TIMEOUT)
        if not head.get("ok"):
            return []
        return [tuple(float(v) for v in rect) for rect in head.get("rects", [])]

    def links(self, page: int) -> list[dict]:
        head, _ = self._ask({"op": "links", "page": page}, RENDER_TIMEOUT)
        if not head.get("ok"):
            return []
        return [dict(link) for link in head.get("links", [])]

    def close(self) -> None:
        if self.proc is None:
            return
        proc, self.proc = self.proc, None
        try:
            if proc.poll() is None and proc.stdin is not None:
                proc.stdin.write(b'{"op": "close"}\n')
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def __enter__(self) -> "Reader":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
