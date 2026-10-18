# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What broke: facts gathered read-only, as the user (docs/EVOLVE.md §4).

  service       a system service failed            systemctl --failed
  user-service  one of the user's services failed  systemctl --user --failed
  crash         a program crashed                  coredumpctl (metadata only, never the dump)
  forge-app     an app built with D.Ai Forge crashed  ~/.local/state/dai/heal/forge-*.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]

UNIT_RE = re.compile(r"^[A-Za-z0-9@._:-]+\.(?:service|socket|timer|mount|path)$")
MAX_DETAIL = 2000


def run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False,
                              env={**os.environ, "SYSTEMD_COLORS": "0", "LANG": "C.UTF-8"})
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(argv, 127, "", "")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "dai" / "heal"


@dataclass
class Problem:
    kind: str           # service | user-service | crash | forge-app
    name: str           # unit, program or app name
    when: float = 0.0
    detail: str = ""    # error lines (shown to the user; data, never instructions)
    count: int = 1
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable across repeats of the same problem (used for "don't ask again" and rate limits)."""
        return hashlib.sha256(f"{self.kind}:{self.name}".encode()).hexdigest()[:12]

    def to_json(self) -> dict:
        return {"kind": self.kind, "name": self.name, "when": self.when, "detail": self.detail[:MAX_DETAIL],
                "count": self.count, "extra": self.extra, "key": self.key}

    @staticmethod
    def from_json(data: dict) -> "Problem":
        return Problem(str(data.get("kind", "")), str(data.get("name", "")), float(data.get("when", 0) or 0),
                       str(data.get("detail", ""))[:MAX_DETAIL], int(data.get("count", 1) or 1),
                       data.get("extra") if isinstance(data.get("extra"), dict) else {})


def failed_units(runner: Runner = run, user: bool = False) -> list[Problem]:
    argv = ["systemctl", *(["--user"] if user else []), "list-units", "--failed", "--plain", "--no-legend", "--no-pager"]
    result = runner(argv)
    problems = []
    for line in result.stdout.splitlines():
        fields = line.lstrip("●*× \t").split()  # some versions print a status bullet first
        if fields and UNIT_RE.match(fields[0]):
            unit = fields[0]
            problems.append(Problem("user-service" if user else "service", unit, time.time(),
                                    _unit_log(unit, runner, user)))
    return problems


def _unit_log(unit: str, runner: Runner, user: bool) -> str:
    argv = ["journalctl", *(["--user"] if user else []), "-u", unit, "-n", "8", "--no-pager", "-o", "cat"]
    return runner(argv).stdout.strip()[-MAX_DETAIL:]


def crashes(runner: Runner = run, since: float | None = None) -> list[Problem]:
    """Programs that crashed, from systemd-coredump's records (the dump itself is never read)."""
    since_arg = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since or time.time() - 7 * 86400))
    result = runner(["coredumpctl", "list", "--no-pager", "--json=short", f"--since={since_arg}"])
    try:
        rows = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else []
    except ValueError:
        rows = []
    found: dict[str, Problem] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("exe"), str):
            continue
        if int(row.get("uid", -1) if str(row.get("uid", "")).lstrip("-").isdigit() else -1) != os.getuid():
            continue  # only the user's own programs
        exe = row["exe"]
        name = Path(exe).name
        when = row.get("time", 0)
        when = when / 1_000_000 if isinstance(when, (int, float)) and when > 1e12 else float(when or 0)
        signal = row.get("sig")
        if name in found:
            found[name].count += 1
            found[name].when = max(found[name].when, when)
        else:
            found[name] = Problem("crash", name, when, f"signal {signal}" if signal else "", 1, {"exe": exe})
    return list(found.values())


def forge_crashes(directory: Path | None = None) -> list[Problem]:
    directory = directory or state_dir()
    problems = []
    for path in sorted(directory.glob("forge-*.json")):
        try:
            problem = Problem.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if problem.kind == "forge-app" and re.match(r"^[a-z][a-z0-9-]{1,30}$", problem.name):
            problems.append(problem)
    return problems


def collect(runner: Runner = run, since: float | None = None) -> list[Problem]:
    problems = failed_units(runner) + failed_units(runner, user=True) + crashes(runner, since) + forge_crashes()
    return sorted(problems, key=lambda p: p.when, reverse=True)


def forget_forge_crash(name: str, directory: Path | None = None) -> None:
    (directory or state_dir()).joinpath(f"forge-{name}.json").unlink(missing_ok=True)
