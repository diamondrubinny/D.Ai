# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The update guard (docs/RAZ.md §3): the system checks before and after every package change.

apt runs `dai-raz-guard pre` before dpkg and `dai-raz-guard post` after it
(/etc/apt/apt.conf.d/85dai-raz). A check that passed before and fails after
is a regression; the list goes to /var/lib/dai/raz/regressions.json, where
D.Ai Heal finds it, shows it on the Living Diamond and offers the fix
(undoing the update, with the user's OK). Never blocks apt: every error is
swallowed, and nothing runs outside a booted system (image builds, chroots).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from . import checks

STATE = Path("/var/lib/dai/raz")
HISTORY = Path("/var/log/apt/history.log")
# The checks that make sense for the whole system, run as root by apt.
SYSTEM_CHECKS = (checks.commands, checks.protected_files, checks.packages, checks.firewall, checks.updates,
                 checks.languages)


def run_system(sys_: checks.System | None = None) -> list[checks.Result]:
    sys_ = sys_ or checks.live()
    results = []
    for check in SYSTEM_CHECKS:
        try:
            results.append(check(sys_))
        except Exception as exc:  # noqa: BLE001
            results.append(checks.Result(check.__name__, "raz", "failed", type(exc).__name__))
    return results


def compare(before: list[dict], after: list[checks.Result]) -> list[dict]:
    """What got worse: a check that passed and now fails, or a failing check with new problems."""
    old = {r.get("id"): r for r in before if isinstance(r, dict)}
    found = []
    for now in after:
        was = old.get(now.id)
        if now.status != "failed" or was is None:
            continue
        if was.get("status") in ("ok", "skipped"):
            found.append({"id": now.id, "detail": now.detail, "items": now.items})
        elif was.get("status") == "failed":
            new_items = [i for i in now.items if i not in (was.get("items") or [])]
            if new_items:
                found.append({"id": now.id, "detail": now.detail, "items": new_items})
    return found


def last_change(history: Path = HISTORY) -> str:
    """The packages of the last apt run, e.g. "Upgrade: firefox-esr:amd64 (140.3 → 140.4)"."""
    try:
        text = history.read_text(encoding="utf-8", errors="replace")[-200_000:]
    except OSError:
        return ""
    block = text.rsplit("Start-Date:", 1)[-1]
    lines = [l for l in block.splitlines() if re.match(r"^(Install|Upgrade|Remove|Purge|Downgrade): ", l)]
    return " | ".join(lines)[:600]


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.chmod(tmp, 0o644)  # check names and package names only: readable so the user's Heal can show them
    os.replace(tmp, path)


def pre(state: Path = STATE, sys_: checks.System | None = None) -> None:
    _write(state / "pre.json", {"time": time.time(), "results": [asdict(r) for r in run_system(sys_)]})


def post(state: Path = STATE, sys_: checks.System | None = None, history: Path = HISTORY) -> list[dict]:
    try:
        before = json.loads((state / "pre.json").read_text(encoding="utf-8")).get("results", [])
    except (OSError, ValueError, AttributeError):
        before = []
    after = run_system(sys_)
    found = compare(before, after) if before else []
    stamp = time.time()
    _write(state / "post.json", {"time": stamp, "results": [asdict(r) for r in after]})
    _write(state / "regressions.json", {"time": stamp, "change": last_change(history), "regressions": found})
    return found


def booted() -> bool:
    return Path("/run/systemd/system").is_dir()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if len(args) != 1 or args[0] not in ("pre", "post"):
        print("usage: dai-raz-guard pre|post", file=sys.stderr)
        return 2
    if os.geteuid() != 0 or not booted():
        return 0  # only apt on a running system; never in an image build or a chroot
    try:
        pre() if args[0] == "pre" else post()
    except Exception:  # noqa: BLE001 - the guard must never get in the way of an update
        pass
    return 0
