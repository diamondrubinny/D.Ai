# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The USB devices plugged into this computer, read from sysfs, so the person can give one to a machine
(docs/VM.md stage 2). Hubs and the root hubs are left out; nothing is opened, only names are read."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SYS_USB = Path("/sys/bus/usb/devices")
HUB_CLASS = "09"


@dataclass(frozen=True)
class UsbDevice:
    usb_id: str      # "vendor:product", lower-case hex
    name: str        # manufacturer and product, as the device says them
    bus: str         # e.g. "1-3"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.usb_id})" if self.name else self.usb_id


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def list_devices(sys_usb: Path | None = None) -> list[UsbDevice]:
    """Every USB device that is not a hub, sorted by bus position."""
    out = []
    try:
        entries = sorted((sys_usb or SYS_USB).iterdir())
    except OSError:
        return []
    for entry in entries:
        if ":" in entry.name or not (entry / "idVendor").exists():
            continue  # an interface, not a device
        if _read(entry / "bDeviceClass") == HUB_CLASS:
            continue
        vendor, product = _read(entry / "idVendor").lower(), _read(entry / "idProduct").lower()
        if len(vendor) != 4 or len(product) != 4:
            continue
        name = " ".join(part for part in (_read(entry / "manufacturer"), _read(entry / "product")) if part)
        out.append(UsbDevice(f"{vendor}:{product}", name[:80], entry.name))
    return out
