# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Find Windows user folders and copy them safely into the Linux home.

The source is only read. Nothing in the home folder is overwritten: a name
that already exists gets " (Windows)" added. Windows system files and
symlinks are skipped, and the free space is checked before copying.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Windows folder → folder in the Linux home (XDG names stay in English here; the
# file manager shows them translated).
FOLDERS = {"Documents": "Documents", "Pictures": "Pictures", "Desktop": "Desktop", "Music": "Music",
           "Videos": "Videos", "Downloads": "Downloads"}
SKIP_USERS = {"Public", "Default", "Default User", "All Users", "defaultuser0", "WDAGUtilityAccount"}
SKIP_FILES = {"desktop.ini", "thumbs.db", "ntuser.dat", ".ds_store"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "my music", "my pictures", "my videos"}


@dataclass
class WindowsUser:
    root: Path        # the drive or folder that holds Users/
    name: str

    @property
    def home(self) -> Path:
        return self.root / "Users" / self.name if (self.root / "Users").is_dir() else self.root


@dataclass
class Plan:
    copies: list[tuple[Path, Path]] = field(default_factory=list)   # (source file, destination file)
    renamed: int = 0
    skipped: int = 0
    bytes: int = 0


def find_users(roots: list[Path]) -> list[WindowsUser]:
    """Windows installations (or copied user folders) under the given mount points."""
    users = []
    for root in roots:
        users_dir = root / "Users"
        if users_dir.is_dir():
            for entry in sorted(users_dir.iterdir()):
                if entry.is_dir() and not entry.is_symlink() and entry.name not in SKIP_USERS \
                        and any((entry / f).is_dir() for f in FOLDERS):
                    users.append(WindowsUser(root, entry.name))
        elif any((root / f).is_dir() for f in FOLDERS):  # a copied user folder
            users.append(WindowsUser(root, root.name))
    return users


def mount_points(user: str | None = None) -> list[Path]:
    user = user or os.environ.get("USER") or Path.home().name
    points = []
    for base in (Path("/media") / user, Path("/run/media") / user, Path("/mnt")):
        try:
            points += [p for p in sorted(base.iterdir()) if p.is_dir()]
        except OSError:
            continue
    return points


def _free_name(dest: Path, taken: set[Path]) -> tuple[Path, bool]:
    if not dest.exists() and dest not in taken:
        return dest, False
    stem, suffix = dest.stem, dest.suffix
    for n in range(1, 1000):
        label = " (Windows)" if n == 1 else f" (Windows {n})"
        candidate = dest.with_name(f"{stem}{label}{suffix}")
        if not candidate.exists() and candidate not in taken:
            return candidate, True
    raise OSError(f"too many copies of {dest.name}")


def plan(user: WindowsUser, home: Path, folders: list[str] | None = None) -> Plan:
    result = Plan()
    taken: set[Path] = set()
    for windows_name in folders or list(FOLDERS):
        source_root = user.home / windows_name
        if not source_root.is_dir() or source_root.is_symlink():
            continue
        for directory, dirnames, filenames in os.walk(source_root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d.casefold() not in SKIP_DIRS
                           and not os.path.islink(os.path.join(directory, d))]
            for filename in filenames:
                source = Path(directory) / filename
                if filename.casefold() in SKIP_FILES or source.is_symlink() or not source.is_file():
                    result.skipped += 1
                    continue
                relative = source.relative_to(source_root)
                dest, renamed = _free_name(home / FOLDERS[windows_name] / relative, taken)
                taken.add(dest)
                result.copies.append((source, dest))
                result.renamed += renamed
                try:
                    result.bytes += source.stat().st_size
                except OSError:
                    result.skipped += 1
    return result


def execute(work: Plan, home: Path, progress=None) -> tuple[int, list[str]]:
    """Copy the planned files; returns (copied, errors). Existing files are never touched."""
    free = shutil.disk_usage(home).free
    if work.bytes > free * 0.95:
        raise OSError(f"not enough space: need {work.bytes // 2**20} MB, have {free // 2**20} MB")
    copied, errors = 0, []
    for index, (source, dest) in enumerate(work.copies, 1):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise FileExistsError(str(dest))
            shutil.copy2(source, dest, follow_symlinks=False)
            copied += 1
        except OSError as exc:
            errors.append(f"{source}: {exc}")
        if progress:
            progress(index, len(work.copies))
    return copied, errors
