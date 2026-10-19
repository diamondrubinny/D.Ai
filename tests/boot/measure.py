# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Measure a booted D.Ai live system (docs/HARDWARE.md §2, stage 1). It measures; it does not judge.

Called by boot-test.sh once the login prompt is seen, with the moment QEMU was started:

  measure.py <serial-socket> <launch-epoch> <login-epoch> <out.json> <memory-mb> <cpus> <accel> [idle-seconds]

It logs in like serial_check.py does, and records (seconds from the start of QEMU):
  - login:    when the login prompt appeared (boot-test.sh, one-second resolution);
  - desktop:  when the LXQt panel process is running (the desktop is usable);
  - memory:   memory in use (MemTotal - MemAvailable) after idle-seconds on the desktop, and the load average.

Numbers depend on the machine they run on: a CI runner without KVM emulates the CPU, so its times say nothing
about a real computer. Compare runs on the same kind of machine only (docs/HARDWARE.md §6).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serial_check import LIVE_PASSWORD, LIVE_USER, LOGIN_FAILED, SHELL_PROMPT_OR_FAILURE, Serial  # noqa: E402

# Seconds from the launch of QEMU; a CPU emulated without KVM can take much longer than a real one.
DESKTOP_TIMEOUT = int(os.environ.get("MEASURE_DESKTOP_TIMEOUT", "900"))


def meminfo(serial: Serial) -> dict[str, int]:
    """Kibibytes from /proc/meminfo for the keys we need."""
    out = serial.run("grep -E '^(MemTotal|MemAvailable):' /proc/meminfo")
    values = {}
    for line in out.splitlines():
        found = re.match(r"(MemTotal|MemAvailable):\s+(\d+) kB", line.strip())
        if found:
            values[found.group(1)] = int(found.group(2))
    if len(values) != 2:
        raise RuntimeError(f"could not read /proc/meminfo: {out[-200:]!r}")
    return values


def main() -> int:
    if len(sys.argv) < 8:
        print(__doc__, file=sys.stderr)
        return 2
    sock, launch, login, out, memory_mb, cpus, accel = sys.argv[1:8]
    idle_seconds = int(sys.argv[8]) if len(sys.argv) > 8 else 60
    launch_epoch, login_epoch = float(launch), float(login)

    serial = Serial(sock)
    serial.send("\n")
    serial.expect(re.compile(rb"login: ?$", re.M), 60)
    serial.send(f"{LIVE_USER}\n")
    serial.expect(re.compile(rb"Password: ?$", re.M), 30)
    serial.send(f"{LIVE_PASSWORD}\n")
    if LOGIN_FAILED.search(serial.expect(SHELL_PROMPT_OR_FAILURE, 60)):
        print("login failed; no measurement", file=sys.stderr)
        return 1
    serial.run("export TERM=dumb PAGER=cat; sudo dmesg -n 1 >/dev/null 2>&1")

    desktop = None
    while time.time() - launch_epoch < DESKTOP_TIMEOUT:
        if "PANEL_UP" in serial.run("pgrep -x lxqt-panel >/dev/null && echo PANEL_UP || echo PANEL_NO"):
            desktop = time.time() - launch_epoch
            break
        time.sleep(2)
    if desktop is None:
        print(f"the desktop did not start within {DESKTOP_TIMEOUT}s", file=sys.stderr)

    time.sleep(idle_seconds)
    mem = meminfo(serial)
    load = serial.run("cat /proc/loadavg").split()[:3]
    used_mb = (mem["MemTotal"] - mem["MemAvailable"]) // 1024
    result = {
        "memory_mb": int(memory_mb),
        "cpus": int(cpus),
        "accel": accel,
        "login_s": round(login_epoch - launch_epoch, 1),
        "desktop_s": round(desktop, 1) if desktop is not None else None,
        "idle_after_s": idle_seconds,
        "memory_used_mb": used_mb,
        "memory_total_mb": mem["MemTotal"] // 1024,
        "load_1_5_15": [float(x) for x in load] if len(load) == 3 else [],
    }
    Path(out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), file=sys.stderr)
    return 0 if desktop is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
