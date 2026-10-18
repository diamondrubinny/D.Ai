# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Local signals for D.Ai Evolve: 0600 files under ~/.local/state/dai/evolve, kept 30 days.

Written by D.Ai Command and D.Ai Forge (record_wish, count_command), read by
the scanner. "dai-evolve off" stops all of it and deletes what was kept.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

KEEP_SECONDS = 30 * 86400
MAX_WISHES = 300
MAX_TEXT = 200
# Never kept: a password typed into the wrong field, a token, a key.
SECRETISH = re.compile(r"(passw|token|secret|bearer|api[_-]?key|authorization|-----BEGIN|\b(?=\S*\d)(?=\S*[A-Za-z])\S{16,})",
                       re.IGNORECASE)


def looks_private(text: str) -> bool:
    return bool(SECRETISH.search(text))


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "dai" / "evolve"


def off_marker() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "dai" / "evolve-off"


def is_off() -> bool:
    return off_marker().exists()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def read_json(name: str, default):
    try:
        return json.loads((state_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(name: str, data) -> None:
    _write(state_dir() / name, json.dumps(data, ensure_ascii=False))


def record_wish(text: str, source: str = "command", reason: str = "", clock=time.time) -> None:
    """Something the user asked for and did not get."""
    text = " ".join(text.split())[:MAX_TEXT]
    if is_off() or len(text) < 3 or len(text.split()) < 2 or looks_private(text):
        return
    now = clock()
    wishes = [w for w in wishes_list(now) if isinstance(w, dict)]
    wishes.append({"text": text, "source": source, "reason": reason[:80], "time": now})
    _write(state_dir() / "wishes.jsonl", "".join(json.dumps(w, ensure_ascii=False) + "\n" for w in wishes[-MAX_WISHES:]))


def wishes_list(now: float | None = None) -> list[dict]:
    now = now or time.time()
    try:
        lines = (state_dir() / "wishes.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            wish = json.loads(line)
        except ValueError:
            continue
        if isinstance(wish, dict) and isinstance(wish.get("text"), str) and now - float(wish.get("time", 0)) < KEEP_SECONDS:
            out.append(wish)
    return out


def forget_wishes(match) -> None:
    kept = [w for w in wishes_list() if not match(w["text"])]
    _write(state_dir() / "wishes.jsonl", "".join(json.dumps(w, ensure_ascii=False) + "\n" for w in kept))


def count_command(entry: str, clock=time.time) -> None:
    """How often a terminal command was run from D.Ai Command (the history itself keeps no counts)."""
    if is_off() or not entry.startswith((">", "$")) or len(entry) > MAX_TEXT or looks_private(entry):
        return
    counts = read_json("commands.json", {})
    counts = counts if isinstance(counts, dict) else {}
    row = counts.get(entry) if isinstance(counts.get(entry), dict) else {"count": 0}
    counts[entry] = {"count": int(row.get("count", 0)) + 1, "last": clock()}
    if len(counts) > 200:  # keep the most recent
        counts = dict(sorted(counts.items(), key=lambda kv: kv[1].get("last", 0))[-200:])
    write_json("commands.json", counts)


def forget_all() -> None:
    for name in ("wishes.jsonl", "commands.json", "suggestions.json", "dismissed.json", "notified.json"):
        (state_dir() / name).unlink(missing_ok=True)
