# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The installation media the person brings (docs/VM.md §0): D.Ai never downloads Windows. This module reads
what an ISO says about itself (its label), so the wizard can show it, and computes the SHA-256 for the person
to compare with the page they downloaded it from.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PVD_OFFSET = 32768           # the ISO 9660 primary volume descriptor
PVD_MAGIC = b"\x01CD001"
MIN_SIZE = 50 * 1024 * 1024  # smaller than this is not an installation image
WINDOWS_HINTS = re.compile(r"X64FRE|X86FRE|CCCOMA|CPBA_|CENA_|CESA_|ESD-ISO|J_CCSA|_SV_|WIN(?:DOWS)?[_ ]?(?:1[01]|7|8)", re.I)


@dataclass
class Iso:
    path: str
    label: str
    size: int
    windows_hint: bool

    @property
    def name(self) -> str:
        return Path(self.path).name


class IsoError(ValueError):
    pass


def read_label(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(PVD_OFFSET)
            block = handle.read(2048)
    except OSError as exc:
        raise IsoError(f"cannot read {path.name}") from exc
    if not block.startswith(PVD_MAGIC):
        raise IsoError(f"{path.name} is not an ISO image")
    return block[40:72].decode("ascii", "replace").strip()


def inspect(path: str | Path) -> Iso:
    p = Path(path)
    if not p.is_file():
        raise IsoError(f"{p.name} does not exist")
    size = p.stat().st_size
    if size < MIN_SIZE:
        raise IsoError(f"{p.name} is too small to be installation media")
    label = read_label(p)
    return Iso(str(p), label, size, bool(WINDOWS_HINTS.search(label)))


def sha256(path: str | Path, progress: Callable[[int, int], None] | None = None) -> str:
    p = Path(path)
    total = p.stat().st_size
    digest = hashlib.sha256()
    done = 0
    with open(p, "rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return digest.hexdigest()
