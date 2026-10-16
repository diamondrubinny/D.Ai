"""Transactional execution with snapshots, journal and undo."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

from .catalog import CATALOG
from .context import ActionError, Context, write_file
from .planner import Step, plan_hash

MAX_SNAPSHOT_BYTES = 512 * 1024
MAX_JOURNAL_ENTRIES = 100


class ApplyError(RuntimeError):
    """A step failed; everything applied before it was rolled back."""


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def for_user(ctx: Context) -> "Journal":
        return Journal(ctx.user_path(".local/state/dai/tune/journal.json"))

    @staticmethod
    def for_system(ctx: Context) -> "Journal":
        return Journal(ctx.path("/var/lib/dai/tune/journal.json"))

    def entries(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        write_file(self.path, json.dumps(entries[-MAX_JOURNAL_ENTRIES:], ensure_ascii=False, indent=1), mode=0o600)

    def append(self, entry: dict[str, Any]) -> None:
        self._save(self.entries() + [entry])

    def set_status(self, entry_id: str, status: str) -> None:
        entries = self.entries()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry["status"] = status
                entry["status_time"] = _now()
        self._save(entries)

    def find(self, entry_id: str = "last") -> dict[str, Any] | None:
        applied = [e for e in self.entries() if e.get("status") == "applied"]
        if entry_id == "last":
            return applied[-1] if applied else None
        return next((e for e in applied if e.get("id") == entry_id), None)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------


def snapshot(paths: Iterable[Path]) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for path in paths:
        if path.is_file():
            data = path.read_bytes()
            if len(data) > MAX_SNAPSHOT_BYTES:
                raise ActionError(f"{path} is too large to snapshot safely")
            snap[str(path)] = base64.b64encode(data).decode("ascii")
        else:
            snap[str(path)] = None
    return snap


def restore_files(snap: dict[str, str | None]) -> None:
    for name, encoded in snap.items():
        path = Path(name)
        if encoded is None:
            if path.exists():
                path.unlink()
        else:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            write_file(path, base64.b64decode(encoded), mode=mode)


# --------------------------------------------------------------------------
# Apply / undo
# --------------------------------------------------------------------------


def _undo_step(step: dict[str, Any], ctx: Context) -> None:
    spec = CATALOG[step["action"]]
    restore_files(step["before"]["files"])
    spec.restore(step["params"], ctx, step["before"]["extra"])


def apply_steps(
    steps: list[Step],
    ctx: Context,
    journal: Journal,
    actor: str,
    scope: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply steps in order; on failure undo the completed ones and raise."""
    done: list[dict[str, Any]] = []
    for step in steps:
        spec = CATALOG[step.action]
        record = {
            "action": step.action,
            "params": step.params,
            "before": {
                "files": snapshot(spec.files(step.params, ctx)),
                "extra": spec.capture(step.params, ctx),
            },
        }
        try:
            spec.apply(step.params, ctx)
        except Exception as exc:  # roll back this step and all earlier ones
            failures = []
            for undo in [record, *reversed(done)]:
                try:
                    _undo_step(undo, ctx)
                except Exception as undo_exc:  # keep going; report at the end
                    failures.append(f"{undo['action']}: {undo_exc}")
            detail = f"; rollback problems: {'; '.join(failures)}" if failures else "; all changes were rolled back"
            raise ApplyError(f"{step.action} failed: {exc}{detail}") from exc
        done.append(record)

    entry = {
        "id": time.strftime("%Y%m%d-%H%M%S-") + plan_hash(steps)[:6],
        "time": _now(),
        "actor": actor,
        "scope": scope,
        "hash": plan_hash(steps),
        "steps": done,
        "status": "applied",
        **(extra or {}),
    }
    journal.append(entry)
    return entry


def undo_entry(entry: dict[str, Any], ctx: Context, journal: Journal) -> None:
    for step in reversed(entry["steps"]):
        _undo_step(step, ctx)
    journal.set_status(entry["id"], "undone")
