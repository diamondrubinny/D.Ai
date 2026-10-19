# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Start, stop, pause: libvirt through `virsh`, always on qemu:///session (the person's own machines, no
root), always as fixed argument lists. States are libvirt's words, kept as they are: running, paused,
shut off, missing (not defined)."""
from __future__ import annotations

import shutil
import subprocess
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


def viewer_argv(title: str, uri: str) -> list[str]:
    return ["remote-viewer", "--title", title, uri]
