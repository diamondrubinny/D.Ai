# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Start, stop, pause: libvirt through `virsh`, always on qemu:///session (the person's own machines, no
root), always as fixed argument lists. States are libvirt's words, kept as they are: running, paused,
shut off, missing (not defined)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .machine import domain_name

URI = "qemu:///session"
Run = Callable[..., subprocess.CompletedProcess]


class VmError(RuntimeError):
    pass


class Virsh:
    def __init__(self, run: Run = subprocess.run, uri: str = URI) -> None:
        self.run, self.uri = run, uri

    def _call(self, *args: str, check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
        argv = ["virsh", "-c", self.uri, *args]
        try:
            result = self.run(argv, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VmError(f"virsh {args[0]}: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:] or [""]
            raise VmError(f"virsh {args[0]}: {detail[0]}")
        return result

    def available(self) -> bool:
        return shutil.which("virsh") is not None

    def define(self, definition: Path) -> None:
        self._call("define", str(definition))

    def undefine(self, name: str) -> None:
        self._call("undefine", domain_name(name), "--nvram", "--tpm", check=False)

    def state(self, name: str) -> str:
        result = self._call("domstate", domain_name(name), check=False, timeout=30)
        if result.returncode != 0:
            return "missing"
        return (result.stdout or "").strip() or "missing"

    def start(self, name: str) -> None:
        self._call("start", domain_name(name), timeout=120)

    def shutdown(self, name: str) -> None:
        """ACPI: Windows gets to shut down properly."""
        self._call("shutdown", domain_name(name))

    def poweroff(self, name: str) -> None:
        """The plug pulled: only when shutdown did not help."""
        self._call("destroy", domain_name(name))

    def pause(self, name: str) -> None:
        self._call("suspend", domain_name(name))

    def resume(self, name: str) -> None:
        self._call("resume", domain_name(name))

    def display(self, name: str) -> str:
        """The SPICE address for the viewer (spice+unix://... in session mode)."""
        result = self._call("domdisplay", domain_name(name), timeout=30)
        uri = (result.stdout or "").strip()
        if not uri:
            raise VmError("the machine has no display yet")
        return uri

    def defined(self) -> list[str]:
        result = self._call("list", "--all", "--name", check=False, timeout=30)
        return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]

    # --- stage 2: sharing, USB, snapshots ---------------------------------------------------------------------

    def redefine(self, definition: Path) -> None:
        """A changed definition: libvirt replaces the stored one; a running machine takes it at its next start."""
        self._call("define", str(definition))

    def _usb_file(self, usb_id: str) -> Path:
        from .machine import usb_hostdev_xml

        path = Path(tempfile.gettempdir()) / f"dai-vm-usb-{os.getpid()}-{usb_id.replace(':', '-')}.xml"
        path.write_text(usb_hostdev_xml(usb_id), encoding="utf-8")
        return path

    def attach_usb(self, name: str, usb_id: str) -> None:
        """The device goes to the running machine now (it leaves D.Ai while Windows has it)."""
        path = self._usb_file(usb_id)
        try:
            self._call("attach-device", domain_name(name), str(path), "--live", timeout=30)
        finally:
            path.unlink(missing_ok=True)

    def detach_usb(self, name: str, usb_id: str) -> None:
        path = self._usb_file(usb_id)
        try:
            self._call("detach-device", domain_name(name), str(path), "--live", timeout=30)
        finally:
            path.unlink(missing_ok=True)

    def snapshot_take(self, name: str, label: str, description: str = "") -> None:
        """An internal qcow2 snapshot (disk, and memory when running), named by the person."""
        args = ["snapshot-create-as", domain_name(name), "--name", label]
        if description:
            args += ["--description", description]
        self._call(*args, timeout=600)

    def snapshots(self, name: str) -> list[dict]:
        result = self._call("snapshot-list", domain_name(name), "--name", check=False, timeout=30)
        if result.returncode != 0:
            return []
        out = []
        for line in (result.stdout or "").splitlines():
            label = line.strip()
            if not label:
                continue
            info = self._call("snapshot-info", domain_name(name), "--snapshotname", label, check=False, timeout=30)
            fields = {}
            for row in (info.stdout or "").splitlines():
                if ":" in row:
                    key, value = row.split(":", 1)
                    fields[key.strip().lower()] = value.strip()
            out.append({"label": label, "when": fields.get("creation time", ""), "state": fields.get("state", ""),
                        "current": fields.get("current", "").lower() == "yes"})
        return out

    def snapshot_revert(self, name: str, label: str) -> None:
        self._call("snapshot-revert", domain_name(name), "--snapshotname", label, timeout=600)

    def snapshot_delete(self, name: str, label: str) -> None:
        self._call("snapshot-delete", domain_name(name), "--snapshotname", label, timeout=600)


def viewer_argv(title: str, uri: str) -> list[str]:
    return ["remote-viewer", "--title", title, uri]
