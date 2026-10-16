"""dai-tune-helper: the only part of D.Ai Tune that runs as root.

Started through polkit (pkexec) by the dai-tune CLI. It trusts nothing from
the caller: every step is rebuilt from the catalog and validated again, only
system-scope actions are accepted, and every change is journaled for undo.

  dai-tune-helper apply        < plan.json   -> {"ok": true, "id": "..."}
  dai-tune-helper undo <id>                  -> {"ok": true}
"""

from __future__ import annotations

import json
import os
import re
import sys
import syslog
from pathlib import Path

from .catalog import ValidationError
from .context import ActionError, Context
from .executor import ApplyError, Journal, apply_steps, undo_entry
from .planner import steps_from_json

MAX_INPUT = 64 * 1024
ENTRY_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def _reply(ok: bool, **fields) -> int:
    print(json.dumps({"ok": ok, **fields}, ensure_ascii=False))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        return _reply(False, error="dai-tune-helper must run as root (via pkexec)")
    actor = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID") or "0"
    ctx = Context(root=Path("/"), home=Path("/root"), lang="en")
    journal = Journal.for_system(ctx)
    syslog.openlog("dai-tune-helper", syslog.LOG_PID, syslog.LOG_AUTH)

    command = argv[1] if len(argv) > 1 else ""
    try:
        if command == "apply":
            raw = sys.stdin.read(MAX_INPUT + 1)
            if len(raw) > MAX_INPUT:
                raise ValidationError("plan too large")
            steps = steps_from_json(json.loads(raw), ctx, scope="system")
            entry = apply_steps(steps, ctx, journal, actor=actor, scope="system")
            syslog.syslog(syslog.LOG_NOTICE, f"uid={actor} applied {entry['id']}: {[s.action for s in steps]}")
            return _reply(True, id=entry["id"])
        if command == "undo" and len(argv) == 3 and ENTRY_ID.match(argv[2]):
            entry = journal.find(argv[2])
            if entry is None:
                raise ValidationError("no such applied change")
            undo_entry(entry, ctx, journal)
            syslog.syslog(syslog.LOG_NOTICE, f"uid={actor} undid {argv[2]}")
            return _reply(True)
        raise ValidationError("usage: dai-tune-helper apply < plan.json | undo <id>")
    except (ValidationError, ApplyError, ActionError, json.JSONDecodeError) as exc:
        syslog.syslog(syslog.LOG_WARNING, f"uid={actor} rejected/failed {command}: {exc}")
        return _reply(False, error=str(exc))
