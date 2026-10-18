# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The local copy of the mail (docs/MAIL.md §4): an SQLite file next to the accounts, 0600.

Headers are kept for the folder lists and the unified inbox; a message body is
kept once it was opened. A folder whose UIDVALIDITY changed is emptied, as
IMAP requires. Removing an account removes all of its rows.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .mail import Header

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    account TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', validity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account, name));
CREATE TABLE IF NOT EXISTS messages (
    account TEXT NOT NULL, folder TEXT NOT NULL, uid INTEGER NOT NULL,
    sender TEXT, sender_address TEXT, recipients TEXT, subject TEXT, date REAL,
    seen INTEGER, flagged INTEGER, message_id TEXT, refs TEXT, body BLOB,
    PRIMARY KEY (account, folder, uid));
CREATE INDEX IF NOT EXISTS messages_date ON messages (date DESC);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        new = not path.exists()
        self.db = sqlite3.connect(path, timeout=10)
        if new:
            os.chmod(path, 0o600)
        self.db.execute("PRAGMA secure_delete = ON")  # deleted mail is overwritten, not left in the file
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # Folders

    def set_folders(self, account: str, folders: list[tuple[str, str]]) -> None:
        names = [n for n, _ in folders]
        with self.db:
            self.db.execute(f"DELETE FROM messages WHERE account = ? AND folder NOT IN ({','.join('?' * len(names))})",
                            (account, *names))
            self.db.execute(f"DELETE FROM folders WHERE account = ? AND name NOT IN ({','.join('?' * len(names))})",
                            (account, *names))
            for name, role in folders:
                self.db.execute("INSERT INTO folders (account, name, role) VALUES (?, ?, ?) "
                                "ON CONFLICT (account, name) DO UPDATE SET role = excluded.role", (account, name, role))

    def folders(self, account: str) -> list[tuple[str, str]]:
        return list(self.db.execute("SELECT name, role FROM folders WHERE account = ? ORDER BY role = '', name",
                                    (account,)))

    def validate(self, account: str, folder: str, validity: int) -> bool:
        """False (and the folder emptied) when the server's UIDVALIDITY changed."""
        row = self.db.execute("SELECT validity FROM folders WHERE account = ? AND name = ?", (account, folder)).fetchone()
        same = row is not None and row[0] in (0, validity)
        with self.db:
            if not same:
                self.db.execute("DELETE FROM messages WHERE account = ? AND folder = ?", (account, folder))
            self.db.execute("UPDATE folders SET validity = ? WHERE account = ? AND name = ?", (validity, account, folder))
        return same

    # Messages

    def last_uid(self, account: str, folder: str) -> int:
        row = self.db.execute("SELECT MAX(uid) FROM messages WHERE account = ? AND folder = ?", (account, folder)).fetchone()
        return int(row[0] or 0)

    def uids(self, account: str, folder: str) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT uid FROM messages WHERE account = ? AND folder = ?", (account, folder))]

    def add(self, account: str, folder: str, headers: list[Header]) -> None:
        with self.db:
            self.db.executemany(
                "INSERT INTO messages (account, folder, uid, sender, sender_address, recipients, subject, date, seen, "
                "flagged, message_id, refs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (account, folder, uid) DO UPDATE SET seen = excluded.seen, flagged = excluded.flagged",
                [(account, folder, h.uid, h.sender, h.sender_address, h.to, h.subject, h.date, int(h.seen),
                  int(h.flagged), h.message_id, h.references) for h in headers])

    def update_flags(self, account: str, folder: str, flags: dict[int, str], scope: list[int]) -> None:
        """The server's current flags for the UIDs in `scope`; those it no longer has are removed here too."""
        known = set(scope)
        with self.db:
            for uid in known - set(flags):
                self.db.execute("DELETE FROM messages WHERE account = ? AND folder = ? AND uid = ?", (account, folder, uid))
            for uid, value in flags.items():
                self.db.execute("UPDATE messages SET seen = ?, flagged = ? WHERE account = ? AND folder = ? AND uid = ?",
                                (int("\\Seen" in value), int("\\Flagged" in value), account, folder, uid))

    def set_seen(self, account: str, folder: str, uid: int, seen: bool = True) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET seen = ? WHERE account = ? AND folder = ? AND uid = ?",
                            (int(seen), account, folder, uid))

    def remove(self, account: str, folder: str, uid: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM messages WHERE account = ? AND folder = ? AND uid = ?", (account, folder, uid))

    def set_body(self, account: str, folder: str, uid: int, raw: bytes) -> None:
        with self.db:
            self.db.execute("UPDATE messages SET body = ? WHERE account = ? AND folder = ? AND uid = ?",
                            (raw, account, folder, uid))

    def body(self, account: str, folder: str, uid: int) -> bytes | None:
        row = self.db.execute("SELECT body FROM messages WHERE account = ? AND folder = ? AND uid = ?",
                              (account, folder, uid)).fetchone()
        return bytes(row[0]) if row and row[0] is not None else None

    def listing(self, accounts: list[str], role: str = "", folder: str = "", limit: int = 500) -> list[dict]:
        """Newest first. With a role (e.g. "inbox") across accounts: the unified view."""
        if not accounts:
            return []
        marks = ",".join("?" * len(accounts))
        if role:
            sql = (f"SELECT m.* FROM messages m JOIN folders f ON f.account = m.account AND f.name = m.folder "
                   f"WHERE m.account IN ({marks}) AND f.role = ? ORDER BY m.date DESC LIMIT ?")
            args = (*accounts, role, limit)
        else:
            sql = f"SELECT * FROM messages WHERE account IN ({marks}) AND folder = ? ORDER BY date DESC LIMIT ?"
            args = (*accounts, folder, limit)
        cursor = self.db.execute(sql, args)
        names = [c[0] for c in cursor.description]
        return [{k: v for k, v in zip(names, row) if k != "body"} for row in cursor]

    def unread(self, accounts: list[str], role: str = "inbox") -> int:
        if not accounts:
            return 0
        marks = ",".join("?" * len(accounts))
        row = self.db.execute(f"SELECT COUNT(*) FROM messages m JOIN folders f ON f.account = m.account AND "
                              f"f.name = m.folder WHERE m.account IN ({marks}) AND f.role = ? AND m.seen = 0",
                              (*accounts, role)).fetchone()
        return int(row[0])

    def forget_account(self, account: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM messages WHERE account = ?", (account,))
            self.db.execute("DELETE FROM folders WHERE account = ?", (account,))
        self.db.execute("VACUUM")  # the deleted mail does not linger in free pages
