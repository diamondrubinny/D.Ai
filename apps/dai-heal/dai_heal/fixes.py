# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The fixes D.Ai Heal can offer: a closed list, each one applied only after the user agrees.

  tune            a D.Ai Tune sentence (e.g. restart a system service): plan, password, journal
  user-restart    restart one of the user's own services
  forge-repair    the Workshop fixes the app from its error, tests it, keeps the old version
  reset-settings  move ~/.config/<program> aside (kept, can be put back)
  relaunch        start the program again
  undo-update     after an update broke something: D.Ai Tune's "undo the last update" (snapshots)
  recheck         run Raz's checks again; when they pass, the problem is done

The local AI may explain a problem; it never adds a fix or runs a command.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .problems import Problem, Runner, resolve_update, run

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
PROGRAM_DIRS = ("/usr/bin/", "/usr/games/", "/usr/local/bin/")


@dataclass(frozen=True)
class Fix:
    kind: str
    payload: str


@dataclass(frozen=True)
class Outcome:
    ok: bool
    key: str            # message key in text.STRINGS
    detail: str = ""
    undo: Fix | None = None


def fixes_for(problem: Problem, home: Path | None = None) -> list[Fix]:
    home = home or Path.home()
    if problem.kind == "service":
        return [Fix("tune", f"restart service {problem.name}")]
    if problem.kind == "user-service":
        return [Fix("user-restart", problem.name)]
    if problem.kind == "forge-app":
        return [Fix("forge-repair", problem.name)]
    if problem.kind == "regression":
        return [Fix("recheck", ",".join(problem.extra.get("checks", []))), Fix("undo-update", "undo the last update")]
    if problem.kind == "crash":
        fixes = []
        exe = str(problem.extra.get("exe", ""))
        if exe.startswith(PROGRAM_DIRS) and SAFE_NAME.match(Path(exe).name):
            fixes.append(Fix("relaunch", exe))
        if SAFE_NAME.match(problem.name) and (home / ".config" / problem.name).is_dir():
            fixes.append(Fix("reset-settings", problem.name))
        return fixes
    return []


def _user_unit_ok(unit: str, runner: Runner) -> bool:
    return runner(["systemctl", "--user", "is-active", unit]).stdout.strip() == "active"


def _system_unit_ok(unit: str, runner: Runner) -> bool:
    return runner(["systemctl", "is-active", unit]).stdout.strip() == "active"


def apply(fix: Fix, problem: Problem, runner: Runner = run, home: Path | None = None,
          tune: Callable[[str], tuple[bool, str]] | None = None,
          repair: Callable[[str, str], tuple[bool, str]] | None = None,
          spawn: Callable[[list[str]], None] | None = None,
          recheck: Callable[[list[str]], list[str]] | None = None) -> Outcome:
    """Apply one fix and check the result. tune/repair/spawn are injectable for tests and the window."""
    home = home or Path.home()
    if fix.kind == "tune":
        ok, message = (tune or _tune_cli)(fix.payload)
        if not ok:
            return Outcome(False, "fix_failed", message)
        if problem.kind == "service" and not _system_unit_ok(problem.name, runner):
            return Outcome(False, "still_failing", runner(["systemctl", "status", "--no-pager", "-n", "5",
                                                           problem.name]).stdout[-1500:])
        return Outcome(True, "fixed")
    if fix.kind == "undo-update":
        ok, message = (tune or _tune_cli)("undo the last update")
        return Outcome(ok, "update_undone" if ok else "fix_failed", message)
    if fix.kind == "recheck":
        still = (recheck or _recheck)(fix.payload.split(","))
        if still:
            return Outcome(False, "still_failing", "\n".join(still))
        resolve_update(problem.name)  # passes again: no longer shown
        return Outcome(True, "recheck_ok")
    if fix.kind == "user-restart":
        if not re.match(r"^[A-Za-z0-9@._:-]+\.service$", fix.payload):
            return Outcome(False, "fix_failed", "invalid unit")
        runner(["systemctl", "--user", "reset-failed", fix.payload])
        runner(["systemctl", "--user", "restart", fix.payload])
        time.sleep(1)
        if _user_unit_ok(fix.payload, runner):
            return Outcome(True, "fixed")
        return Outcome(False, "still_failing", runner(["journalctl", "--user", "-u", fix.payload, "-n", "5",
                                                       "--no-pager", "-o", "cat"]).stdout[-1500:])
    if fix.kind == "forge-repair":
        ok, message = (repair or _forge_repair)(fix.payload, problem.detail)
        return Outcome(ok, "repaired" if ok else "fix_failed", message)
    if fix.kind == "reset-settings":
        if not SAFE_NAME.match(fix.payload):
            return Outcome(False, "fix_failed", "invalid name")
        settings = home / ".config" / fix.payload
        if not settings.is_dir() or settings.is_symlink():
            return Outcome(False, "fix_failed", f"{settings} is not there")
        backup = settings.with_name(f"{fix.payload}.dai-backup-{time.strftime('%Y%m%d-%H%M%S')}")
        settings.rename(backup)
        return Outcome(True, "settings_reset", str(backup), undo=Fix("restore-settings", str(backup)))
    if fix.kind == "restore-settings":
        backup = Path(fix.payload)
        name = backup.name.split(".dai-backup-")[0]
        target = backup.parent / name
        if backup.parent != home / ".config" or not SAFE_NAME.match(name) or not backup.is_dir():
            return Outcome(False, "fix_failed", "nothing to put back")
        if target.exists():
            shutil.move(str(target), str(target.with_name(f"{name}.dai-new-{time.strftime('%Y%m%d-%H%M%S')}")))
        backup.rename(target)
        return Outcome(True, "settings_restored", str(target))
    if fix.kind == "relaunch":
        if not fix.payload.startswith(PROGRAM_DIRS) or not os.access(fix.payload, os.X_OK):
            return Outcome(False, "fix_failed", "the program is not installed")
        (spawn or _spawn)([fix.payload])
        return Outcome(True, "relaunched")
    return Outcome(False, "fix_failed", f"unknown fix {fix.kind}")


def _recheck(ids: list[str]) -> list[str]:
    """Raz's checks again, as the user; what still fails."""
    try:
        from dai_raz import checks
    except ImportError:
        return ["Raz is not installed"]
    wanted = {i for i in ids if i}
    results = [r for r in checks.run_all() if r.id in wanted]
    return [f"{r.id}: " + "; ".join(r.items or [r.detail]) for r in results if r.status == "failed"]


def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def _tune_cli(sentence: str) -> tuple[bool, str]:
    """Plan → polkit password → journal, exactly as in D.Ai Tune."""
    try:
        from dai_tune.cli import apply_plan
        from dai_tune.context import Context, detect_lang
        from dai_tune.planner import plan_from_text
    except ImportError:
        return False, "D.Ai Tune is not installed"
    ctx = Context(lang=detect_lang())
    plan = plan_from_text(sentence, ctx)
    if not plan.ok:
        return False, "; ".join(plan.errors + plan.unknown) or "not understood"
    result = apply_plan(plan, ctx, label="D.Ai Heal")
    return result.ok, result.message


def _forge_repair(name: str, error: str) -> tuple[bool, str]:
    """The Workshop fixes the app from the error the user just hit, tests it, and saves a new version."""
    try:
        from dai_forge import apps
        from dai_forge.workshop import REPAIR_REQUEST, build
    except ImportError:
        return False, "D.Ai Forge is not installed"
    from .problems import forget_forge_crash

    app = apps.load(name)
    if app.kind == "web":
        return False, "web apps are fixed with “+ change …” in D.Ai Forge"
    built = build(REPAIR_REQUEST.format(detail=error[-1500:]), app.kind, app.code_path.read_text(encoding="utf-8"))
    if built.test.status == "failed":
        return False, built.test.detail.splitlines()[-1] if built.test.detail else "still crashes"
    permissions = {p: app.permissions.get(p, False) and built.result.get(p, False) for p in apps.PERMISSIONS}
    saved, _ = apps.save(name, app.title, app.kind, built.result["code"], permissions,
                         f"D.Ai Heal: repair after a crash", generator="ai", tested=built.test.status)
    forget_forge_crash(name)
    return True, f"v{saved.version}"
