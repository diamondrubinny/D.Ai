# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""restic, called with argv lists and a password file (never on the command line)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Callable, Sequence

from .config import EXCLUDES, MACHINES, Settings, key_path

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
KEEP = ("--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "12")
TAG = "dai"


class BackupError(RuntimeError):
    pass


def run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        # A minimal environment: no RESTIC_PASSWORD or repository variables can leak in.
        return subprocess.run(list(argv), capture_output=True, text=True, check=False,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C.UTF-8"})
    except OSError as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", str(exc))


class Restic:
    def __init__(self, settings: Settings, home: Path | None = None, runner: Runner = run) -> None:
        self.settings = settings
        self.home = home or Path.home()
        self.runner = runner
        self.key = key_path(home)

    def _argv(self, *args: str) -> list[str]:
        return ["restic", "--repo", self.settings.repo, "--password-file", str(self.key), "--no-cache", *args]

    def _run(self, *args: str) -> str:
        result = self.runner(self._argv(*args))
        if result.returncode not in (0, 3):  # 3: some files could not be read (reported, not fatal)
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
            raise BackupError(" ".join(detail) or f"restic exited with {result.returncode}")
        return result.stdout

    def available(self) -> bool:
        """The drive is connected and the backup on it is ours."""
        return (self.settings.repo_path / "config").is_file()

    def init(self) -> None:
        self._run("init")

    def backup(self) -> dict:
        folders = [str(self.home / f) for f in self.settings.folders if (self.home / f).is_dir()]
        if self.settings.machines and (self.home / MACHINES).is_dir():
            folders.append(str(self.home / MACHINES))  # the machines' disks, only when asked (dai-backup machines on)
        if not folders:
            raise BackupError("none of the chosen folders exist")
        excludes = [arg for pattern in EXCLUDES for arg in ("--exclude", pattern)]
        if not self.settings.machines:
            excludes += ["--exclude", str(self.home / MACHINES)]
        out = self._run("backup", "--json", "--tag", TAG, "--exclude-caches", *excludes, *folders)
        summary = {}
        for line in out.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("message_type") == "summary":
                summary = message
        return summary

    def maintain(self, verify: bool = True) -> None:
        self._run("forget", "--tag", TAG, *KEEP, "--prune")
        if verify:
            self._run("check", "--read-data-subset=5%")

    def snapshots(self) -> list[dict]:
        try:
            data = json.loads(self._run("snapshots", "--json", "--tag", TAG) or "[]")
        except json.JSONDecodeError:
            return []
        return sorted(data if isinstance(data, list) else [], key=lambda s: s.get("time", ""))

    def restore(self, path: Path, snapshot: str = "latest", target: Path | None = None) -> Path:
        """Restore one file or folder into ~/Restored/<date>/…, never over existing files."""
        path = path.expanduser().resolve()
        target = target or self.home / "Restored" / time.strftime("%Y-%m-%d_%H%M%S")
        if target.exists() and any(target.iterdir()):
            raise BackupError(f"{target} is not empty")
        target.mkdir(parents=True, exist_ok=True)
        self._run("restore", snapshot, "--tag", TAG, "--target", str(target), "--include", str(path))
        return target
