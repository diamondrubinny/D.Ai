# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Living Diamond's state (docs/TASKBAR.md §2.1): one small file the panel watches.

  $XDG_RUNTIME_DIR/dai/status.json   {"heal": 1, "privacy": ["Zoom"], "ideas": 2}

Written by the services that already run (D.Ai Heal, Privacy, Evolve), read by
the panel plugin with inotify, never polled. Counters and app names only:
no content, questions or file names. In memory (tmpfs), 0600, gone at logout.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from pathlib import Path

__version__ = "0.1.0"
__author__ = "Diamond Rubinny (d.Ai)"

MAX_COUNT = 99
MAX_APPS = 3
MAX_NAME = 40
CONTROL = re.compile(r"[\x00-\x1f\x7f‎‏‪-‮⁦-⁩]")


def directory() -> Path | None:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "dai" if runtime else None


def _clean(section: str, value: object) -> object:
    if section in ("heal", "ideas"):
        return max(0, min(MAX_COUNT, int(value)))  # type: ignore[call-overload]
    if section == "privacy":
        names = [CONTROL.sub("", str(name)).strip()[:MAX_NAME] for name in value]  # type: ignore[union-attr]
        return sorted({name for name in names if name})[:MAX_APPS]
    raise ValueError(f"unknown status section: {section}")


def read() -> dict:
    folder = directory()
    try:
        data = json.loads((folder / "status.json").read_text(encoding="utf-8")) if folder else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update(section: str, value: object) -> bool:
    """Set one section; returns whether the file changed. Never raises: the panel is only a mirror."""
    folder = directory()
    if folder is None:
        return False
    try:
        clean = _clean(section, value)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(folder / "status.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # several writers (Heal, Privacy, Evolve)
            data = read()
            if data.get(section) == clean:
                return False
            data[section] = clean
            tmp = folder / ".status.json.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, folder / "status.json")
            return True
    except (OSError, TypeError, ValueError):
        return False
