# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-oem-helper: finishes the setup as root for the first-boot wizard.

Started with pkexec by the wizard. The polkit rule lets only the local,
active dai-setup session do this without a password; this helper checks
the caller and the state again and validates every field itself.

  dai-oem-helper complete < owner.json   -> {"ok": true}
  dai-oem-helper reboot                  -> restarts once the setup is finished
"""

from __future__ import annotations

import json
import os
import pwd
import sys
import syslog
from pathlib import Path

from .core import SETUP_USER, Machine, OemError, Owner

MAX_INPUT = 8 * 1024


def _reply(ok: bool, **fields) -> int:
    print(json.dumps({"ok": ok, **fields}, ensure_ascii=False))
    return 0 if ok else 1


def caller_allowed(pkexec_uid: str | None, getuid=os.getuid) -> bool:
    """The wizard's user through pkexec, or root itself (administrators, tests)."""
    if pkexec_uid is None:
        return getuid() == 0
    try:
        return pwd.getpwuid(int(pkexec_uid)).pw_name == SETUP_USER
    except (KeyError, ValueError):
        return False


def owner_from_json(raw: str) -> Owner:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise OemError("expected an object")
    fields = {"full_name", "username", "password", "hostname", "luks_password", "language"}
    if set(data) - fields or not all(isinstance(data.get(k), str) for k in ("full_name", "username", "password", "hostname")):
        raise OemError("unexpected fields")
    luks = data.get("luks_password")
    if luks is not None and not isinstance(luks, str):
        raise OemError("unexpected fields")
    return Owner(data["full_name"], data["username"], data["password"], data["hostname"], luks,
                 str(data.get("language", "he")))


def main(argv: list[str], machine: Machine | None = None) -> int:
    if os.geteuid() != 0:
        return _reply(False, error="dai-oem-helper must run as root (via pkexec)")
    syslog.openlog("dai-oem-helper", syslog.LOG_PID, syslog.LOG_AUTH)
    if not caller_allowed(os.environ.get("PKEXEC_UID")):
        syslog.syslog(syslog.LOG_WARNING, f"refused caller uid={os.environ.get('PKEXEC_UID')}")
        return _reply(False, error="only the first-boot setup may do this")
    machine = machine or Machine(root=Path("/"))
    command = argv[1] if len(argv) > 1 else ""
    try:
        if command == "complete":
            raw = sys.stdin.read(MAX_INPUT + 1)
            if len(raw) > MAX_INPUT:
                raise OemError("input too large")
            owner = owner_from_json(raw)
            machine.complete(owner)
            syslog.syslog(syslog.LOG_NOTICE, f"setup finished for {owner.username} on {owner.hostname}")
            return _reply(True)
        if command == "reboot":
            if machine.state().get("phase") != "cleanup":
                raise OemError("the setup is not finished")
            machine.run(["systemctl", "reboot"])
            return _reply(True)
        raise OemError("usage: dai-oem-helper complete < owner.json | reboot")
    except (OemError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        syslog.syslog(syslog.LOG_WARNING, f"{command} failed: {exc}")
        return _reply(False, error=str(exc))
