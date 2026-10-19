# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What travels inside an encrypted Diamond Chat frame (docs/SEND.md §3).

  kind (1 byte) | header length (4 bytes, big-endian) | header (UTF-8 JSON) | body

  kind 1 text      header {id, time}            body: the text (UTF-8)
  kind 2 picture   header {id, time, mime}      body: the picture (PNG, JPEG or WebP; checked again on arrival)
  kind 3 receipt   header {id, time, state}     body: empty ("delivered", "seen" or "refused")
  kind 4 bye       header {id, time}            body: empty (nothing more to send on this connection)

Everything is checked when it is read, before anything else touches it: sizes, types, the id's shape.
"""
from __future__ import annotations

import json
import re
import struct
import time
import uuid
from dataclasses import dataclass, field

TEXT, PICTURE, RECEIPT, BYE = 1, 2, 3, 4
MAX_HEADER = 4096
MAX_TEXT = 64 * 1024
MAX_PICTURE = 25 * 1024 * 1024
MIMES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff", "image/webp": b"RIFF"}
ID = re.compile(r"^[0-9a-f]{32}$")
STATES = ("delivered", "seen", "refused")


class MessageError(ValueError):
    """Malformed, too large, or not what it says it is."""


@dataclass
class Message:
    kind: int
    body: bytes = b""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    time: float = field(default_factory=time.time)
    mime: str = ""
    state: str = ""

    @classmethod
    def text(cls, words: str) -> "Message":
        return cls(TEXT, words.encode("utf-8"))

    @classmethod
    def picture(cls, data: bytes, mime: str) -> "Message":
        return cls(PICTURE, data, mime=mime)

    @classmethod
    def receipt(cls, message_id: str, state: str) -> "Message":
        return cls(RECEIPT, b"", id=message_id, state=state)

    @classmethod
    def bye(cls) -> "Message":
        return cls(BYE)

    def encode(self) -> bytes:
        header: dict = {"id": self.id, "time": round(self.time, 3)}
        if self.kind == PICTURE:
            header["mime"] = self.mime
        if self.kind == RECEIPT:
            header["state"] = self.state
        raw = json.dumps(header, separators=(",", ":")).encode()
        decoded = decode(bytes([self.kind]) + struct.pack(">I", len(raw)) + raw + self.body)  # the same checks
        return bytes([decoded.kind]) + struct.pack(">I", len(raw)) + raw + self.body


def sniff(data: bytes) -> str | None:
    """The picture's real type, from its first bytes (not from what the sender said)."""
    for mime, magic in MIMES.items():
        if data.startswith(magic) and (mime != "image/webp" or data[8:12] == b"WEBP"):
            return mime
    return None


def decode(frame: bytes) -> Message:
    if len(frame) < 5:
        raise MessageError("too short")
    kind, size = frame[0], struct.unpack(">I", frame[1:5])[0]
    if kind not in (TEXT, PICTURE, RECEIPT, BYE):
        raise MessageError("unknown kind")
    if size > MAX_HEADER or 5 + size > len(frame):
        raise MessageError("bad header")
    try:
        header = json.loads(frame[5:5 + size].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MessageError("bad header") from exc
    body = frame[5 + size:]
    message_id, when = header.get("id"), header.get("time")
    if not isinstance(message_id, str) or not ID.match(message_id):
        raise MessageError("bad id")
    if not isinstance(when, (int, float)) or not 0 < when < 2 ** 33:
        raise MessageError("bad time")
    if kind == TEXT:
        if len(body) > MAX_TEXT:
            raise MessageError("text too long")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MessageError("text is not UTF-8") from exc
        return Message(TEXT, body, message_id, float(when))
    if kind == PICTURE:
        mime = header.get("mime")
        if len(body) > MAX_PICTURE or not body:
            raise MessageError("picture too large or empty")
        if mime not in MIMES or sniff(body) != mime:
            raise MessageError("not a PNG, JPEG or WebP picture")
        return Message(PICTURE, body, message_id, float(when), mime=mime)
    if kind == BYE:
        if body:
            raise MessageError("bad bye")
        return Message(BYE, b"", message_id, float(when))
    state = header.get("state")
    if state not in STATES or body:
        raise MessageError("bad receipt")
    return Message(RECEIPT, b"", message_id, float(when), state=state)
