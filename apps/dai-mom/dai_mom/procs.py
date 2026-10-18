# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Every process on the computer, read from /proc (docs/MOM.md §3).

Read-only. Every path goes through `root` so it can be tested against a
fake /proc. A process is identified by (pid, start time), never by the pid
alone: pids are reused, and acting on a reused pid would hit a stranger.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Process:
    pid: int
    ppid: int
    uid: int
    name: str                 # /proc/<pid>/comm
    cmdline: list[str]
    exe: str                  # "" when it cannot be read (other users' processes)
    start: int                # clock ticks after boot; with the pid, the identity
    ticks: int                # utime + stime
    memory: int               # bytes: PSS when readable, otherwise RSS
    state: str = ""
    cgroup: str = ""          # the systemd scope, e.g. app-flatpak-org.gimp.GIMP-1234.scope
    cpu: float = 0.0          # percent of the whole computer since the last sample

    @property
    def key(self) -> tuple[int, int]:
        return (self.pid, self.start)


@dataclass
class Snapshot:
    processes: dict[int, Process] = field(default_factory=dict)
    taken: float = 0.0
    cores: int = 1


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_stat(text: str) -> tuple[str, int, int, int] | None:
    """(state, ppid, ticks, start) from /proc/<pid>/stat. The name may hold spaces and ')'."""
    if ")" not in text:
        return None
    fields = text.rsplit(")", 1)[1].split()
    try:
        return fields[0], int(fields[1]), int(fields[11]) + int(fields[12]), int(fields[19])
    except (IndexError, ValueError):
        return None


def _uid(status: str) -> int:
    for line in status.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    return -1


def _memory(root: Path, pid: str, page: int) -> int:
    for line in _read(root / "proc" / pid / "smaps_rollup").splitlines():
        if line.startswith("Pss:"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1]) * 1024
    statm = _read(root / "proc" / pid / "statm").split()
    return int(statm[1]) * page if len(statm) > 1 and statm[1].isdigit() else 0


def read_process(root: Path, pid: str, page: int = 4096) -> Process | None:
    base = root / "proc" / pid
    stat = parse_stat(_read(base / "stat"))
    if stat is None:
        return None  # gone, or a kernel thread being torn down
    state, ppid, ticks, start = stat
    raw = _read(base / "cmdline")
    try:
        exe = os.readlink(base / "exe")
    except OSError:
        exe = ""
    return Process(pid=int(pid), ppid=ppid, uid=_uid(_read(base / "status")),
                   name=_read(base / "comm").strip() or "?", cmdline=[a for a in raw.split("\0") if a],
                   exe=exe, start=start, ticks=ticks, memory=_memory(root, pid, page), state=state,
                   cgroup=_read(base / "cgroup").strip().rsplit("/", 1)[-1])


def snapshot(root: Path = Path("/"), previous: Snapshot | None = None, now: float | None = None) -> Snapshot:
    """All processes now; CPU is measured against `previous` (the same process only: same pid and start)."""
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    cores = os.cpu_count() or 1
    taken = time.monotonic() if now is None else now
    proc = root / "proc"
    result = Snapshot(taken=taken, cores=cores)
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        process = read_process(root, entry.name, page)
        if process is None or not process.cmdline and 2 in (process.pid, process.ppid):
            continue  # kernel threads have no command line and belong to kthreadd
        if previous is not None:
            before = previous.processes.get(process.pid)
            elapsed = taken - previous.taken
            if before is not None and before.start == process.start and elapsed > 0:
                process.cpu = round(max(0.0, (process.ticks - before.ticks) / hz / elapsed * 100 / cores), 1)
        result.processes[process.pid] = process
    return result


def is_same(root: Path, key: tuple[int, int]) -> Process | None:
    """The process if it is still the one we saw (same pid and start time), else None."""
    process = read_process(root, str(key[0]))
    return process if process is not None and process.start == key[1] else None


def memory_totals(root: Path = Path("/")) -> dict[str, int]:
    """MemTotal, MemAvailable, SwapTotal and SwapFree in bytes."""
    values: dict[str, int] = {}
    for line in _read(root / "proc/meminfo").splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0]] = int(parts[1]) * 1024
    return values


def cpu_total(root: Path = Path("/")) -> tuple[int, int]:
    """(busy, all) jiffies from the first line of /proc/stat."""
    first = _read(root / "proc/stat").split("\n", 1)[0].split()
    try:
        numbers = [int(v) for v in first[1:]]
    except ValueError:
        return (0, 0)
    idle = sum(numbers[3:5]) if len(numbers) >= 5 else 0
    return (sum(numbers) - idle, sum(numbers))
