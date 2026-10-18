# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Closing apps, safely (docs/MOM.md §5).

- Only this user's processes; never other users' or the system's.
- Every signal is checked against the identity seen on screen (pid and start
  time), so a pid that was reused by a new process is never hit.
- Parts of the session need an explicit "yes" to close and cannot be forced.
- No shell: os.kill with a fixed signal.

A closed or forced app does not show up in D.Ai Heal as a crash: SIGTERM and
SIGKILL never make a core dump.
"""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .apps import App
from .procs import is_same


class Refused(Exception):
    """The action is not allowed; the message says why (a key for the interface text)."""


@dataclass
class Result:
    signalled: list[int] = field(default_factory=list)
    gone: list[int] = field(default_factory=list)       # already closed, or the pid now belongs to someone else


Killer = Callable[[int, int], None]


def _check(app: App, force: bool, confirmed: bool) -> None:
    if app.protected and force:
        raise Refused("protected_force")
    if app.protected and not confirmed:
        raise Refused("protected_confirm")
    if force and not confirmed:
        raise Refused("force_confirm")


def close(app: App, force: bool = False, confirmed: bool = False, root: Path = Path("/"),
          kill: Killer = os.kill, uid: int | None = None) -> Result:
    """Ask the app to close (SIGTERM to its top processes) or force it (SIGKILL to all of them)."""
    _check(app, force, confirmed)
    uid = os.getuid() if uid is None else uid
    if uid == 0:
        raise Refused("root")  # MOM never runs as root
    targets = app.processes if force else app.roots
    result = Result()
    me = os.getpid()
    for process in targets:
        if process.pid in (1, me):
            continue
        current = is_same(root, process.key)
        if current is None or current.uid != uid:
            result.gone.append(process.pid)
            continue
        try:
            kill(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            result.signalled.append(process.pid)
        except ProcessLookupError:
            result.gone.append(process.pid)
        except PermissionError:
            raise Refused("permission") from None
    return result


def still_running(app: App, root: Path = Path("/")) -> bool:
    return any(is_same(root, p.key) is not None for p in app.processes)
