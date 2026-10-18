# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What J does with an account, without any window: sync, open, delete, send.

The window runs these off its thread. Each call opens its own store
connection (SQLite objects stay in one thread) and its own IMAP session.
"""

from __future__ import annotations

from pathlib import Path

from . import compose, mail
from .accounts import Account
from .store import Store

SYNCED_ROLES = ("inbox", "sent", "drafts", "trash", "junk", "archive")
FLAG_WINDOW = 500   # the newest messages whose read/unread state is refreshed on every sync


def sync_folder(imap: mail.Imap, store: Store, account: Account, folder: str) -> int:
    """New headers and current flags of one folder; returns how many new messages arrived."""
    validity = imap.select(folder)
    store.validate(account.id, folder, validity)
    known = sorted(store.uids(account.id, folder))[-FLAG_WINDOW:]
    if known:
        store.update_flags(account.id, folder, imap.flags(known), known)
    new = imap.headers(store.last_uid(account.id, folder))
    store.add(account.id, folder, new)
    return len(new)


def sync(account: Account, password: str, db: Path, folder: str | None = None, factory=None) -> dict:
    """Signs in, refreshes the folder list and the main folders (or just `folder`)."""
    store = Store(db)
    try:
        with mail.Imap(account.incoming, password, factory) as imap:
            folders = imap.folders()
            store.set_folders(account.id, [(f.name, f.role) for f in folders if f.selectable])
            account.folders = {f.role: f.name for f in folders if f.role and f.role != "inbox"}
            wanted = [folder] if folder else [f.name for f in folders if f.selectable and f.role in SYNCED_ROLES]
            arrived = {name: sync_folder(imap, store, account, name) for name in wanted}
        return {"arrived": arrived, "folders": [(f.name, f.role) for f in folders if f.selectable]}
    finally:
        store.close()


def open_message(account: Account, password: str, db: Path, folder: str, uid: int, factory=None) -> mail.Body:
    """The message body, from the local copy or the server; marks it read."""
    store = Store(db)
    try:
        raw = store.body(account.id, folder, uid)
        if raw is None:
            with mail.Imap(account.incoming, password, factory) as imap:
                imap.select(folder, readonly=False)
                raw = imap.body(uid)
                imap.set_flag(uid, "\\Seen")
            store.set_body(account.id, folder, uid, raw)
        store.set_seen(account.id, folder, uid)
        return mail.parse_body(raw)
    finally:
        store.close()


def delete(account: Account, password: str, db: Path, folder: str, uid: int, factory=None) -> None:
    """To the trash; from the trash itself, deleted for good."""
    trash = account.folders.get("trash")
    store = Store(db)
    try:
        with mail.Imap(account.incoming, password, factory) as imap:
            imap.select(folder, readonly=False)
            if trash and folder != trash:
                imap.move(uid, trash)
            else:
                imap.set_flag(uid, "\\Deleted")
                imap.conn.expunge()
        store.remove(account.id, folder, uid)
    finally:
        store.close()


def send(account: Account, password: str, draft: compose.Draft, smtp_factory=None, imap_factory=None) -> None:
    draft.sender_name = draft.sender_name or account.name
    draft.sender_address = account.address
    message = compose.build(draft)
    raw = None
    if draft.sign or draft.encrypt:  # before anything leaves: a missing key stops it here
        from . import pgp

        try:
            raw = pgp.protect(message, draft.sign, draft.encrypt)
        except pgp.ProtectError as exc:
            raise mail.MailError(f"pgp_{exc}") from None
    rcpt = [a for _, a in compose.recipients(draft.to)[0] + compose.recipients(draft.cc)[0]]
    mail.send(account.outgoing, password, raw if raw is not None else message, smtp_factory,
              envelope=(account.address, rcpt))
    sent = account.folders.get("sent")
    if sent and not account.incoming.host.endswith("gmail.com"):  # Gmail files sent mail by itself
        try:
            with mail.Imap(account.incoming, password, imap_factory) as imap:
                imap.append(sent, raw if raw is not None else message.as_bytes())
        except mail.MailError:
            pass  # it was sent; only the copy in "Sent" is missing
