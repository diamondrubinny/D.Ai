# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Who is recording or filming right now. Read-only, no privileges needed.

  * PipeWire (pw-dump): running capture streams. Audio → microphone; video →
    camera or screen sharing (PipeWire cannot reliably tell those apart).
  * /proc/*/fd: processes of this user that opened /dev/video* directly.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


@dataclass(frozen=True, order=True)
class Use:
    device: str   # mic | camera | video (camera or screen sharing)
    app: str
    pid: int = 0


def run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", str(exc))


def _app_name(props: dict) -> str:
    for key in ("application.name", "application.process.binary", "node.name"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:64]
    return "?"


def parse_pw_dump(data: object) -> list[Use]:
    uses = []
    if not isinstance(data, list):
        return uses
    for obj in data:
        if not isinstance(obj, dict) or obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info") or {}
        props = info.get("props") or {}
        media = props.get("media.class")
        if info.get("state") != "running" or media not in ("Stream/Input/Audio", "Stream/Input/Video"):
            continue
        if str(props.get("stream.monitor", "")).lower() == "true":
            continue  # volume meters watch levels; they do not record
        pid = props.get("application.process.id")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            pid = 0
        uses.append(Use("mic" if media == "Stream/Input/Audio" else "video", _app_name(props), pid))
    return uses


def pipewire_uses(runner: Runner = run) -> list[Use]:
    result = runner(["pw-dump", "--no-colors"])
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return parse_pw_dump(json.loads(result.stdout))
    except json.JSONDecodeError:
        return []


def camera_uses(proc: Path = Path("/proc")) -> list[Use]:
    """Processes (of this user) holding /dev/video* open."""
    uses = []
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return uses
    for pid_dir in pids:
        try:
            fds = list((pid_dir / "fd").iterdir())
        except OSError:
            continue  # another user's process, or gone
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith("/dev/video"):
                try:
                    name = (pid_dir / "comm").read_text().strip() or "?"
                except OSError:
                    name = "?"
                uses.append(Use("camera", name, int(pid_dir.name)))
                break
    return uses


def current(runner: Runner = run, proc: Path = Path("/proc")) -> list[Use]:
    """Everything in use now, without duplicates (one app may hold several streams)."""
    return sorted(set(pipewire_uses(runner)) | set(camera_uses(proc)))
