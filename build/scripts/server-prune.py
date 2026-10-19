#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Turns the shared live-build configuration into the D.Ai Server configuration (docs/SERVER.md §2, §4).

build-iso.sh copies build/live-build/common into the build tree, then the edition on top. For the server
edition, this script runs in between and removes what a server must not carry: the desktop, the graphical
apps, the installer, the desktop-only boot hooks, and the radio and pointer-device packages (Bluetooth,
Wi-Fi firmware) that a server does not use. It also drops the packages that add an attack surface without a
server's need (pkexec: the polkit helper that has had local privilege-escalation bugs).

Usage: server-prune.py <config-dir>   (the directory build-iso.sh calls config/; run once, before the edition)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Lists that exist only for the desktop. The server edition brings its own list.
DESKTOP_LISTS = ("desktop.list.chroot", "displays.list.optional", "mail.list.optional", "basics.list.optional")

# Hooks that configure the desktop, the installer, or the graphical boot splash. The server edition has its own 0100.
DESKTOP_HOOKS = (
    "0100-dai-system.hook.chroot",
    "0200-dai-theme.hook.chroot",
    "0250-dai-boot-look.hook.chroot",
    "0300-dai-installer.hook.chroot",
)

# Shared files that only the desktop uses (paths relative to config/includes.chroot_after_packages).
DESKTOP_FILES = (
    "etc/sddm.conf.d",
    "etc/skel",
    "etc/swaylock",
    "etc/xdg",
    "etc/calamares",
    "usr/bin/dai-install",
    "usr/bin/dai-keyboard",
    "usr/bin/dai-nightlight",
    "usr/bin/dai-screenshot",
    "usr/bin/startdai-wayland",
    "usr/lib/live/config/9000-dai-sddm-autologin",
    "usr/lib/live/config/9100-dai-installer-icon",
    "usr/share/applications/dai-install.desktop",
    "usr/share/dai/theme",
    "usr/share/dai/branding/wallpaper-night.jpg",
    "usr/share/dai/branding/dai-command.svg",
    "usr/share/plymouth",
    "usr/share/sddm",
    "usr/share/sounds",
)

# Packages the server does not need, removed from the shared base list.
BASE_REMOVED = {
    "bluez",               # Bluetooth: no radio on a server
    "wpasupplicant",       # Wi-Fi client
    "firmware-iwlwifi",    # Wi-Fi firmware
    "firmware-atheros",    # Wi-Fi firmware
    "firmware-amd-graphics",  # graphics firmware
    "pkexec",              # polkit helper: not needed on a server (local privilege-escalation history)
    "systemd-timesyncd",   # replaced by chrony in the server edition
}


def prune_lists(config: Path) -> list[str]:
    removed = []
    lists = config / "package-lists"
    for name in DESKTOP_LISTS:
        path = lists / name
        if path.exists():
            path.unlink()
            removed.append(f"package-lists/{name}")
    base = lists / "base.list.chroot"
    if base.exists():
        kept, dropped = [], []
        for line in base.read_text(encoding="utf-8").splitlines(keepends=True):
            word = line.strip()
            if word and not word.startswith("#") and word in BASE_REMOVED:
                dropped.append(word)
                continue
            kept.append(line)
        base.write_text("".join(kept), encoding="utf-8")
        removed.extend(f"base:{word}" for word in dropped)
    return removed


def prune_hooks(config: Path) -> list[str]:
    removed = []
    hooks = config / "hooks" / "normal"
    for name in DESKTOP_HOOKS:
        path = hooks / name
        if path.exists():
            path.unlink()
            removed.append(f"hooks/normal/{name}")
    return removed


def prune_files(config: Path) -> list[str]:
    removed = []
    root = config / "includes.chroot_after_packages"
    for rel in DESKTOP_FILES:
        path = root / rel
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(rel)
        elif path.exists():
            path.unlink()
            removed.append(rel)
    return removed


def prune(config: Path) -> list[str]:
    """Everything removed, as readable names; the caller prints them."""
    if not (config / "package-lists").is_dir():
        raise SystemExit(f"server-prune: {config} has no package-lists (run after the common layer is copied)")
    return prune_lists(config) + prune_hooks(config) + prune_files(config)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    removed = prune(Path(argv[1]))
    print(f"server-prune: removed {len(removed)} desktop items", file=sys.stderr)
    for item in removed:
        print(f"  - {item}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
