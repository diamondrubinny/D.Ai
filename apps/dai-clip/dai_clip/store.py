# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The history, in memory only: $XDG_RUNTIME_DIR is a per-user tmpfs that
logind removes at logout. Without it nothing is kept (no disk fallback).

Every copy runs a separate `dai-clip _store`, so writes are atomic and
serialized with flock.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAX_ITEMS = 30
MAX_CHARS = 100_000
KEEP_SECONDS = 12 * 3600
MAX_FILE_BYTES = 4 * 1024 * 1024
HISTORY = "history.json"
PAUSE = "paused-until"


@dataclass(frozen=True)
class Item:
    text: str
    time: float


def runtime_dir(env: dict | None = None) -> Path | None:
    """The private history folder, or None when it cannot be trusted."""
    base = (os.environ if env is None else env).get("XDG_RUNTIME_DIR")
    if not base:
        return None
    folder = Path(base) / "dai-clip"
    try:
        folder.mkdir(mode=0o700, exist_ok=True)
        info = os.lstat(folder)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return None
        if info.st_mode & 0o077:
            os.chmod(folder, 0o700)
    except OSError:
        return None
    return folder


def config_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".config")
    return Path(base) / "dai"


def _read(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return b""
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
            return b""
        return handle.read(MAX_FILE_BYTES + 1)


def _write(path: Path, data: bytes) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    try:
        temp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.replace(temp, path)


class History:
    def __init__(self, folder: Path, clock=time.time) -> None:
        self.folder = folder
        self.path = folder / HISTORY
        self.clock = clock

    @contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self.folder / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self) -> list[Item]:
        try:
            raw = json.loads(_read(self.path) or b"[]")
        except (ValueError, UnicodeDecodeError):
            return []  # damaged: start again
        if not isinstance(raw, list):
            return []
        cutoff = self.clock() - KEEP_SECONDS
        items = []
        for entry in raw:
            if (isinstance(entry, dict) and isinstance(entry.get("text"), str) and isinstance(entry.get("time"), (int, float))
                    and entry["time"] >= cutoff and 0 < len(entry["text"]) <= MAX_CHARS):
                items.append(Item(entry["text"], float(entry["time"])))
        return items[:MAX_ITEMS]

    def _save(self, items: list[Item]) -> None:
        _write(self.path, json.dumps([item.__dict__ for item in items[:MAX_ITEMS]], ensure_ascii=False).encode())

    def items(self) -> list[Item]:
        """Newest first."""
        with self._locked():
            return self._load()

    def add(self, text: str) -> bool:
        if not text.strip() or len(text) > MAX_CHARS:
            return False
        with self._locked():
            items = [item for item in self._load() if item.text != text]
            self._save([Item(text, self.clock()), *items])
        return True

    def remove(self, text: str) -> None:
        with self._locked():
            self._save([item for item in self._load() if item.text != text])

    def clear(self) -> None:
        with self._locked():
            self._save([])

    # -- pause ---------------------------------------------------------------

    def pause(self, minutes: float) -> float:
        until = self.clock() + minutes * 60
        _write(self.folder / PAUSE, f"{until:.0f}".encode())
        return until

    def resume(self) -> None:
        try:
            (self.folder / PAUSE).unlink()
        except FileNotFoundError:
            pass

    def paused_until(self) -> float | None:
        try:
            until = float(_read(self.folder / PAUSE).decode() or 0)
        except (ValueError, UnicodeDecodeError):
            return None
        return until if until > self.clock() else None


def is_off(env: dict | None = None) -> bool:
    return (config_dir(env) / "clip-off").exists()


def set_off(off: bool, env: dict | None = None) -> None:
    marker = config_dir(env) / "clip-off"
    if off:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("D.Ai Clip is off (dai-clip on turns it back on).\n")
    else:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
