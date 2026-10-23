# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-chat: Diamond Chat from the command line (docs/SEND.md).

  dai-chat window               the Diamond Chat window
  dai-chat name [NAME]          the display name your contacts see (you choose it; never your user name)
  dai-chat receive on|off       let contacts send you messages (off until you turn it on)
  dai-chat requests             messages waiting for your decision: from someone new, or held as suspicious
  dai-chat accept NAME | decline NAME   see NAME's messages, or delete them and block NAME
  dai-chat show NAME ID | discard NAME ID   one held message: show it anyway, or delete it
  dai-chat code                 your invitation code, to give someone by phone or in person
  dai-chat add NAME CODE        the code someone gave you (they add yours too)
  dai-chat contacts             your contacts, and the codes still waiting
  dai-chat symbols NAME         the six symbols to compare with NAME, by phone or face to face
  dai-chat verify NAME          after the symbols matched: NAME may now send you pictures
  dai-chat send NAME [TEXT...]  a message, from stdin without TEXT (it waits here until NAME is online)
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

from . import invite, keys, pictures, sas, scan
from .pairing import clean_name
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


def restart() -> None:
    """A running service reads the settings again (nothing happens when Chat is off)."""
    try:
        subprocess.run(["systemctl", "--user", "try-restart", "dai-chat.service"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass


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
    if command == "window":
        from .gui import main as window

        return window(["dai-chat"])
    store = Store(folder)
    try:
        identity_stores, onion_stores = stores(folder)
        me, _ = keys.load_or_create(identity_stores)
        onion_identity, _ = keys.load_or_create(onion_stores)
        onion_seed = onion_identity.seed()

        path = service.settings_path()
        settings = service.Settings.load(path)
        if command == "name":
            if rest:
                chosen = clean_name(" ".join(rest))
                if not chosen:
                    show(say(lang, "Write a name with letters in it.", "כתבו שם שיש בו אותיות."))
                    return 2
                settings.name = chosen
                settings.save(path)
                restart()
            show(say(lang, "Your contacts see you as: {name}", "אנשי הקשר רואים אתכם בשם: {name}",
                     name=settings.name) if settings.name else
                 say(lang, "No display name yet. Choose one: dai-chat name NAME",
                     "עדיין אין שם תצוגה. בחרו שם: dai-chat name NAME"))
            return 0
        if command in ("code", "add", "on", "receive") and not settings.name:
            show(say(lang, "First choose the name your contacts will see (not your user name): dai-chat name NAME",
                     "קודם בחרו את השם שאנשי הקשר יראו (לא שם המשתמש שלכם): dai-chat name NAME"))
            return 2
        if command == "receive" and rest and rest[0] in ("on", "off"):
            settings.receive = rest[0] == "on"
            settings.save(path)
            restart()
            show(say(lang, "Receiving is on. New contacts' messages wait for your OK, and every message is checked "
                     "first.", "קבלת הודעות פועלת. הודעות מאנשי קשר חדשים ממתינות לאישורכם, וכל הודעה נבדקת "
                     "קודם.") if settings.receive else
                 say(lang, "Receiving is off: messages to you wait on your contacts' computers.",
                     "קבלת הודעות כבויה: הודעות אליכם ממתינות במחשבים של אנשי הקשר."))
            return 0
        if command == "requests":
            found = False
            for contact in store.contacts():
                for item in store.conversation(contact.public, waiting=True):
                    found = True
                    body = item["text"] or say(lang, "[a picture]", "[תמונה]")
                    if item["state"] == "request":
                        head = say(lang, "{name}, new: dai-chat accept {name} or decline {name}",
                                   "{name}, חדש: dai-chat accept {name} או decline {name}", name=contact.name)
                    else:
                        head = say(lang, "{name}, held ({why}): dai-chat show {name} {id} or discard {name} {id}",
                                   "{name}, עוכבה ({why}): dai-chat show {name} {id} או discard {name} {id}",
                                   name=contact.name, id=item["id"][:8],
                                   why=scan.describe(item["warning"].split(","), lang))
                    show(head)
                    if item["state"] == "request" and not item["warning"]:
                        show(f"    {body[:200]}")
            if not found:
                show(say(lang, "Nothing is waiting for you.", "שום דבר לא ממתין לכם."))
            return 0
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
                shown = f"{contact.name} ({contact.display})" if contact.display and contact.display != contact.name \
                    else contact.name
                show(f"{shown}  ({state})")
            for _theirs, name in store.waiting():
                show(say(lang, "{name}  (waiting for them to add your code)", "{name}  (ממתינים שיוסיפו את הקוד שלכם)",
                         name=name))
            return 0
        if command == "lan" and rest and rest[0] in ("on", "off"):
            # The firewall goes through D.Ai Tune: a plan, a confirmation (it opens the computer to the local
            # network), and undo. Chat's port, and mDNS so contacts can find each other; local network only.
            port = service.transport.PORT
            wanted = (f"open port {port} and open udp port 5353" if rest[0] == "on" else
                      f"close port {port} and close udp port 5353")
            try:
                tuned = subprocess.run(["dai-tune", wanted], timeout=600).returncode
            except (OSError, subprocess.TimeoutExpired):
                tuned = 1
            if tuned != 0 and rest[0] == "on":
                show(say(lang, "The firewall was not changed, so Chat stays on Tor only.",
                         "חומת האש לא שונתה, ולכן Chat נשאר ב־Tor בלבד."))
                return 1
            settings.lan = rest[0] == "on"
            settings.save(path)
            restart()
            show(say(lang, "Saved. Contacts on this network can now reach you directly.",
                     "נשמר. אנשי קשר ברשת הזו יכולים עכשיו להגיע אליכם ישירות.") if settings.lan else
                 say(lang, "Saved. Chat uses Tor only.", "נשמר. Chat משתמש ב־Tor בלבד."))
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
        if command in ("symbols", "verify", "send", "send-picture", "read", "delete", "block", "unblock", "accept",
                       "decline", "show", "discard") and rest:
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
            if command == "send" and len(rest) >= 1:
                # From stdin when it is not on the command line: argv is visible to every user in `ps`.
                words = " ".join(rest[1:]) if len(rest) >= 2 else sys.stdin.read().strip()
                if not words:
                    show(say(lang, "Nothing to send: write the text on stdin (echo hello | dai-chat send {name}).",
                             "אין מה לשלוח: כתבו את הטקסט ב־stdin ‏(echo שלום | dai-chat send {name}).", name=contact.name))
                    return 2
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
            if command == "accept":
                store.accept(contact.public)
                show(say(lang, "{name}'s messages are shown from now on (suspicious ones still wait for you).",
                         "ההודעות של {name} מוצגות מעכשיו (הודעות חשודות עדיין ימתינו לכם).", name=contact.name))
                return 0
            if command == "decline":
                count = store.decline(contact.public)
                show(say(lang, "Deleted {count} waiting messages and blocked {name}.",
                         "נמחקו {count} הודעות ממתינות ו־{name} נחסמו.", count=count, name=contact.name))
                return 0
            if command in ("show", "discard") and len(rest) == 2:
                held = [m for m in store.conversation(contact.public, waiting=True)
                        if m["state"] == "held" and m["id"].startswith(rest[1].lower())]
                if len(held) != 1:
                    show(say(lang, "No held message with that number.", "אין הודעה מעוכבת עם המספר הזה."))
                    return 2
                if command == "show":
                    store.show(contact.public, held[0]["id"])
                else:
                    store.delete_waiting(contact.public, held[0]["id"])
                return 0
            if command == "read":
                for item in store.conversation(contact.public):
                    who = say(lang, "me", "אני") if item["outgoing"] else contact.name
                    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["time"]))
                    body = item["text"] or say(lang, "[a picture]", "[תמונה]")
                    show(f"{when}  {who}: {body}")
                waiting = len(store.conversation(contact.public, waiting=True))
                if waiting:
                    show(say(lang, "{count} more wait for your decision: dai-chat requests",
                             "עוד {count} ממתינות להחלטה שלכם: dai-chat requests", count=waiting))
                return 0
        show(__doc__.strip())
        return 2
    except OSError:
        show(say(lang, "Could not reach the keyring or the chat folder.", "אין גישה לצרור המפתחות או לתיקיית הצ'אט."))
        return 1
    finally:
        store.close()
