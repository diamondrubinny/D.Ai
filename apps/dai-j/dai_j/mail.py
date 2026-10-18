# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Talking to the mail server: IMAP to read, SMTP to send (docs/MAIL.md stage 1).

Encrypted only, with the system's certificate checks: TLS from the start or
STARTTLS, never plain text. One short connection per task, so a stuck
server never freezes the window. Folder names travel in IMAP's modified
UTF-7, so Hebrew folder names work both ways.
"""

from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from .accounts import Account
from .discover import Server

TIMEOUT = 30
HEADER_FIELDS = "FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES"
ROLES = {"\\Sent": "sent", "\\Trash": "trash", "\\Drafts": "drafts", "\\Archive": "archive", "\\Junk": "junk",
         "\\All": "all"}
# Servers without SPECIAL-USE: the usual names (also Hebrew ones).
ROLE_NAMES = {
    "sent": ("sent", "sent items", "sent mail", "[gmail]/sent mail", "inbox.sent", "נשלח", "דואר יוצא"),
    "trash": ("trash", "deleted items", "deleted messages", "[gmail]/trash", "inbox.trash", "אשפה", "פריטים שנמחקו"),
    "drafts": ("drafts", "[gmail]/drafts", "inbox.drafts", "טיוטות"),
    "junk": ("junk", "spam", "junk e-mail", "[gmail]/spam", "inbox.junk", "דואר זבל"),
    "archive": ("archive", "archives", "ארכיון"),
}
LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\) (?P<sep>"[^"]*"|NIL) (?P<name>.+)$')
FETCH_UID = re.compile(rb"UID (\d+)")
FETCH_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")


class MailError(Exception):
    """Something the user can act on; the message is a key for the interface text."""


# Modified UTF-7 (RFC 3501 §5.1.3)

def decode_folder(name: str) -> str:
    def repl(match: re.Match) -> str:
        chunk = match.group(1)
        if not chunk:
            return "&"
        data = chunk.replace(",", "/")
        data += "=" * (-len(data) % 4)
        return base64.b64decode(data).decode("utf-16-be", errors="replace")

    return re.sub(r"&([A-Za-z0-9+,]*)-", repl, name)


def encode_folder(name: str) -> str:
    out, buffer = [], []

    def flush() -> None:
        if buffer:
            raw = "".join(buffer).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode().rstrip("=").replace("/", ",") + "-")
            buffer.clear()

    for char in name:
        if 0x20 <= ord(char) <= 0x7E:
            flush()
            out.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush()
    return "".join(out)


def quote(name: str) -> str:
    return '"' + encode_folder(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Folder:
    name: str             # as the server knows it, decoded
    role: str = ""        # inbox, sent, trash, drafts, junk, archive, all
    selectable: bool = True


@dataclass
class Header:
    uid: int
    sender: str
    sender_address: str
    to: str
    subject: str
    date: float
    seen: bool
    flagged: bool
    message_id: str = ""
    references: str = ""


@dataclass
class Body:
    text: str = ""
    html: str = ""
    attachments: list[tuple[str, int]] = field(default_factory=list)   # (file name, bytes)


# Parsing

def _decoded(message, name: str) -> str:
    value = message.get(name, "")
    return re.sub(r"\s+", " ", str(value)).strip()


def _date(message) -> float:
    try:
        return parsedate_to_datetime(message.get("Date", "")).timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


def parse_header(uid: int, flags: str, raw: bytes) -> Header:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    pairs = getaddresses([str(message.get("From", ""))])
    name, address = pairs[0] if pairs else ("", "")
    return Header(uid=uid, sender=name or address, sender_address=address, to=_decoded(message, "To"),
                  subject=_decoded(message, "Subject"), date=_date(message), seen="\\Seen" in flags,
                  flagged="\\Flagged" in flags, message_id=_decoded(message, "Message-ID"),
                  references=(_decoded(message, "References") + " " + _decoded(message, "In-Reply-To")).strip())


def parse_body(raw: bytes) -> Body:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    body = Body()
    text_part = message.get_body(preferencelist=("plain",))
    html_part = message.get_body(preferencelist=("html",))
    for part, attr in ((text_part, "text"), (html_part, "html")):
        if part is not None:
            try:
                setattr(body, attr, part.get_content())
            except (LookupError, ValueError):  # an unknown charset
                payload = part.get_payload(decode=True) or b""
                setattr(body, attr, payload.decode("utf-8", errors="replace"))
    for part in message.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        body.attachments.append((part.get_filename() or "attachment", len(payload)))
    return body


def parse_list(lines: list) -> list[Folder]:
    folders = []
    for line in lines:
        if not isinstance(line, bytes):
            continue
        match = LIST_LINE.match(line)
        if not match:
            continue
        flags = match.group("flags").decode(errors="replace")
        raw = match.group("name").decode(errors="replace").strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        name = decode_folder(raw)
        role = "inbox" if name.upper() == "INBOX" else next((r for f, r in ROLES.items() if f in flags), "")
        folders.append(Folder(name, role, "\\Noselect" not in flags and "\\NonExistent" not in flags))
    taken = {f.role for f in folders if f.role}
    for folder in folders:  # no SPECIAL-USE: guess from the usual names
        if not folder.role:
            for role, names in ROLE_NAMES.items():
                if role not in taken and folder.name.casefold() in names:
                    folder.role = role
                    taken.add(role)
    return folders


def parse_fetch(data: list) -> list[tuple[int, str, bytes]]:
    """imaplib's FETCH answer as (uid, flags, literal)."""
    result = []
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            meta, literal = item[0], item[1]
            uid, flags = FETCH_UID.search(meta), FETCH_FLAGS.search(meta)
            if uid:
                result.append((int(uid.group(1)), flags.group(1).decode(errors="replace") if flags else "", literal))
    return result


# Connections

def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class Imap:
    """One IMAP session; use as a context manager."""

    def __init__(self, server: Server, password: str, factory=None) -> None:
        self.server = server
        self.password = password
        self.factory = factory
        self.conn = None

    def __enter__(self) -> "Imap":
        try:
            if self.factory is not None:
                self.conn = self.factory(self.server)
            elif self.server.security == "ssl":
                self.conn = imaplib.IMAP4_SSL(self.server.host, self.server.port, ssl_context=_context(),
                                              timeout=TIMEOUT)
            elif self.server.security == "starttls":
                self.conn = imaplib.IMAP4(self.server.host, self.server.port, timeout=TIMEOUT)
                self.conn.starttls(ssl_context=_context())
            else:
                raise MailError("insecure")
        except ssl.SSLCertVerificationError:
            raise MailError("certificate") from None
        except (OSError, imaplib.IMAP4.error):
            raise MailError("unreachable") from None
        try:
            self.conn.login(self.server.username, self.password)
        except imaplib.IMAP4.error:
            self._close()
            raise MailError("login") from None
        return self

    def __exit__(self, *exc) -> None:
        self._close()

    def _close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
            self.conn = None

    def _ok(self, result: tuple) -> list:
        status, data = result
        if status != "OK":
            raise MailError("server")
        return data

    def folders(self) -> list[Folder]:
        return parse_list(self._ok(self.conn.list()))

    def select(self, folder: str, readonly: bool = True) -> int:
        """Selects the folder; returns its UIDVALIDITY (a change means the cached UIDs are void)."""
        self._ok(self.conn.select(quote(folder), readonly=readonly))
        _, values = self.conn.response("UIDVALIDITY")
        try:
            return int(values[0]) if values and values[0] else 0
        except (TypeError, ValueError):
            return 0

    def headers(self, after_uid: int = 0, limit: int = 300) -> list[Header]:
        """The newest messages (up to `limit`) after a UID."""
        data = self._ok(self.conn.uid("SEARCH", None, f"UID {after_uid + 1}:*" if after_uid else "ALL"))
        uids = sorted({int(u) for u in (data[0] or b"").split() if u.isdigit() and int(u) > after_uid})[-limit:]
        result = []
        for start in range(0, len(uids), 100):
            chunk = ",".join(str(u) for u in uids[start:start + 100])
            fetched = self._ok(self.conn.uid("FETCH", chunk, f"(UID FLAGS BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])"))
            result += [parse_header(uid, flags, raw) for uid, flags, raw in parse_fetch(fetched)]
        return result

    def flags(self, uids: list[int]) -> dict[int, str]:
        if not uids:
            return {}
        fetched = self._ok(self.conn.uid("FETCH", ",".join(map(str, uids)), "(UID FLAGS)"))
        result = {}
        for item in fetched:
            meta = item[0] if isinstance(item, tuple) else item
            if isinstance(meta, bytes):
                uid, flags = FETCH_UID.search(meta), FETCH_FLAGS.search(meta)
                if uid:
                    result[int(uid.group(1))] = flags.group(1).decode(errors="replace") if flags else ""
        return result

    def body(self, uid: int) -> bytes:
        fetched = parse_fetch(self._ok(self.conn.uid("FETCH", str(uid), "(UID BODY.PEEK[])")))
        if not fetched:
            raise MailError("gone")
        return fetched[0][2]

    def set_flag(self, uid: int, flag: str, on: bool = True) -> None:
        self._ok(self.conn.uid("STORE", str(uid), "+FLAGS" if on else "-FLAGS", f"({flag})"))

    def move(self, uid: int, target: str) -> None:
        capabilities = getattr(self.conn, "capabilities", ())
        if "MOVE" in capabilities:
            self._ok(self.conn.uid("MOVE", str(uid), quote(target)))
            return
        self._ok(self.conn.uid("COPY", str(uid), quote(target)))
        self.set_flag(uid, "\\Deleted")
        if "UIDPLUS" in capabilities:
            self._ok(self.conn.uid("EXPUNGE", str(uid)))
        else:
            self._ok(self.conn.expunge())

    def append(self, folder: str, raw: bytes, seen: bool = True) -> None:
        self._ok(self.conn.append(quote(folder), "(\\Seen)" if seen else None,
                                  imaplib.Time2Internaldate(time.time()), raw))


def send(server: Server, password: str, message: EmailMessage | bytes, factory=None,
         envelope: tuple[str, list[str]] | None = None) -> None:
    """Sends over SMTP with TLS. A message already made into bytes (signed or encrypted) goes exactly as it is,
    with the envelope given; otherwise the server sees the envelope from the message headers."""
    try:
        if factory is not None:
            smtp = factory(server)
        elif server.security == "ssl":
            smtp = smtplib.SMTP_SSL(server.host, server.port, context=_context(), timeout=TIMEOUT)
        elif server.security == "starttls":
            smtp = smtplib.SMTP(server.host, server.port, timeout=TIMEOUT)
            smtp.starttls(context=_context())
        else:
            raise MailError("insecure")
    except ssl.SSLCertVerificationError:
        raise MailError("certificate") from None
    except (OSError, smtplib.SMTPException):
        raise MailError("unreachable") from None
    try:
        smtp.login(server.username, password)
        if isinstance(message, bytes):
            if envelope is None or not envelope[1]:
                raise MailError("recipients")
            smtp.sendmail(envelope[0], envelope[1], message)
        else:
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise MailError("login") from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError("recipients") from None
    except (OSError, smtplib.SMTPException):
        raise MailError("send") from None
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass


def check(account: Account, password: str, imap_factory=None) -> list[Folder]:
    """Signs in once and returns the folders: the test when an account is added."""
    with Imap(account.incoming, password, imap_factory) as imap:
        return imap.folders()
