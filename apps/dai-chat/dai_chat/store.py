# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Contacts and messages, on this computer only (docs/SEND.md §3, "Storage and privacy").

~/.local/share/dai/chat/: chat.db and pictures/, in a 0700 folder, files 0600, on the encrypted disk.
History is kept until you delete it (the approved choice); deleting a conversation deletes it here only.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .invite import Invite
from .message import MIMES, PICTURE, TEXT, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    public BLOB PRIMARY KEY CHECK (length(public) = 32),
    name TEXT NOT NULL,
    onion TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    added REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT NOT NULL,
    contact BLOB NOT NULL REFERENCES contacts(public) ON DELETE CASCADE,
    outgoing INTEGER NOT NULL,
    kind INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    picture TEXT NOT NULL DEFAULT '',
    time REAL NOT NULL,
    state TEXT NOT NULL,
    PRIMARY KEY (contact, id)
);
CREATE INDEX IF NOT EXISTS by_contact ON messages(contact, time);
CREATE TABLE IF NOT EXISTS waiting (
    fpr BLOB PRIMARY KEY CHECK (length(fpr) = 10),
    service BLOB NOT NULL CHECK (length(service) = 32),
    name TEXT NOT NULL,
    added REAL NOT NULL
);
"""
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


@dataclass
class Contact:
    public: bytes
    name: str
    onion: str = ""
    verified: bool = False
    blocked: bool = False


def default_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "dai" / "chat"


class Store:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder or default_dir()
        self.pictures = self.folder / "pictures"
        self.pictures.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        os.chmod(self.pictures, 0o700)
        path = self.folder / "chat.db"
        if not path.exists():
            os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")  # the window and the background service share it
        self.db.executescript(SCHEMA)

    # contacts
    def add_contact(self, contact: Contact) -> None:
        with self.db:
            # an upsert, not INSERT OR REPLACE: a replace deletes the row, and the cascade the history with it
            self.db.execute("INSERT INTO contacts VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(public) DO UPDATE SET "
                            "name = excluded.name, onion = excluded.onion, verified = excluded.verified, "
                            "blocked = excluded.blocked",
                            (contact.public, contact.name.strip()[:80] or "?", contact.onion, int(contact.verified),
                             int(contact.blocked), time.time()))

    def contact(self, public: bytes) -> Contact | None:
        row = self.db.execute("SELECT public, name, onion, verified, blocked FROM contacts WHERE public = ?",
                              (public,)).fetchone()
        return Contact(row[0], row[1], row[2], bool(row[3]), bool(row[4])) if row else None

    def contacts(self) -> list[Contact]:
        rows = self.db.execute("SELECT public, name, onion, verified, blocked FROM contacts ORDER BY name").fetchall()
        return [Contact(r[0], r[1], r[2], bool(r[3]), bool(r[4])) for r in rows]

    def may_talk(self, public: bytes) -> bool:
        """Only known, unblocked contacts get through the handshake (session.Responder)."""
        contact = self.contact(public)
        return contact is not None and not contact.blocked

    def set_verified(self, public: bytes, verified: bool = True) -> None:
        with self.db:
            self.db.execute("UPDATE contacts SET verified = ? WHERE public = ?", (int(verified), public))

    def set_blocked(self, public: bytes, blocked: bool = True) -> None:
        with self.db:
            self.db.execute("UPDATE contacts SET blocked = ? WHERE public = ?", (int(blocked), public))

    # codes we typed, waiting for the other person to type ours (pairing.py)
    def wait_for(self, invite: Invite, name: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO waiting VALUES (?, ?, ?, ?)",
                            (invite.fingerprint, invite.service_key, name.strip()[:80] or "?", time.time()))

    def waiting_for(self, fpr: bytes) -> Invite | None:
        row = self.db.execute("SELECT service, fpr FROM waiting WHERE fpr = ?", (fpr,)).fetchone()
        return Invite(row[0], row[1]) if row else None

    def waiting(self) -> list[tuple[Invite, str]]:
        rows = self.db.execute("SELECT service, fpr, name FROM waiting ORDER BY added").fetchall()
        return [(Invite(r[0], r[1]), r[2]) for r in rows]

    def cancel_waiting(self, fpr: bytes) -> None:
        with self.db:
            self.db.execute("DELETE FROM waiting WHERE fpr = ?", (fpr,))

    def paired(self, fpr: bytes, public: bytes) -> Contact | None:
        """The other person's key arrived and matched the code: they become an (unverified) contact."""
        row = self.db.execute("SELECT service, name FROM waiting WHERE fpr = ?", (fpr,)).fetchone()
        if row is None:
            return None
        known = self.contact(public)
        contact = Contact(public, known.name if known else row[1], Invite(row[0], fpr).onion,
                          verified=bool(known and known.verified), blocked=bool(known and known.blocked))
        self.add_contact(contact)
        self.cancel_waiting(fpr)
        return contact

    # messages
    def add_message(self, contact: bytes, message: Message, outgoing: bool, state: str) -> None:
        """Keeps a message; a message id belongs to one contact, so another contact cannot reuse or touch it."""
        picture = ""
        if self.has_message(contact, message.id):
            return  # sent again (a retry after a lost receipt): already here
        if message.mime in MIMES:
            # the id is 32 hex digits and the prefix is hex too: a safe name, unique per contact
            path = self.pictures / f"{contact.hex()[:16]}-{message.id}{EXTENSIONS[message.mime]}"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(message.body)
            picture = path.name
        text = message.body.decode("utf-8") if message.kind == TEXT else ""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (message.id, contact, int(outgoing), message.kind, text, picture, message.time, state))

    def has_message(self, contact: bytes, message_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM messages WHERE contact = ? AND id = ?",
                               (contact, message_id)).fetchone() is not None

    def set_state(self, contact: bytes, message_id: str, state: str) -> None:
        """Only the contact a message was sent to can mark it delivered, seen or refused."""
        with self.db:
            self.db.execute("UPDATE messages SET state = ? WHERE contact = ? AND id = ? AND outgoing = 1",
                            (state, contact, message_id))

    def outgoing(self, contact: bytes, message_id: str) -> Message | None:
        """A queued message as it is sent again: the same id and time, so the other side keeps it once."""
        row = self.db.execute("SELECT kind, text, picture, time FROM messages WHERE contact = ? AND id = ? "
                              "AND outgoing = 1", (contact, message_id)).fetchone()
        if not row:
            return None
        kind, text, picture, when = row
        if kind == PICTURE:
            mime = next(m for m, ext in EXTENSIONS.items() if picture.endswith(ext))
            return Message(PICTURE, (self.pictures / picture).read_bytes(), message_id, when, mime=mime)
        return Message(TEXT, text.encode("utf-8"), message_id, when)

    def conversation(self, contact: bytes, limit: int = 500) -> list[dict]:
        rows = self.db.execute("SELECT id, outgoing, kind, text, picture, time, state FROM messages "
                               "WHERE contact = ? ORDER BY time DESC LIMIT ?", (contact, limit)).fetchall()
        keys = ("id", "outgoing", "kind", "text", "picture", "time", "state")
        return [dict(zip(keys, row)) for row in reversed(rows)]

    def queued(self, contact: bytes) -> list[str]:
        """Outgoing messages still waiting for the contact to come online, oldest first."""
        rows = self.db.execute("SELECT id FROM messages WHERE contact = ? AND outgoing = 1 AND state = 'queued' "
                               "ORDER BY time", (contact,)).fetchall()
        return [row[0] for row in rows]

    def delete_conversation(self, contact: bytes) -> int:
        """Deletes it here, pictures included; the other person keeps their copy (the window says so)."""
        names = [r[0] for r in self.db.execute("SELECT picture FROM messages WHERE contact = ? AND picture != ''",
                                               (contact,))]
        with self.db:
            count = self.db.execute("DELETE FROM messages WHERE contact = ?", (contact,)).rowcount
        for name in names:
            try:
                (self.pictures / name).unlink()
            except OSError:
                pass
        return count

    def close(self) -> None:
        self.db.close()
