# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Read-only facts about this computer, from /proc, /sys and the disk.

Nothing here changes anything or needs root. Every path goes through
`root` so the logic can be tested against a fake system tree.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(list(argv), 127, "", str(exc))


@dataclass
class Proc:
    pid: int
    name: str
    cpu: float = 0.0      # percent of one core during the sample
    rss: int = 0          # bytes


@dataclass
class Battery:
    capacity: int         # percent charged
    health: int | None    # percent of the design capacity, if known
    status: str           # Charging / Discharging / Full / ...


@dataclass
class Facts:
    cores: int = 1
    load1: float = 0.0
    mem_total: int = 0        # bytes
    mem_available: int = 0
    swap_total: int = 0
    swap_free: int = 0
    uptime_days: float = 0.0
    processes: list[Proc] = field(default_factory=list)
    disks: dict[str, tuple[int, int]] = field(default_factory=dict)   # mount → (total, free)
    folders: list[tuple[str, int]] = field(default_factory=list)      # biggest folders in home
    caches: dict[str, int] = field(default_factory=dict)              # apt, journal, trash, thumbnails
    failed_units: list[str] = field(default_factory=list)
    battery: Battery | None = None
    power_profile: str = ""
    devices: list = field(default_factory=list)          # hardware.Device
    wifi_blocked: bool = False
    wifi_interfaces: list[str] = field(default_factory=list)
    printing: bool = True
    root_fs: str = ""                 # file system of /, for snapshots (docs/SNAPSHOTS.md)
    snapshots: bool = False           # snapper takes snapshots before updates
    last_update: tuple[str, int] | None = None   # (date, packages) of the last apt run
    machines: list[tuple[str, int, int]] = field(default_factory=list)  # D.Ai VM machines: (name, memory MB, CPUs)
    kvm: bool | None = None           # /dev/kvm usable by this user (None: not looked at)
    machines_free: int = 0            # bytes free where the machines' disks live


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def meminfo(root: Path) -> dict[str, int]:
    values = {}
    for line in _read(root / "proc/meminfo").splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0]] = int(parts[1]) * 1024
    return values


def _ticks(root: Path, pid: str) -> int | None:
    stat = _read(root / "proc" / pid / "stat")
    if not stat or ")" not in stat:
        return None
    fields = stat.rsplit(")", 1)[1].split()
    try:
        return int(fields[11]) + int(fields[12])  # utime + stime
    except (IndexError, ValueError):
        return None


def processes(root: Path, sample: float = 0.5) -> list[Proc]:
    """Every process with its CPU use over `sample` seconds and its memory."""
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    pids = [p.name for p in (root / "proc").iterdir() if p.name.isdigit()] if (root / "proc").is_dir() else []
    before = {pid: _ticks(root, pid) for pid in pids}
    started = time.monotonic()
    if sample > 0:
        time.sleep(sample)
    elapsed = max(time.monotonic() - started, 1e-6)
    result = []
    for pid in pids:
        name = _read(root / "proc" / pid / "comm").strip()
        if not name:
            continue
        statm = _read(root / "proc" / pid / "statm").split()
        rss = int(statm[1]) * page if len(statm) > 1 and statm[1].isdigit() else 0
        after = _ticks(root, pid)
        cpu = 0.0
        if sample > 0 and before.get(pid) is not None and after is not None:
            cpu = max(0.0, (after - before[pid]) / hz / elapsed * 100)
        result.append(Proc(int(pid), name, round(cpu, 1), rss))
    return result


def dir_size(path: Path, deadline: float) -> int:
    """Size of a folder tree, without following symlinks; stops at the deadline."""
    total = 0
    stack = [path]
    while stack and time.monotonic() < deadline:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_blocks * 512
            except OSError:
                continue
    return total


def biggest_folders(home: Path, budget: float = 3.0, top: int = 6) -> list[tuple[str, int]]:
    deadline = time.monotonic() + budget
    sizes = []
    try:
        children = [c for c in home.iterdir() if c.is_dir() and not c.is_symlink()]
    except OSError:
        return []
    for child in children:
        sizes.append((child.name, dir_size(child, deadline)))
    return sorted((s for s in sizes if s[1] > 0), key=lambda s: s[1], reverse=True)[:top]


def battery(root: Path) -> Battery | None:
    supplies = sorted((root / "sys/class/power_supply").glob("BAT*"))
    for supply in supplies:
        capacity = _read(supply / "capacity").strip()
        if not capacity.isdigit():
            continue
        health = None
        for full, design in (("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")):
            a, b = _read(supply / full).strip(), _read(supply / design).strip()
            if a.isdigit() and b.isdigit() and int(b) > 0:
                health = min(100, round(int(a) * 100 / int(b)))
                break
        return Battery(int(capacity), health, _read(supply / "status").strip() or "Unknown")
    return None


def root_filesystem(root: Path) -> str:
    fstype = ""
    for line in _read(root / "proc/mounts").splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "/":
            fstype = fields[2]  # the last mount on / wins (overlays)
    return fstype


def last_apt_run(root: Path) -> tuple[str, int] | None:
    """Date and number of packages of the last install/upgrade in apt's history."""
    entry = _read(root / "var/log/apt/history.log").strip().split("\n\n")[-1]
    date, count = "", 0
    for line in entry.splitlines():
        key, _, value = line.partition(": ")
        if key == "Start-Date":
            date = value.strip()
        elif key in ("Install", "Upgrade", "Remove", "Purge", "Downgrade", "Reinstall"):
            count += len(re.findall(r"\),?", value)) or 1
    return (date, count) if date else None


def vm_machines(home: Path) -> list[tuple[str, int, int]]:
    """D.Ai VM's machines (docs/VM.md), read from their own files so Doctor needs nothing from dai-vm."""
    import json

    found = []
    for path in sorted((home / ".local/share/dai/vm/machines").glob("*/machine.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            found.append((str(data["name"]), int(data["memory_mb"]), int(data["cpus"])))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def collect(root: Path = Path("/"), home: Path | None = None, runner: Runner = run, sample: float = 0.5,
            topics: tuple[str, ...] = ("slow", "disk", "battery", "hardware", "update"), budget: float = 3.0) -> Facts:
    home = home or Path.home()
    facts = Facts(cores=os.cpu_count() or 1)
    load = _read(root / "proc/loadavg").split()
    facts.load1 = float(load[0]) if load else 0.0
    mem = meminfo(root)
    facts.mem_total, facts.mem_available = mem.get("MemTotal", 0), mem.get("MemAvailable", 0)
    facts.swap_total, facts.swap_free = mem.get("SwapTotal", 0), mem.get("SwapFree", 0)
    uptime = _read(root / "proc/uptime").split()
    facts.uptime_days = float(uptime[0]) / 86400 if uptime else 0.0
    if "slow" in topics:
        facts.processes = processes(root, sample)
        failed = runner(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"])
        facts.failed_units = [line.split()[0] for line in failed.stdout.splitlines() if line.strip()]
    for mount in ("/", str(home)):
        target = root / mount.lstrip("/") if root != Path("/") else Path(mount)
        try:
            usage = shutil.disk_usage(target)
        except OSError:
            continue
        if not any(v == (usage.total, usage.free) for v in facts.disks.values()):
            facts.disks[mount] = (usage.total, usage.free)
    if "disk" in topics:
        deadline = time.monotonic() + budget
        facts.caches = {
            "apt": dir_size(root / "var/cache/apt/archives", deadline),
            "journal": dir_size(root / "var/log/journal", deadline),
            "trash": dir_size(home / ".local/share/Trash", deadline),
            "thumbnails": dir_size(home / ".cache/thumbnails", deadline),
        }
        facts.folders = biggest_folders(home, budget)
    if "hardware" in topics:
        from . import hardware

        facts.devices = hardware.scan(root, runner)
        facts.wifi_blocked = hardware.wifi_blocked(root)
        facts.wifi_interfaces = hardware.wifi_interfaces(root)
        facts.printing = hardware.printing_installed(root)
    if "update" in topics:
        facts.root_fs = root_filesystem(root)
        facts.snapshots = (root / "etc/snapper/configs/root").exists()
        facts.last_update = last_apt_run(root)
    if "machine" in topics:
        facts.processes = facts.processes or processes(root, sample)
        facts.kvm = os.access(root / "dev/kvm", os.R_OK | os.W_OK)
        facts.machines = vm_machines(home)
        try:
            facts.machines_free = shutil.disk_usage(home / ".local/share/dai/vm" if (home / ".local/share/dai/vm").is_dir()
                                                    else home).free
        except OSError:
            facts.machines_free = 0
    if "battery" in topics:
        facts.battery = battery(root)
        if facts.battery is not None:
            profile = runner(["powerprofilesctl", "get"])
            facts.power_profile = profile.stdout.strip() if profile.returncode == 0 else ""
    return facts
