# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""A small IMAP4rev1 server on localhost, so J's code talks to a real imaplib connection in tests.

It speaks just enough: CAPABILITY, LOGIN, LIST, SELECT/EXAMINE, UID SEARCH/FETCH/STORE/MOVE/COPY/EXPUNGE,
EXPUNGE, APPEND (with a literal), NOOP and LOGOUT.
"""

from __future__ import annotations

import re
import socketserver
import threading
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone


def message(uid: int, sender: str, subject: str, body: str, html: str = "", day: int = 1) -> bytes:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "dana@example.com"
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime(2026, 10, day, 9, 30, tzinfo=timezone.utc))
    m["Message-ID"] = f"<m{uid}@example.com>"
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


class Mailbox:
    def __init__(self) -> None:
        self.user, self.password = "dana@example.com", "correct horse"
        self.validity = {"INBOX": 7, "Sent": 3, "Trash": 4, "&BdAF6AXbBdkF1QXf-": 5}   # the last is "ארכיון"
        self.flags = {"INBOX": "", "Sent": "\\Sent", "Trash": "\\Trash", "&BdAF6AXbBdkF1QXf-": "\\Archive"}
        self.messages: dict[str, dict[int, list]] = {name: {} for name in self.validity}   # uid -> [flags, raw]
        self.next_uid = {name: 1 for name in self.validity}
        self.lock = threading.Lock()

    def add(self, folder: str, raw: bytes, flags: str = "") -> int:
        with self.lock:
            uid = self.next_uid[folder]
            self.next_uid[folder] += 1
            self.messages[folder][uid] = [set(flags.split()), raw]
            return uid


class Handler(socketserver.StreamRequestHandler):
    def send(self, line: str | bytes) -> None:
        self.wfile.write((line if isinstance(line, bytes) else line.encode()) + b"\r\n")

    def handle(self) -> None:
        box: Mailbox = self.server.mailbox
        selected = None
        self.send("* OK [CAPABILITY IMAP4rev1 MOVE UIDPLUS SPECIAL-USE] fake ready")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            try:
                line = raw.decode().rstrip("\r\n")
            except UnicodeDecodeError:
                return  # not IMAP (a TLS hello in the "never falls back" test)
            literal = re.search(r"\{(\d+)\}$", line)
            data = b""
            if literal:
                self.send("+ go on")
                data = self.rfile.read(int(literal.group(1)))
                self.rfile.readline()
            tag, _, rest = line.partition(" ")
            command, _, args = rest.partition(" ")
            command = command.upper()
            if command == "CAPABILITY":
                self.send("* CAPABILITY IMAP4rev1 MOVE UIDPLUS SPECIAL-USE")
            elif command == "LOGIN":
                user, password = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', args)[0:2]
                user, password = user[0] or user[1], password[0] or password[1]
                if (user, password.replace('\\"', '"')) != (box.user, box.password):
                    self.send(f"{tag} NO [AUTHENTICATIONFAILED] wrong")
                    continue
            elif command == "LIST":
                for name, flag in box.flags.items():
                    self.send(f'* LIST (\\HasNoChildren{" " + flag if flag else ""}) "/" "{name}"')
            elif command in ("SELECT", "EXAMINE"):
                name = args.strip().strip('"')
                if name not in box.messages:
                    self.send(f"{tag} NO no such folder")
                    continue
                selected = name
                self.send(f"* {len(box.messages[name])} EXISTS")
                self.send(f"* OK [UIDVALIDITY {box.validity[name]}] ok")
            elif command == "UID":
                sub, _, params = args.partition(" ")
                self.uid(tag, sub.upper(), params, box, selected)
                continue
            elif command == "EXPUNGE":
                with box.lock:
                    for uid in [u for u, (f, _) in box.messages[selected].items() if "\\Deleted" in f]:
                        del box.messages[selected][uid]
            elif command == "APPEND":
                name = args.split(" ", 1)[0].strip('"')
                box.add(name, data, "\\Seen")
            elif command == "LOGOUT":
                self.send("* BYE")
                self.send(f"{tag} OK bye")
                return
            self.send(f"{tag} OK done")

    def uid(self, tag: str, sub: str, params: str, box: Mailbox, folder: str | None) -> None:
        messages = box.messages[folder]
        if sub == "SEARCH":
            spec = params.replace("CHARSET", "").split()
            uids = sorted(messages)
            if spec and spec[0] == "UID":
                low = int(spec[1].split(":")[0])
                uids = [u for u in uids if u >= low] or uids[-1:]   # "n:*" always includes the last one
            self.send("* SEARCH " + " ".join(map(str, uids)))
        elif sub == "FETCH":
            wanted, items = params.split(" ", 1)
            for uid in self._uids(wanted, messages):
                flags, raw = messages[uid]
                flag_text = " ".join(sorted(flags))
                if "BODY.PEEK[]" in items:
                    self.send(f"* {uid} FETCH (UID {uid} BODY[] {{{len(raw)}}}".encode())
                    self.wfile.write(raw)
                    self.send(")")
                elif "HEADER.FIELDS" in items:
                    header = raw.split(b"\n\n", 1)[0].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + b"\r\n\r\n"
                    self.send(f"* {uid} FETCH (UID {uid} FLAGS ({flag_text}) BODY[HEADER.FIELDS (FROM)] "
                              f"{{{len(header)}}}".encode())
                    self.wfile.write(header)
                    self.send(")")
                else:
                    self.send(f"* {uid} FETCH (UID {uid} FLAGS ({flag_text}))")
        elif sub == "STORE":
            wanted, mode, value = params.split(" ", 2)
            names = set(value.strip("()").split())
            for uid in self._uids(wanted, messages):
                if mode.startswith("+"):
                    messages[uid][0] |= names
                else:
                    messages[uid][0] -= names
        elif sub in ("MOVE", "COPY"):
            wanted, target = params.split(" ", 1)
            target = target.strip('"')
            for uid in self._uids(wanted, messages):
                box.add(target, messages[uid][1], " ".join(messages[uid][0]))
                if sub == "MOVE":
                    del messages[uid]
        elif sub == "EXPUNGE":
            for uid in self._uids(params, messages):
                if "\\Deleted" in messages[uid][0]:
                    del messages[uid]
        self.send(f"{tag} OK done")

    @staticmethod
    def _uids(spec: str, messages: dict) -> list[int]:
        result = []
        for part in spec.split(","):
            if ":" in part:
                low, high = part.split(":")
                top = max(messages) if messages else 0
                result += [u for u in messages if int(low) <= u <= (top if high == "*" else int(high))]
            elif part.isdigit() and int(part) in messages:
                result.append(int(part))
        return sorted(set(result))


class FakeImapServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.mailbox = Mailbox()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
