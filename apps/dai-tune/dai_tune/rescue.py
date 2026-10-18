# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Rescue (docs/BASICS.md §2, docs/SNAPSHOTS.md): from the D.Ai USB, when the installed system no longer
starts after an update.

  1. find the installed system: a Btrfs partition (opened first when it is encrypted with LUKS) with "@"
  2. list its update snapshots (snapper, on that disk: --root)
  3. undo the last update, after a safety snapshot of how it is now (so the rescue itself can be undone)

Root only. Nothing is changed before the person confirms; the passphrase goes to cryptsetup on stdin and is
never written anywhere. The disk is unmounted and closed again at the end, whatever happened.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import snapshots
from .context import ActionError, Context

MAPPER = "dai-rescue"
DEVICE = re.compile(r"^/dev/[A-Za-z0-9/_.-]{1,64}$")


@dataclass
class Disk:
    path: str        # /dev/nvme0n1p3
    fstype: str      # btrfs | crypto_LUKS
    size: str = ""
    label: str = ""


def disks(run: Callable = subprocess.run) -> list[Disk]:
    """Partitions that can hold an installed D.Ai: Btrfs, or LUKS (which may hold Btrfs). Not the ones in use."""
    result = run(["lsblk", "-J", "-p", "-o", "PATH,FSTYPE,SIZE,LABEL,MOUNTPOINTS,TYPE"], capture_output=True,
                 text=True)
    try:
        tree = json.loads(result.stdout or "{}").get("blockdevices", [])
    except ValueError:
        return []
    found: list[Disk] = []

    def walk(nodes: list) -> None:
        for node in nodes or []:
            mounted = [m for m in node.get("mountpoints") or [] if m]
            if node.get("fstype") in ("btrfs", "crypto_LUKS") and not mounted:
                path = str(node.get("path") or "")
                if DEVICE.match(path) and not path.startswith(f"/dev/mapper/{MAPPER}"):
                    found.append(Disk(path, node["fstype"], str(node.get("size") or ""), str(node.get("label") or "")))
            walk(node.get("children"))

    walk(tree)
    return found


class Opened:
    """The installed system, mounted read-write under a private folder; closed again on exit."""

    def __init__(self, disk: Disk, passphrase: str | None = None, run: Callable = subprocess.run) -> None:
        if not DEVICE.match(disk.path):
            raise ActionError("not a disk")
        self.disk, self.passphrase, self.run = disk, passphrase, run
        self.device, self.top, self.opened_luks = disk.path, "", False

    def _do(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        result = self.run(argv, capture_output=True, text=True, **kwargs)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
            raise ActionError(f"{argv[0]} failed: {' '.join(detail)}")
        return result

    def __enter__(self) -> "Opened":
        try:
            if self.disk.fstype == "crypto_LUKS":
                if not self.passphrase:
                    raise ActionError("this disk is encrypted: the passphrase is needed")
                self._do(["cryptsetup", "open", "--type", "luks", "--key-file", "-", self.disk.path, MAPPER],
                         input=self.passphrase)
                self.opened_luks, self.device = True, f"/dev/mapper/{MAPPER}"
            self.top = tempfile.mkdtemp(prefix="dai-rescue-")  # 0700
            self._do(["mount", "-o", "subvolid=5", self.device, self.top])  # the whole Btrfs, with "@" inside
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> None:
        if self.top:
            self.run(["umount", self.top], capture_output=True)
            try:
                Path(self.top).rmdir()
            except OSError:
                pass
            self.top = ""
        if self.opened_luks:
            self.run(["cryptsetup", "close", MAPPER], capture_output=True)
            self.opened_luks = False
        self.passphrase = None

    @property
    def root(self) -> str:
        """The installed system's "/" (the "@" subvolume), or "" when this is not a D.Ai/Debian installation."""
        candidate = Path(self.top) / "@"
        return str(candidate) if (candidate / "etc/os-release").is_file() else ""


def _ctx() -> Context:
    return Context(root=Path("/"), home=Path("/root"))


def updates(opened: Opened, ctx: Context | None = None) -> list[dict]:
    """The installed system's snapshots, newest last (empty when snapshots were never turned on)."""
    root = opened.root
    if not root or not (Path(root) / "etc/snapper/configs" / snapshots.CONFIG).is_file():
        return []
    return snapshots.listing(ctx or _ctx(), snapshots.CONFIG, root)


def undo_last_update(opened: Opened, ctx: Context | None = None) -> tuple[int, int, int]:
    """(pre, post, safety): the last update undone, after a snapshot of how it was, to undo the rescue."""
    ctx = ctx or _ctx()
    root = opened.root
    if not root:
        raise ActionError("no installed D.Ai system on this disk")
    if snapshots.last_update(updates(opened, ctx)) is None:
        raise ActionError("there is no update snapshot on this disk to go back to")
    safety = snapshots.create_safety(ctx, snapshots.CONFIG, root)
    pre, post = snapshots.undo_update(ctx, snapshots.CONFIG, root)
    return pre, post, safety


# --------------------------------------------------------------------------
# dai-rescue (as root, from the USB)
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None, run: Callable = subprocess.run, ask: Callable = input,
         secret: Callable | None = None) -> int:
    import getpass
    import sys

    from dai_i18n import pick, text, ui_lang

    lang = ui_lang()
    args = list(sys.argv[1:] if argv is None else argv[1:])
    secret = secret or getpass.getpass
    say = lambda en, he, **kw: print(text(lang, en, he, **kw))  # noqa: E731
    if "--version" in args:
        print("dai-rescue — Diamond Rubinny (d.Ai)")
        return 0
    wanted = args[args.index("--device") + 1] if "--device" in args and args.index("--device") + 1 < len(args) else ""
    found = [d for d in disks(run) if not wanted or d.path == wanted]
    if not found:
        say("No installed D.Ai system was found (a Btrfs or encrypted partition that is not in use).",
            "לא נמצאה מערכת D.Ai מותקנת (מחיצת Btrfs או מוצפנת שלא בשימוש).")
        return 1
    disk = found[0]
    if len(found) > 1:
        for index, item in enumerate(found, 1):
            print(f"  {index}. {item.path}  {item.size}  {item.fstype}  {item.label}")
        choice = ask(pick(lang, "Which one? ", "איזו? ")).strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(found):
            return 1
        disk = found[int(choice) - 1]
    passphrase = secret(pick(lang, "Disk passphrase: ", "סיסמת ההצפנה של הדיסק: ")) \
        if disk.fstype == "crypto_LUKS" else None
    try:
        with Opened(disk, passphrase, run) as opened:
            if not opened.root:
                say("{path} is not an installed D.Ai system.", "‏{path} אינה מערכת D.Ai מותקנת.", path=disk.path)
                return 1
            rows = updates(opened)
            pair = snapshots.last_update(rows)
            if pair is None:
                say("This system has no update snapshots, so there is nothing to undo from here.",
                    "למערכת הזו אין תמונות מצב של עדכונים, ולכן אין מה לבטל מכאן.")
                return 1
            when = next((str(r.get("date", "")) for r in rows if r.get("number") == pair[1]), "")
            say("The last update was on {when} (snapshots {pre}..{post}).",
                "העדכון האחרון היה ב־{when} (תמונות מצב {pre}..{post}).", when=when, pre=pair[0], post=pair[1])
            if "--undo-last-update" not in args:
                return 0
            if "--yes" not in args and ask(pick(lang, "Undo it now? [y/N] ", "לבטל אותו עכשיו? [כ/ל] ")).strip() \
                    .casefold() not in ("y", "yes", "כ", "כן"):
                return 1
            pre, post, safety = undo_last_update(opened)
            say("✓ Undone. Restart without the USB. (To go back to how it was before this rescue: "
                "snapshot {safety}.)", "✓ בוטל. הפעילו מחדש בלי ה־USB. (כדי לחזור למצב שלפני השחזור: "
                "תמונת מצב {safety}.)", safety=safety)
            return 0
    except ActionError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

