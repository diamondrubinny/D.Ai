# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Fakes for the D.Ai VM tests: a computer (/proc, /dev, firmware files), an ISO, virsh and qemu-img."""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

from dai_vm import control, hardware

_real_check = hardware.check  # tests may patch hardware.check with a fake that calls this one


def fake_root(root: Path, flags: str = "fpu vmx sse2", mem_kb: int = 16_000_000, kvm: bool = True,
              firmware: bool = True) -> Path:
    (root / "proc").mkdir(parents=True, exist_ok=True)
    (root / "proc/cpuinfo").write_text(f"processor\t: 0\nflags\t\t: {flags}\n", encoding="utf-8")
    (root / "proc/meminfo").write_text(f"MemTotal:       {mem_kb} kB\nMemAvailable:   {mem_kb // 2} kB\n", encoding="utf-8")
    (root / "dev").mkdir(exist_ok=True)
    (root / "dev/kvm").unlink(missing_ok=True)
    if kvm:
        (root / "dev/kvm").write_bytes(b"")
    (root / "usr/share/OVMF").mkdir(parents=True, exist_ok=True)
    (root / "usr/share/OVMF/OVMF_CODE_4M.ms.fd").unlink(missing_ok=True)
    if firmware:
        (root / "usr/share/OVMF/OVMF_CODE_4M.ms.fd").write_bytes(b"\0")
    return root


def fake_iso(path: Path, label: str = "CCCOMA_X64FRE_EN-US_DV9", size: int = 60 * 1024 * 1024) -> Path:
    with open(path, "wb") as handle:
        handle.truncate(size)
        handle.seek(32768)
        block = bytearray(2048)
        block[0:6] = b"\x01CD001"
        block[40:72] = label.encode("ascii").ljust(32)
        handle.write(block)
    return path


def tools_present(name: str) -> str:
    return f"/usr/bin/{name}"


def plenty_of_disk(_path) -> float:
    return 500.0


def check(lang: str, root: Path, home: Path, **kwargs) -> hardware.Report:
    """The hardware check on a fake computer: every tool present, KVM usable and plenty of disk unless said otherwise."""
    kwargs.setdefault("which", tools_present)
    kwargs.setdefault("access", lambda p, m: True)
    kwargs.setdefault("disk_free", plenty_of_disk)
    return _real_check(lang, root=root, home=home, **kwargs)


class FakeRun:
    """qemu-img and virsh, remembered: machines are defined, started and stopped in a dict."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.states: dict[str, str] = {}
        self.fail: set[str] = set()

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "qemu-img":
            Path(argv[4]).write_bytes(b"QFI\xfb")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] != "virsh":
            return subprocess.CompletedProcess(argv, 1, "", "unknown program")
        verb, rest = argv[3], argv[4:]
        if verb in self.fail:
            return subprocess.CompletedProcess(argv, 1, "", f"error: {verb} refused")
        if verb == "define":
            name = Path(rest[0]).parent.name
            self.states[f"dai-{name}"] = "shut off"
            return subprocess.CompletedProcess(argv, 0, "Domain defined\n", "")
        if verb == "list":
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.states) + "\n", "")
        name = rest[0]
        if name not in self.states:
            return subprocess.CompletedProcess(argv, 1, "", "error: failed to get domain")
        if verb == "domstate":
            return subprocess.CompletedProcess(argv, 0, self.states[name] + "\n", "")
        if verb == "start":
            self.states[name] = "running"
        elif verb in ("shutdown", "destroy"):
            self.states[name] = "shut off"
        elif verb == "suspend":
            self.states[name] = "paused"
        elif verb == "resume":
            self.states[name] = "running"
        elif verb == "domdisplay":
            return subprocess.CompletedProcess(argv, 0, f"spice+unix:///run/user/1000/libvirt/{name}.sock\n", "")
        elif verb == "undefine":
            del self.states[name]
        return subprocess.CompletedProcess(argv, 0, "", "")


def virsh_with(run: FakeRun) -> control.Virsh:
    v = control.Virsh(run)
    v.available = lambda: True  # type: ignore[method-assign]
    return v


class FakeFetch:
    """An https download: the bytes given, in chunks."""

    def __init__(self, data: bytes):
        self.data, self.urls = data, []

    def __call__(self, url: str):
        self.urls.append(url)
        return io.BytesIO(self.data)
