# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""A machine: what the person chose, where its files live, and the libvirt definition built from it
(docs/VM.md §4). Everything runs under qemu:///session, as the person, in their home folder (on the encrypted
disk):

  ~/.local/share/dai/vm/machines/<name>/machine.json   the choices
  ~/.local/share/dai/vm/machines/<name>/disk.qcow2     the disk (grows as used)
  ~/.local/share/dai/vm/machines/<name>/domain.xml     what libvirt was given

The definition for Windows 11: q35, UEFI with Secure Boot (libvirt picks Debian's OVMF with Microsoft's keys),
a TPM 2.0 from swtpm, a VirtIO disk, VirtIO network through passt (the person's own session, no bridge), QXL
graphics on SPICE over a local socket, a USB tablet, sound, a balloon, a random-number source, and the VirtIO
drivers ISO as a second CD. Clipboard sharing, a shared folder and USB devices are off unless turned on (stage 2):
each is a switch in the saved choices, the definition is rewritten from them, and a running machine takes a
clipboard or folder change at its next start (USB devices go in and out live).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .hardware import MAX_GUEST_MB, MIN_GUEST_MB

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
USB_ID_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
WINDOWS_KINDS = ("11", "10", "other")
MIN_DISK_GB, MAX_DISK_GB = 32, 2048


class MachineError(ValueError):
    pass


@dataclass
class Machine:
    name: str
    memory_mb: int
    cpus: int
    disk_gb: int
    iso: str | None = None            # the installation media; None once installed and detached
    drivers_iso: str | None = None    # the VirtIO drivers ISO
    windows: str = "11"               # "11", "10" or "other"
    clipboard: bool = False
    shared_folder: str | None = None
    shared_readonly: bool = True       # Windows reads the folder; writing is a second choice
    usb: list[str] = field(default_factory=list)  # "vendor:product" ids given to the machine at start
    created: str = ""

    def validate(self) -> "Machine":
        if not NAME_RE.match(self.name):
            raise MachineError("a name is letters, digits, dots, dashes and underscores, up to 40 characters")
        if not MIN_GUEST_MB <= int(self.memory_mb) <= MAX_GUEST_MB:
            raise MachineError(f"memory must be between {MIN_GUEST_MB} and {MAX_GUEST_MB} MB")
        if not 1 <= int(self.cpus) <= 32:
            raise MachineError("CPUs must be between 1 and 32")
        if not MIN_DISK_GB <= int(self.disk_gb) <= MAX_DISK_GB:
            raise MachineError(f"the disk must be between {MIN_DISK_GB} and {MAX_DISK_GB} GB")
        if self.windows not in WINDOWS_KINDS:
            raise MachineError("windows must be 11, 10 or other")
        for path in (self.iso, self.drivers_iso):
            if path is not None and not Path(path).is_file():
                raise MachineError(f"no such file: {path}")
        if self.shared_folder is not None:
            folder = Path(self.shared_folder)
            if not folder.is_absolute() or not folder.is_dir():
                raise MachineError(f"not a folder: {self.shared_folder}")
            if folder.resolve() == Path.home().resolve() or folder.resolve() == Path("/"):
                raise MachineError("share a folder inside your home, not the whole home or the whole disk")
        for usb_id in self.usb:
            if not USB_ID_RE.match(usb_id):
                raise MachineError(f"a USB id looks like 1234:abcd, not {usb_id}")
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Machine":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def machines_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "share" / "dai" / "vm" / "machines"


def machine_dir(name: str, home: Path | None = None) -> Path:
    return machines_dir(home) / name


def domain_name(name: str) -> str:
    return f"dai-{name}"


def domain_uuid(name: str) -> str:
    """libvirt refuses to redefine a domain under a new UUID; D.Ai's is derived from the name, so it never changes."""
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://d.ai/vm/" + name))


def save(machine: Machine, home: Path | None = None) -> Path:
    folder = machine_dir(machine.name, home)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "machine.json"
    path.write_text(json.dumps(machine.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(name: str, home: Path | None = None) -> Machine:
    path = machine_dir(name, home) / "machine.json"
    try:
        return Machine.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise MachineError(f"no machine called {name}") from exc


def list_machines(home: Path | None = None) -> list[Machine]:
    out = []
    for folder in sorted(machines_dir(home).glob("*")):
        if (folder / "machine.json").is_file():
            try:
                out.append(load(folder.name, home))
            except MachineError:
                continue
    return out


def _sub(parent, tag: str, text: str | None = None, **attrs: str):
    element = ET.SubElement(parent, tag, {k.rstrip("_"): v for k, v in attrs.items()})
    if text is not None:
        element.text = text
    return element


def domain_xml(machine: Machine, home: Path | None = None) -> str:
    """The libvirt domain definition for this machine."""
    folder = machine_dir(machine.name, home)
    disk = folder / "disk.qcow2"
    domain = ET.Element("domain", type="kvm")
    _sub(domain, "name", domain_name(machine.name))
    _sub(domain, "uuid", domain_uuid(machine.name))  # fixed per name, so a changed definition replaces the old one
    _sub(domain, "title", machine.name)
    _sub(domain, "description", "Made by D.Ai VM (docs/VM.md). The person's own media and key.")
    _sub(domain, "memory", str(int(machine.memory_mb)), unit="MiB")
    _sub(domain, "currentMemory", str(int(machine.memory_mb)), unit="MiB")
    _sub(domain, "vcpu", str(int(machine.cpus)), placement="static")
    if machine.shared_folder:  # virtiofs needs the guest's memory shared with virtiofsd
        backing = _sub(domain, "memoryBacking")
        _sub(backing, "source", type="memfd")
        _sub(backing, "access", mode="shared")

    os_ = _sub(domain, "os", firmware="efi")
    _sub(os_, "type", "hvm", arch="x86_64", machine="q35")
    _sub(os_, "loader", secure="yes")
    _sub(os_, "boot", dev="cdrom")
    _sub(os_, "boot", dev="hd")

    features = _sub(domain, "features")
    _sub(features, "acpi")
    _sub(features, "apic")
    _sub(features, "smm", state="on")
    if machine.windows in ("11", "10"):
        hyperv = _sub(features, "hyperv", mode="custom")
        _sub(hyperv, "relaxed", state="on")
        _sub(hyperv, "vapic", state="on")
        _sub(hyperv, "spinlocks", state="on", retries="8191")
        _sub(hyperv, "vpindex", state="on")
        _sub(hyperv, "synic", state="on")
        _sub(hyperv, "stimer", state="on")
    _sub(domain, "cpu", mode="host-passthrough", check="none")

    clock = _sub(domain, "clock", offset="localtime" if machine.windows != "other" else "utc")
    _sub(clock, "timer", name="rtc", tickpolicy="catchup")
    _sub(clock, "timer", name="pit", tickpolicy="delay")
    _sub(clock, "timer", name="hpet", present="no")
    if machine.windows in ("11", "10"):
        _sub(clock, "timer", name="hypervclock", present="yes")
    _sub(domain, "on_poweroff", "destroy")
    _sub(domain, "on_reboot", "restart")
    _sub(domain, "on_crash", "destroy")

    devices = _sub(domain, "devices")
    hd = _sub(devices, "disk", type="file", device="disk")
    _sub(hd, "driver", name="qemu", type="qcow2", discard="unmap")
    _sub(hd, "source", file=str(disk))
    _sub(hd, "target", dev="vda", bus="virtio")
    letter = "a"
    for media in (machine.iso, machine.drivers_iso):
        if media:
            cd = _sub(devices, "disk", type="file", device="cdrom")
            _sub(cd, "driver", name="qemu", type="raw")
            _sub(cd, "source", file=str(media))
            _sub(cd, "target", dev=f"sd{letter}", bus="sata")
            _sub(cd, "readonly")
            letter = chr(ord(letter) + 1)
    _sub(devices, "controller", type="usb", model="qemu-xhci")
    net = _sub(devices, "interface", type="user")
    _sub(net, "backend", type="passt")
    _sub(net, "model", type="virtio")
    tpm = _sub(devices, "tpm", model="tpm-crb")
    _sub(tpm, "backend", type="emulator", version="2.0")
    graphics = _sub(devices, "graphics", type="spice")
    _sub(graphics, "listen", type="socket")
    _sub(graphics, "image", compression="off")
    video = _sub(devices, "video")
    _sub(video, "model", type="qxl", ram="65536", vram="65536", vgamem="16384", heads="1")
    _sub(devices, "input", type="tablet", bus="usb")
    _sub(devices, "input", type="keyboard", bus="usb")
    _sub(devices, "sound", model="ich9")
    _sub(devices, "memballoon", model="virtio")
    rng = _sub(devices, "rng", model="virtio")
    _sub(rng, "backend", "/dev/urandom", model="random")
    if machine.clipboard:  # the SPICE agent channel: without it, nothing of the clipboard crosses
        channel = _sub(devices, "channel", type="spicevmc")
        _sub(channel, "target", type="virtio", name="com.redhat.spice.0")
    if machine.shared_folder:
        fs = _sub(devices, "filesystem", type="mount", accessmode="passthrough")
        _sub(fs, "driver", type="virtiofs")
        _sub(fs, "source", dir=str(machine.shared_folder))
        _sub(fs, "target", dir="dai-shared")
        if machine.shared_readonly:
            _sub(fs, "readonly")
    for usb_id in machine.usb:
        devices.append(ET.fromstring(usb_hostdev_xml(usb_id)))
    ET.indent(domain)
    return ET.tostring(domain, encoding="unicode") + "\n"


def usb_hostdev_xml(usb_id: str) -> str:
    """The hostdev element for one USB device (vendor:product), for the definition and for live attach."""
    if not USB_ID_RE.match(usb_id):
        raise MachineError(f"a USB id looks like 1234:abcd, not {usb_id}")
    vendor, product = usb_id.split(":")
    return (f'<hostdev mode="subsystem" type="usb" managed="yes"><source><vendor id="0x{vendor}"/>'
            f'<product id="0x{product}"/></source></hostdev>')


def update(machine: Machine, home: Path | None = None) -> Path:
    """Save changed choices and rewrite the definition; returns the definition's path (libvirt redefines it)."""
    machine.validate()
    save(machine, home)
    definition = machine_dir(machine.name, home) / "domain.xml"
    definition.write_text(domain_xml(machine, home), encoding="utf-8")
    return definition


Run = Callable[..., object]


def create(machine: Machine, home: Path | None = None, run: Run | None = None) -> Path:
    """The folder, the disk, the saved choices and the definition; returns the definition's path. `run` is
    subprocess.run or a fake; it is given fixed argv lists."""
    import subprocess

    run = run or subprocess.run
    machine.validate()
    folder = machine_dir(machine.name, home)
    if folder.exists() and any(folder.iterdir()):
        raise MachineError(f"a machine called {machine.name} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    disk = folder / "disk.qcow2"
    result = run(["qemu-img", "create", "-f", "qcow2", str(disk), f"{int(machine.disk_gb)}G"],
                 capture_output=True, text=True, timeout=120)
    if getattr(result, "returncode", 1) != 0:
        raise MachineError(f"qemu-img could not make the disk: {getattr(result, 'stderr', '')[-200:]}")
    save(machine, home)
    definition = folder / "domain.xml"
    definition.write_text(domain_xml(machine, home), encoding="utf-8")
    return definition
