# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Mail kept on this computer (docs/MAIL.md §11): importing mbox and Maildir into J's local folders.

The other app's files are only read (Python's mailbox module, never locked or
written). Each message is copied into J's own store (SQLite, 0600) under the
account "local" ("On this computer"), headers and body together, so it stays
readable without the other app or any server. Importing the same folder again
adds only what is new (by Message-ID). Messages Thunderbird marked deleted but
did not compact yet are skipped, and nothing over 50 MB is copied.
"""

from __future__ import annotations

import mailbox
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .mail import parse_header

LOCAL = "local"                 # the account id of the local folders
MAX_MESSAGE = 50 * 2**20
MAX_FOLDER_NAME = 120
MOZILLA_READ, MOZILLA_FLAGGED, MOZILLA_DELETED = 0x0001, 0x0004, 0x0008
NOT_MBOX = {".msf", ".dat", ".json", ".sqlite", ".html", ".js", ".log", ".bak"}


@dataclass
class Source:
    """One folder of mail another app keeps on this computer."""
    app: str          # thunderbird, betterbird, evolution, file
    name: str         # the folder name in J, e.g. "Thunderbird/Inbox"
    path: Path
    kind: str         # mbox or maildir


@dataclass
class Result:
    added: int = 0
    skipped: int = 0  # already in J, deleted in the other app, or too big
    folders: list[str] = field(default_factory=list)


def _clean_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f\x7f‎‏‪-‮⁦-⁩]", "", name).strip().strip("/")
    return name[:MAX_FOLDER_NAME] or "Imported"


def _is_mbox(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() in NOT_MBOX or path.stat().st_size == 0:
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"From "
    except OSError:
        return False


def _is_maildir(path: Path) -> bool:
    return all((path / sub).is_dir() for sub in ("cur", "new"))


def mozilla_folders(app: str, profile: Path) -> list[Source]:
    """Local Folders and POP accounts of a Thunderbird or Betterbird profile (IMAP mail stays on its server)."""
    found = []
    mail = profile / "Mail"
    for account in sorted(mail.iterdir()) if mail.is_dir() else []:
        if not account.is_dir():
            continue
        label = "Local Folders" if account.name == "Local Folders" else account.name
        for path in sorted(account.rglob("*")):
            if _is_mbox(path):
                relative = path.relative_to(account)
                parts = [p[:-4] if p.endswith(".sbd") else p for p in relative.parts]  # Inbox.sbd/Work -> Inbox/Work
                found.append(Source(app, _clean_name(f"{app.capitalize()}/{label}/{'/'.join(parts)}"), path, "mbox"))
    return found


def evolution_folders(home: Path) -> list[Source]:
    root = home / ".local/share/evolution/mail/local"
    if not _is_maildir(root):
        return []
    found = [Source("evolution", "Evolution/Inbox", root, "maildir")]
    for path in sorted(root.iterdir()):
        if path.name.startswith(".") and _is_maildir(path):  # Maildir++ subfolders: ".Work.Projects"
            found.append(Source("evolution", _clean_name("Evolution/" + path.name[1:].replace(".", "/")), path,
                                "maildir"))
    return found


def find_sources(home: Path | None = None) -> list[Source]:
    from .importers import thunderbird_profiles

    home = home or Path.home()
    found: list[Source] = []
    for app, prefs in thunderbird_profiles(home):
        found += mozilla_folders(app, prefs.parent)
    return found + evolution_folders(home)


def source_for_path(path: Path) -> Source | None:
    """An mbox file or a Maildir folder the person picked."""
    path = path.expanduser()
    if _is_maildir(path):
        return Source("file", _clean_name(f"Imported/{path.name}"), path, "maildir")
    if _is_mbox(path):
        return Source("file", _clean_name(f"Imported/{path.stem or path.name}"), path, "mbox")
    return None


def _messages(source: Source) -> Iterator[tuple[bytes, str] | None]:
    """(raw message, IMAP-style flags), or None for one that must not be copied."""
    box = mailbox.mbox(source.path, create=False) if source.kind == "mbox" else \
        mailbox.Maildir(source.path, factory=None, create=False)
    for key in box.iterkeys():
        try:
            message = box.get_message(key)
            raw = message.as_bytes()
        except (OSError, ValueError, LookupError):
            yield None
            continue
        if len(raw) > MAX_MESSAGE:
            yield None
            continue
        flags = set(message.get_flags())  # mbox: Status/X-Status; Maildir: the info part of the file name
        mozilla = message.get("X-Mozilla-Status", "")
        if re.fullmatch(r"[0-9a-fA-F]{4}", mozilla.strip()):
            bits = int(mozilla, 16)
            if bits & MOZILLA_DELETED:
                yield None  # deleted in Thunderbird, kept until it compacts the folder
                continue
            flags |= {"R"} if bits & MOZILLA_READ else set()
            flags |= {"F"} if bits & MOZILLA_FLAGGED else set()
        seen = "R" in flags or "S" in flags
        yield raw, " ".join(f for f, on in (("\\Seen", seen), ("\\Flagged", "F" in flags)) if on)


def import_source(store, source: Source, progress: Callable[[int], None] | None = None) -> Result:
    """Copy one folder into J's local folders; only what is new is added."""
    result = Result(folders=[source.name])
    folders = dict(store.folders(LOCAL))
    folders[source.name] = folders.get(source.name, "")
    store.set_folders(LOCAL, sorted(folders.items()))
    known = {row["message_id"] for row in store.listing([LOCAL], folder=source.name, limit=10**9) if row["message_id"]}
    uid = store.last_uid(LOCAL, source.name)
    for item in _messages(source):
        if item is None:
            result.skipped += 1
            continue
        raw, flags = item
        header = parse_header(uid + 1, flags, raw)
        if header.message_id and header.message_id in known:
            result.skipped += 1
            continue
        uid += 1
        store.add(LOCAL, source.name, [header])
        store.set_body(LOCAL, source.name, uid, raw)
        known.add(header.message_id)
        result.added += 1
        if progress and result.added % 100 == 0:
            progress(result.added)
    return result
