# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond Chat from D.Ai Command: "send Dana: see you at six" / "שלח לדנה: מגיעה בשש".

The message is put in the queue from inside the command bar's own process, never handed to another program
on its command line (every user on the computer can read command lines in `ps`).
"""
from __future__ import annotations

import re
from pathlib import Path

from .store import Contact, Store, default_dir

SEND = re.compile(r"^\s*(?:send|message|tell|write to)\s+(?:to\s+)?(?P<name>[^:]{1,40}?)\s*:\s*(?P<text>\S.*)$|"
                  r"^\s*(?:שלח|שלחי|תשלח|תשלחי|כתוב|כתבי)\s+(?:הודעה\s+)?(?:אל\s+)?(?P<hname>[^:]{1,40}?)\s*:\s*"
                  r"(?P<htext>\S.*)$", re.IGNORECASE | re.DOTALL)


def parse(text: str) -> tuple[list[str], str] | None:
    """(the names it may mean, the message), or None when it is not a "send NAME: text"."""
    found = SEND.match(text)
    if not found:
        return None
    if found.group("name"):
        return [found.group("name").strip()], found.group("text").strip()
    name = found.group("hname").strip()
    names = [name]
    for prefix in ("ל־", "ל-", "ל"):  # "לדנה" is "to Dana"; "לאה" may also be a name: try both
        if name.startswith(prefix) and len(name) > len(prefix):
            names.insert(0, name[len(prefix):])
            break
    return names, found.group("htext").strip()


def find_contact(names: list[str], folder: Path | None = None) -> Contact | None:
    """The contact one of the names means, only when Diamond Chat was set up (nothing is created here)."""
    from .cli import find

    folder = folder or default_dir()
    if not (folder / "chat.db").exists():
        return None
    store = Store(folder)
    try:
        for name in names:
            contact = find(store, name)
            if contact is not None and not contact.blocked:
                return contact
        return None
    finally:
        store.close()


def send_text(public: bytes, words: str, folder: Path | None = None) -> bool:
    """Queues the message and tells the service; False when it is not running (it waits, and goes later)."""
    from .cli import control_path
    from .message import Message
    from .service import poke

    store = Store(folder or default_dir())
    try:
        store.add_message(public, Message.text(words), outgoing=True, state="queued")
    finally:
        store.close()
    return poke(control_path()) is not None
