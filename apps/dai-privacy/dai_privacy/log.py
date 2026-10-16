# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The local privacy log: who used the microphone or camera, and when.

JSON Lines in ~/.local/state/dai/privacy.log (0600). Entries older than
30 days are removed on every write. It never leaves the computer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .sensors import Use

KEEP_DAYS = 30


def log_path(home: Path | None = None) -> Path:
    base = os.environ.get("XDG_STATE_HOME") if home is None else None
    root = Path(base) if base else (home or Path.home()) / ".local" / "state"
    return root / "dai" / "privacy.log"


def changes(before: set[Use], after: set[Use]) -> list[tuple[str, Use]]:
    """("start", use) / ("stop", use) for what changed between two checks."""
    return [("start", u) for u in sorted(after - before)] + [("stop", u) for u in sorted(before - after)]


def read(path: Path, days: float = KEEP_DAYS, now: float | None = None) -> list[dict]:
    now = now or time.time()
    entries = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return entries
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and now - float(entry.get("time", 0)) <= days * 86400:
            entries.append(entry)
    return entries


def append(path: Path, events: list[tuple[str, Use]], now: float | None = None) -> None:
    if not events:
        return
    now = now or time.time()
    kept = read(path, KEEP_DAYS, now)
    kept += [{"time": round(now, 1), "event": kind, "device": use.device, "app": use.app, "pid": use.pid}
             for kind, use in events]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(entry, ensure_ascii=False) + "\n" for entry in kept)
    os.replace(tmp, path)
