# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Raz's checks (docs/RAZ.md §2): is every part of D.Ai still working?

One list, run on the user's computer (`dai-raz check`) and inside the CI's
virtual machine, so what is checked before a release is checked again on
every real computer. Read-only and as the user: nothing here changes the
system or needs root. Every command is a fixed argv, never a shell.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

CREDIT = "Diamond Rubinny (d.Ai)"

# The D.Ai commands that answer --version with the credit line.
COMMANDS = ("dai-ai", "dai-backup", "dai-clip", "dai-code", "dai-command", "dai-doctor", "dai-evolve", "dai-find",
            "dai-forge", "dai-heal", "dai-j", "dai-mom", "dai-move", "dai-pdf", "dai-privacy", "dai-quick", "dai-raz",
            "dai-tune", "dai-vm", "dai-voice", "dai-welcome")
PANEL_PLUGINS = ("libdaicommand.so", "libdaistatus.so", "libdaiclock.so")
# Files that must exist, belong to root and be writable by nobody else.
PROTECTED_FILES = ("/etc/nftables.conf", "/etc/firefox/policies/policies.json",
                   "/usr/share/polkit-1/actions/io.github.diamondrubinny.dai.tune.policy", "/usr/lib/dai/dai-tune-helper")
OUR_PACKAGES = ("dai-apps", "dai-ruby", "dai-panel-plugin")


@dataclass
class Result:
    id: str
    area: str              # components, config, security, languages
    status: str            # ok, failed, skipped
    detail: str = ""
    items: list[str] = field(default_factory=list)   # what exactly failed


@dataclass
class System:
    """Everything a check may look at; tests replace it."""
    run: Callable[[list[str]], subprocess.CompletedProcess]
    which: Callable[[str], str | None] = shutil.which
    root: Path = Path("/")

    def path(self, name: str) -> Path:
        return self.root / name.lstrip("/")


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False,
                              env={**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def live() -> System:
    return System(run=_run)


# Components

def commands(sys: System) -> Result:
    broken = []
    for name in COMMANDS:
        if sys.which(name) is None:
            broken.append(f"{name}: missing")
            continue
        result = sys.run([name, "--version"])
        if result.returncode != 0 or CREDIT not in result.stdout + result.stderr:
            broken.append(f"{name}: exit {result.returncode}")
    return Result("commands", "components", "failed" if broken else "ok", f"{len(COMMANDS)} commands", broken)


def panel(sys: System) -> Result:
    result = sys.run(["pgrep", "-u", str(os.getuid()), "-x", "lxqt-panel"])
    pid = result.stdout.split()[0] if result.returncode == 0 and result.stdout.split() else ""
    if not pid:
        return Result("panel", "components", "skipped", "lxqt-panel is not running")
    try:
        maps = sys.path(f"/proc/{pid}/maps").read_text(errors="replace")
    except OSError:
        return Result("panel", "components", "skipped", "cannot read the panel's memory map")
    missing = [p for p in PANEL_PLUGINS if p not in maps]
    return Result("panel", "components", "failed" if missing else "ok", "panel plugins loaded", missing)


def services(sys: System) -> Result:
    if sys.which("systemctl") is None:
        return Result("services", "components", "skipped", "no systemd")
    wanted = (("dai-daid.socket", "enabled"), ("dai-evolve.timer", "enabled"))
    broken = []
    for unit, state in wanted:
        result = sys.run(["systemctl", "--user", "is-enabled", unit])
        if result.stdout.strip() != state:
            broken.append(f"{unit}: {result.stdout.strip() or 'unknown'}")
    return Result("services", "components", "failed" if broken else "ok", "user services", broken)


# Configuration

def protected_files(sys: System) -> Result:
    problems = []
    for name in PROTECTED_FILES:
        path = sys.path(name)
        try:
            info = path.lstat()
        except OSError:
            problems.append(f"{name}: missing")
            continue
        if info.st_uid != 0:
            problems.append(f"{name}: not owned by root")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            problems.append(f"{name}: writable by others")
        if name.endswith(".json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.append(f"{name}: not valid JSON")
    return Result("files", "config", "failed" if problems else "ok", f"{len(PROTECTED_FILES)} files", problems)


def packages(sys: System) -> Result:
    """dpkg's own record of our files: anything changed since installation shows up here."""
    if sys.which("dpkg") is None:
        return Result("packages", "config", "skipped", "no dpkg")
    installed = [p for p in OUR_PACKAGES if sys.run(["dpkg-query", "-W", "-f=${Status}", p]).stdout.endswith(" installed")]
    if not installed:
        return Result("packages", "config", "skipped", "no D.Ai packages installed")
    result = sys.run(["dpkg", "--verify", *installed])
    # Conffiles ("c" in the attribute column) are the user's to change; everything else is ours.
    changed = [line.split()[-1] for line in result.stdout.splitlines()
               if line.strip() and len(line.split()) >= 2 and line.split()[1] != "c"]
    return Result("packages", "config", "failed" if changed else "ok", ", ".join(installed), changed[:20])


# Security

def firewall(sys: System) -> Result:
    if sys.which("systemctl") is None:
        return Result("firewall", "security", "skipped", "no systemd")
    active = sys.run(["systemctl", "is-active", "nftables.service"]).stdout.strip()
    return Result("firewall", "security", "ok" if active == "active" else "failed", f"nftables {active or 'unknown'}")


def updates(sys: System) -> Result:
    """Security updates install by themselves: the setting D.Ai Tune's score also reads."""
    try:
        text = sys.path("/etc/apt/apt.conf.d/20auto-upgrades").read_text(errors="replace")
    except OSError:
        text = ""
    ok = re.search(r'Unattended-Upgrade\s+"1"', text) is not None
    return Result("updates", "security", "ok" if ok else "failed", "automatic security updates " + ("on" if ok else "off"))


def posture(sys: System) -> Result:
    try:
        from dai_tune.context import Context
        from dai_tune.posture import assess
    except ImportError:
        return Result("posture", "security", "skipped", "D.Ai Tune is not installed")
    try:
        score, items = assess(Context(lang="en"), "en")
    except Exception as exc:  # noqa: BLE001 - a broken assessment is itself the finding
        return Result("posture", "security", "failed", f"the security score cannot be computed: {type(exc).__name__}")
    return Result("posture", "security", "ok", f"security score {score}/100")


# Languages

def languages(sys: System) -> Result:
    try:
        import dai_i18n
    except ImportError:
        return Result("languages", "languages", "failed", "dai_i18n is missing")
    problems = []
    if not dai_i18n.is_rtl("he") or not dai_i18n.is_rtl("ar") or dai_i18n.is_rtl("ru"):
        problems.append("text direction")
    for lang in ("he", "en", "ar", "ru", "es", "fr", "de", "pt"):
        try:
            filled = dai_i18n.text(lang, "{n} new", "{n} חדשים", n=3)
            if "3" not in filled or "{" in filled:  # filled in, wherever the language puts the number
                problems.append(f"{lang}: placeholders")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{lang}: {type(exc).__name__}")
    return Result("languages", "languages", "failed" if problems else "ok", "8 languages", problems)


CHECKS: tuple[Callable[[System], Result], ...] = (commands, panel, services, protected_files, packages, firewall, updates,
                                                  posture, languages)


def run_all(sys: System | None = None) -> list[Result]:
    sys = sys or live()
    results = []
    for check in CHECKS:
        try:
            results.append(check(sys))
        except Exception as exc:  # noqa: BLE001 - one broken check never hides the others
            results.append(Result(check.__name__, "raz", "failed", f"the check itself failed: {type(exc).__name__}"))
    return results


def to_json(results: list[Result]) -> str:
    return json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2)
