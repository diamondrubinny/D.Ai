# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-chat: Diamond Chat from the command line (the window comes next; docs/SEND.md).

  dai-chat code                 your invitation code, to give someone by phone or in person
  dai-chat add NAME CODE        the code someone gave you (they add yours too)
  dai-chat contacts             your contacts, and the codes still waiting
  dai-chat symbols NAME         the six symbols to compare with NAME, by phone or face to face
  dai-chat verify NAME          after the symbols matched: NAME may now send you pictures
  dai-chat send NAME TEXT...    a message (it waits on this computer until NAME is online)
  dai-chat send-picture NAME FILE   a picture, re-drawn first: its location and camera details are removed
  dai-chat read NAME            the conversation
  dai-chat delete NAME          delete the conversation here (NAME keeps their copy)
  dai-chat block NAME | unblock NAME
  dai-chat lan on|off           find contacts on the local network too (D.Ai Tune opens the port)
  dai-chat on | off             start Diamond Chat (and its Tor) now and at every login, or stop it
  dai-chat status
  dai-chat run                  the background service (started by systemd while Chat is on)
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from dai_i18n import pick, ui_lang

from . import invite, keys, pictures, sas
from .message import MAX_PICTURE, Message
from .store import Contact, Store, default_dir


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def default_stores(folder: Path) -> tuple[list, list]:
    """Where the identity and onion keys live: the keyring first, else 0600 files next to the store."""
    return ([keys.KeyringStore(), keys.FileStore(folder / "identity")],
            [keys.KeyringStore(kind="onion"), keys.FileStore(folder / "onion")])


def control_path() -> Path:
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(run) / "dai-chat" / "app.sock"


def find(store: Store, name: str) -> Contact | None:
    """A contact by name: exactly (ignoring case), or the only one that starts with it."""
    wanted = name.strip().casefold()
    contacts = store.contacts()
    exact = [c for c in contacts if c.name.casefold() == wanted]
    if exact:
        return exact[0]
    starts = [c for c in contacts if c.name.casefold().startswith(wanted)]
    return starts[0] if len(starts) == 1 else None


def main(argv: list[str] | None = None, stores: Callable[[Path], tuple[list, list]] = default_stores,
         out=None) -> int:
    from . import service

    argv = list(sys.argv if argv is None else argv)[1:]
    out = out or sys.stdout
    lang = ui_lang()
    folder = default_dir()

    def show(line: str) -> None:
        print(line, file=out)

    if not argv or argv[0] in ("-h", "--help", "help"):
        show(__doc__.strip())
        return 0
    command, rest = argv[0], argv[1:]
    store = Store(folder)
    try:
        identity_stores, onion_stores = stores(folder)
        me, _ = keys.load_or_create(identity_stores)
        onion_identity, _ = keys.load_or_create(onion_stores)
        onion_seed = onion_identity.seed()

        if command == "code":
            show(service.invite_code(onion_seed, me))
            return 0
        if command == "add" and len(rest) >= 2:
            name, code = rest[0], " ".join(rest[1:])
            try:
                theirs = invite.parse(code)
            except invite.InviteError:
                show(say(lang, "That code has a typo. Check it with {name} and try again.",
                         "בקוד יש שגיאת הקלדה. בדקו אותו מול {name} ונסו שוב.", name=name))
                return 2
            if theirs.matches(me.public):
                show(say(lang, "That is your own code.", "זה הקוד שלכם."))
                return 2
            store.wait_for(theirs, name)
            service.poke(control_path())
            show(say(lang, "Waiting for {name}. Give them your code too: {code}",
                     "ממתינים ל־{name}. תנו להם גם את הקוד שלכם: {code}", name=name,
                     code=service.invite_code(onion_seed, me)))
            return 0
        if command == "contacts":
            for contact in store.contacts():
                state = (say(lang, "blocked", "חסום") if contact.blocked else
                         say(lang, "verified", "מאומת") if contact.verified else
                         say(lang, "not verified: compare the symbols", "לא מאומת: השוו את הסמלים"))
                show(f"{contact.name}  ({state})")
            for _theirs, name in store.waiting():
                show(say(lang, "{name}  (waiting for them to add your code)", "{name}  (ממתינים שיוסיפו את הקוד שלכם)",
                         name=name))
            return 0
        if command == "lan" and rest and rest[0] in ("on", "off"):
            path = service.settings_path()
            settings = service.Settings.load(path)
            settings.lan = rest[0] == "on"
            settings.save(path)
            show(say(lang, "Saved. It takes effect when Chat starts again.",
                     "נשמר. ייכנס לתוקף כש־Chat יופעל מחדש."))
            return 0
        if command in ("on", "off") and not rest:
            verb = ["enable", "--now"] if command == "on" else ["disable", "--now"]
            result = subprocess.run(["systemctl", "--user", *verb, "dai-chat.service"], capture_output=True,
                                    timeout=60)
            if result.returncode != 0:
                show(say(lang, "Could not change the Diamond Chat service.", "לא ניתן לשנות את שירות Diamond Chat."))
                return 1
            show(say(lang, "Diamond Chat is on. Your code: {code}", "Diamond Chat פועל. הקוד שלכם: {code}",
                     code=service.invite_code(onion_seed, me)) if command == "on" else
                 say(lang, "Diamond Chat is off; messages you write wait here.",
                     "Diamond Chat כבוי; הודעות שתכתבו ימתינו כאן."))
            return 0
        if command == "status":
            state = service.poke(control_path(), "status")
            if state is None:
                show(say(lang, "Diamond Chat is not running.", "Diamond Chat לא פועל."))
                return 1
            show(say(lang, "Tor: {tor}. Local network: {lan}. Waiting to send: {queued}. Codes waiting: {waiting}.",
                     "Tor: {tor}. רשת מקומית: {lan}. ממתינות לשליחה: {queued}. קודים ממתינים: {waiting}.",
                     tor=state.get("tor"), lan=state.get("lan"), queued=state.get("queued"),
                     waiting=state.get("waiting")))
            return 0
        if command == "run":
            settings = service.Settings.load(service.settings_path())
            from .discovery import Discovery
            from .tor import Tor

            runner = service.Service(me, onion_seed, store, settings, tor_runner=Tor(),
                                     discovery=Discovery(me.public, service.transport.PORT))

            async def serve() -> None:
                loop, task = asyncio.get_running_loop(), asyncio.current_task()
                for stop in (signal.SIGTERM, signal.SIGINT):  # systemd stops with SIGTERM: Tor goes with us
                    loop.add_signal_handler(stop, task.cancel)
                try:
                    await runner.run_forever(control_path())
                except asyncio.CancelledError:
                    pass

            asyncio.run(serve())
            return 0

        # the rest are about one contact
        if command in ("symbols", "verify", "send", "send-picture", "read", "delete", "block", "unblock") and rest:
            contact = find(store, rest[0])
            if contact is None:
                show(say(lang, "No contact called {name}.", "אין איש קשר בשם {name}.", name=rest[0]))
                return 2
            if command == "symbols":
                show(sas.describe(sas.symbols(me.public, contact.public), lang))
                show(say(lang, "{name} should see the same six, in the same order. Then: dai-chat verify {name}",
                         "אצל {name} צריכים להופיע אותם שישה, באותו סדר. ואז: dai-chat verify {name}",
                         name=contact.name))
                return 0
            if command == "verify":
                store.set_verified(contact.public)
                show(say(lang, "{name} is verified.", "האימות של {name} הושלם.", name=contact.name))
                return 0
            if command in ("block", "unblock"):
                store.set_blocked(contact.public, command == "block")
                return 0
            if command == "delete":
                count = store.delete_conversation(contact.public)
                show(say(lang, "Deleted {count} messages from this computer. {name} keeps their copy.",
                         "נמחקו {count} הודעות מהמחשב הזה. אצל {name} העותק נשאר.", count=count, name=contact.name))
                return 0
            if command == "send" and len(rest) >= 2:
                words = " ".join(rest[1:])
                store.add_message(contact.public, Message.text(words), outgoing=True, state="queued")
                sent = service.poke(control_path()) is not None
                show(say(lang, "Queued; it goes out when {name} is online.", "בתור; תישלח כשהמחשב של {name} יהיה מחובר.",
                         name=contact.name) if sent else
                     say(lang, "Queued. Turn Diamond Chat on to send it.", "בתור. הפעילו את Diamond Chat כדי לשלוח.",
                         name=contact.name))
                return 0
            if command == "send-picture" and len(rest) == 2:
                if not contact.verified:
                    show(say(lang, "Compare the six symbols with {name} first (dai-chat symbols {name}): pictures "
                             "are only accepted from verified contacts.",
                             "השוו קודם את ששת הסמלים עם {name} (dai-chat symbols {name}): תמונות מתקבלות רק "
                             "מאנשי קשר מאומתים.", name=contact.name))
                    return 2
                try:
                    path = Path(rest[1])
                    if path.stat().st_size > MAX_PICTURE:
                        raise pictures.PictureError("too large")
                    body, mime = pictures.clean(path.read_bytes())
                except (OSError, pictures.PictureError):
                    show(say(lang, "That file is not a PNG, JPEG or WebP picture up to 25 MB.",
                             "הקובץ אינו תמונת PNG, JPEG או WebP של עד 25MB."))
                    return 2
                store.add_message(contact.public, Message.picture(body, mime), outgoing=True, state="queued")
                service.poke(control_path())
                show(say(lang, "Queued, without its location and camera details.",
                         "בתור, בלי המיקום ופרטי המצלמה."))
                return 0
            if command == "read":
                for item in store.conversation(contact.public):
                    who = say(lang, "me", "אני") if item["outgoing"] else contact.name
                    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["time"]))
                    body = item["text"] or say(lang, "[a picture]", "[תמונה]")
                    show(f"{when}  {who}: {body}")
                return 0
        show(__doc__.strip())
        return 2
    except OSError:
        show(say(lang, "Could not reach the keyring or the chat folder.", "אין גישה לצרור המפתחות או לתיקיית הצ'אט."))
        return 1
    finally:
        store.close()
