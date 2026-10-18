# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Will my hardware work? Read from sysfs, without root.

A device "works" when the kernel bound a driver to it. Typical reasons it
does not: no driver for that chip, missing firmware, or it is switched off
(rfkill). Run in the live session, this answers the question before
installing anything.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

# PCI class (first 4 hex digits of 0xCCSSPP) → kind.
PCI_KINDS = {"0280": "wifi", "0200": "ethernet", "0300": "graphics", "0302": "graphics", "0380": "graphics",
             "0403": "audio", "0401": "audio"}


@dataclass(frozen=True)
class Device:
    kind: str           # wifi | ethernet | graphics | audio | camera | bluetooth | printer
    name: str
    driver: str | None  # None: no driver bound
    slot: str = ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _pci_name(slot: str, runner: Callable[[Sequence[str]], subprocess.CompletedProcess] | None) -> str:
    if runner is None:
        return ""
    result = runner(["lspci", "-mm", "-s", slot])
    return parse_lspci_mm(result.stdout) if result.returncode == 0 else ""


def parse_lspci_mm(line: str) -> str:
    """'00:02.0 "VGA compatible controller" "Intel Corporation" "UHD Graphics 620" -r07 -p00 ...' → vendor + device."""
    try:
        fields = [f for f in shlex.split(line.strip().splitlines()[0]) if not f.startswith("-")] if line.strip() else []
    except ValueError:
        return ""
    return f"{fields[2]} {fields[3]}".strip() if len(fields) >= 4 else ""


def scan(root: Path = Path("/"), runner=None) -> list[Device]:
    devices: list[Device] = []
    for dev in sorted((root / "sys/bus/pci/devices").glob("*")):
        kind = PCI_KINDS.get(_read(dev / "class").removeprefix("0x")[:4])
        if not kind:
            continue
        driver = (dev / "driver").resolve().name if (dev / "driver").exists() else None
        name = _pci_name(dev.name, runner) or f"{_read(dev / 'vendor')}:{_read(dev / 'device')}"
        devices.append(Device(kind, name, driver, dev.name))
    for cam in sorted((root / "sys/class/video4linux").glob("video*")):
        name = _read(cam / "name") or cam.name
        if not any(d.kind == "camera" and d.name == name for d in devices):
            devices.append(Device("camera", name, "uvcvideo" if (cam / "device/driver").exists() else None))
    for hci in sorted((root / "sys/class/bluetooth").glob("hci*")):
        devices.append(Device("bluetooth", hci.name, "btusb" if (hci / "device/driver").exists() else "bluetooth"))
    for intf in sorted((root / "sys/bus/usb/devices").glob("*:*")):
        if _read(intf / "bInterfaceClass") == "07":  # USB printer class
            parent = intf.parent / intf.name.split(":")[0]
            name = " ".join(filter(None, (_read(parent / "manufacturer"), _read(parent / "product")))) or "USB printer"
            devices.append(Device("printer", name, "usblp" if (intf / "driver").exists() else None))
    return devices


def wifi_blocked(root: Path = Path("/")) -> bool:
    for kill in (root / "sys/class/rfkill").glob("rfkill*"):
        if _read(kill / "type") == "wlan" and (_read(kill / "soft") == "1" or _read(kill / "hard") == "1"):
            return True
    return False


def wifi_interfaces(root: Path = Path("/")) -> list[str]:
    return [p.name for p in (root / "sys/class/net").glob("*") if (p / "wireless").is_dir()]


def printing_installed(root: Path = Path("/")) -> bool:
    return (root / "usr/sbin/cupsd").exists()
