# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diffs, backups, atomic writes and undo for AI-proposed edits."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path


def state_dir(root: Path) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    path = base / "dai" / "code" / key
    path.mkdir(parents=True, exist_ok=True)
    for parent in (path, path.parent, path.parent.parent):
        try:
            os.chmod(parent, 0o700)
        except OSError:
            pass
    return path


def unified(rel: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))


def _journal(root: Path) -> Path:
    return state_dir(root) / "journal.json"


def entries(root: Path) -> list[dict]:
    try:
        data = json.loads(_journal(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(root: Path, items: list[dict]) -> None:
    path = _journal(root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def write_atomic(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    tmp = path.with_name(f".{path.name}.dai-code.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(path)


def apply(root: Path, path: Path, new_text: str, summary: str, instruction: str) -> dict:
    """Back up the current file, write the new one, journal it."""
    rel = str(path.relative_to(root))
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000:06d}"
    backup = None
    if path.exists():
        backup = state_dir(root) / "backups" / stamp / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, new_text)
    entry = {"id": stamp, "file": rel, "backup": str(backup) if backup else None, "summary": summary,
             "instruction": instruction[:300], "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": "applied",
             "after_sha256": hashlib.sha256(new_text.encode()).hexdigest()}
    _save(root, entries(root) + [entry])
    return entry


def undo(root: Path, entry_id: str = "last", force: bool = False) -> dict:
    items = entries(root)
    applied = [e for e in items if e.get("status") == "applied"]
    entry = applied[-1] if entry_id == "last" and applied else next((e for e in applied if e["id"] == entry_id), None)
    if entry is None:
        raise ValueError("nothing to undo")
    path = (root / entry["file"]).resolve()
    if root not in path.parents:
        raise ValueError("journal points outside the project")
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if not force and hashlib.sha256(current.encode()).hexdigest() != entry.get("after_sha256"):
        raise ValueError(f"{entry['file']} changed since the edit; use --force to restore the backup anyway")
    if entry.get("backup"):
        write_atomic(path, Path(entry["backup"]).read_text(encoding="utf-8"))
    elif path.exists():
        path.unlink()
    for item in items:
        if item["id"] == entry["id"]:
            item["status"] = "undone"
    _save(root, items)
    return entry
