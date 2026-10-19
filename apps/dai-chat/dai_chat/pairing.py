# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Becoming contacts (docs/SEND.md §0), as Briar's "add a contact at a distance" does: each person types the
other's invitation code (invite.py), then the two computers swap their full identity keys and the display
names their people chose, and each checks the key it got against the code it typed.

  I -> R  PAIR = "P" | idI | svcI | n | nameI | sign_I(PROTOCOL "pair-req" | idI | svcI | n | nameI | fprR)
  R -> I  ACK  = idR | svcR | n | nameR | sign_R(PROTOCOL "pair-ack" | idR | svcR | n | nameR | idI)

  id   the Ed25519 identity key;  svc  the onion service key;  fpr  the 10 fingerprint bytes in a code
  n    the length of the display name (UTF-8, at most NAME_BYTES); the name is never the computer's user name

R answers only someone whose code R typed (the fingerprint of idI and svcI must match a code it is waiting
on); I keeps the answer only if idR and svcR match the code I typed. The new contact is "unverified" until
the two people compare the six symbols (sas.py). Nothing secret travels: the keys are public, and each
signature proves the sender holds its key and binds the answer to this request.
"""
from __future__ import annotations

import unicodedata

from . import PROTOCOL
from .invite import FPR_SIZE, Invite
from .keys import Identity, fingerprint, verify

MARK = b"P"
NAME_CHARS = 40
NAME_BYTES = 160
PAIR_MAX = 1 + 32 + 32 + 1 + NAME_BYTES + 64
ACK_MAX = 32 + 32 + 1 + NAME_BYTES + 64


class PairingError(Exception):
    """Not a code we are waiting on, or the keys do not match the code."""


def clean_name(text: str) -> str:
    """A display name that cannot hide anything: no control or direction characters, no line breaks, at most
    40 characters. Shown next to the name you gave the contact yourself."""
    kept = "".join(c for c in unicodedata.normalize("NFC", text)
                   if unicodedata.category(c)[0] not in ("C", "Z") or c == " ")
    return " ".join(kept.split())[:NAME_CHARS]


def _name_bytes(name: str) -> bytes:
    data = clean_name(name).encode("utf-8")  # 40 characters are at most 160 bytes (4 each in UTF-8)
    return bytes([len(data)]) + data


def _split(frame: bytes, start: int) -> tuple[bytes, str, bytes]:
    """(the length byte and name as signed, the cleaned name, the signature)."""
    if len(frame) < start + 1 + 64:
        raise PairingError("too short")
    size = frame[start]
    if size > NAME_BYTES or len(frame) != start + 1 + size + 64:
        raise PairingError("bad name")
    raw = frame[start:start + 1 + size]
    try:
        name = clean_name(raw[1:].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PairingError("bad name") from exc
    return raw, name, frame[start + 1 + size:]


def request(me: Identity, my_service: bytes, theirs: Invite, my_name: str = "") -> bytes:
    body = me.public + my_service + _name_bytes(my_name)
    return MARK + body + me.sign(PROTOCOL + b"pair-req" + body + theirs.fingerprint)


def answer(me: Identity, my_service: bytes, frame: bytes, waiting, my_name: str = "") -> tuple[bytes, bytes, bytes, str]:
    """`waiting(fpr)` gives the Invite we typed for that fingerprint, or None.
    Returns (the ACK frame, their identity key, their service key, their display name)."""
    if len(frame) > PAIR_MAX or frame[:1] != MARK:
        raise PairingError("not a pairing request")
    public, service = frame[1:33], frame[33:65]
    raw, name, signature = _split(frame, 65)
    expected = waiting(fingerprint(public)[:FPR_SIZE])
    if expected is None or expected.service_key != service:
        raise PairingError("we are not waiting for this code")
    if not verify(public, PROTOCOL + b"pair-req" + public + service + raw + fingerprint(me.public)[:FPR_SIZE],
                  signature):
        raise PairingError("the request is not signed by its key")
    body = me.public + my_service + _name_bytes(my_name)
    return body + me.sign(PROTOCOL + b"pair-ack" + body + public), public, service, name


def finish(me: Identity, theirs: Invite, frame: bytes) -> tuple[bytes, str]:
    """Checks the ACK against the code we typed; returns (their identity key, their display name)."""
    if len(frame) > ACK_MAX:
        raise PairingError("not a pairing answer")
    public, service = frame[:32], frame[32:64]
    raw, name, signature = _split(frame, 64)
    if not theirs.matches(public) or service != theirs.service_key:
        raise PairingError("the answer does not match the code")
    if not verify(public, PROTOCOL + b"pair-ack" + public + service + raw + me.public, signature):
        raise PairingError("the answer is not signed by its key")
    return public, name
