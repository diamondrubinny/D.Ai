# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Snapshots before updates (docs/SNAPSHOTS.md): snapper on a Btrfs system disk.

Once a snapper config named "root" exists, the hook in the snapper package
(/etc/apt/apt.conf.d/80snapper) takes a "pre" and a "post" snapshot around
every dpkg run, described "apt". D.Ai only creates that config (and only on
Btrfs), and undoes the last such pair on request. Root only (the helper);
snapper runs without D-Bus so it also works where snapperd is not running.
"""

from __future__ import annotations

import json

from .context import ActionError, Context

CONFIG = "root"
NUMBER_LIMIT = "10"
APT_DESCRIPTION = "apt"


def snapper(config: str, *args: str, root: str = "") -> list[str]:
    """snapper without D-Bus; with `root`, on a system that is not running (D.Ai Rescue, from the USB)."""
    return ["snapper", "--no-dbus", *(["--root", root] if root else []), "-c", config, *args]


def filesystem(ctx: Context, path: str = "/") -> str:
    result = ctx.run(["findmnt", "-n", "-o", "FSTYPE", "--target", path], check=False)
    return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""


def enabled(ctx: Context, config: str = CONFIG) -> bool:
    return ctx.path(f"/etc/snapper/configs/{config}").exists()


def enable(ctx: Context, config: str = CONFIG, path: str = "/") -> bool:
    """Create the snapper config; False when it already existed."""
    if not ctx.path("/usr/bin/snapper").exists():
        raise ActionError("snapper is not installed")
    fstype = filesystem(ctx, path)
    if fstype != "btrfs":
        raise ActionError(f"snapshots need a Btrfs disk; {path} is {fstype or 'unknown'} "
                          "(choose Btrfs when installing: docs/SNAPSHOTS.md)")
    if enabled(ctx, config):
        return False
    ctx.run(snapper(config, "create-config", path))
    ctx.run(snapper(config, "set-config", f"NUMBER_LIMIT={NUMBER_LIMIT}", "NUMBER_LIMIT_IMPORTANT=4",
                    "TIMELINE_CREATE=no"))
    return True


def disable(ctx: Context, config: str = CONFIG) -> None:
    if enabled(ctx, config):
        ctx.run(snapper(config, "delete-config"))


def listing(ctx: Context, config: str = CONFIG, root: str = "") -> list[dict]:
    result = ctx.run(snapper(config, "--jsonout", "list", root=root))
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise ActionError("snapper gave an unreadable list") from exc
    rows = data.get(config) if isinstance(data, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def last_update(rows: list[dict]) -> tuple[int, int] | None:
    """(pre, post) of the most recent finished update, from `snapper --jsonout list`."""
    numbers = {row.get("number") for row in rows}
    for row in sorted(rows, key=lambda r: r.get("number") or 0, reverse=True):
        pre = row.get("pre-number", row.get("pre_number"))
        if row.get("type") == "post" and row.get("description") == APT_DESCRIPTION \
                and isinstance(pre, int) and pre in numbers and isinstance(row.get("number"), int):
            return pre, row["number"]
    return None


def create_safety(ctx: Context, config: str = CONFIG, root: str = "") -> int:
    """A snapshot of right now, so undoing the update can be undone too."""
    result = ctx.run(snapper(config, "create", "-t", "single", "-d", "dai: before undoing an update",
                             "-c", "number", "-p", root=root))
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise ActionError("snapper did not report the snapshot number") from exc


def undo_update(ctx: Context, config: str = CONFIG, root: str = "") -> tuple[int, int]:
    pair = last_update(listing(ctx, config, root))
    if pair is None:
        raise ActionError("there is no update snapshot to go back to yet")
    pre, post = pair
    ctx.run(snapper(config, "undochange", f"{pre}..{post}", root=root))
    return pair


def back_to(ctx: Context, number: int, config: str = CONFIG) -> None:
    """Make the system files as they were in snapshot `number` (0 is "now")."""
    ctx.run(snapper(config, "undochange", f"{number}..0"))
