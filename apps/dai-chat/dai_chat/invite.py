# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The invitation code (docs/SEND.md §0): how a contact finds you on the internet before you have paired.

  dai1-<base32 of: onion service key (32 bytes) | first 10 bytes of the identity key's fingerprint | checksum (2)>

It holds no name and no secret: it is your onion address plus enough of your identity to recognise you in
the handshake. Pairing is only finished when both people compare the six symbols (sas.py).
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from nacl.encoding import RawEncoder
from nacl.hash import blake2b

from .keys import fingerprint

PREFIX = "dai1-"
FPR_SIZE = 10


class InviteError(ValueError):
    """Not a Diamond Chat invitation, or mistyped."""


def onion_address(service_key: bytes) -> str:
    """The v3 .onion address of an Ed25519 onion service key (Tor's rend-spec-v3 §6)."""
    if len(service_key) != 32:
        raise InviteError("an onion service key is 32 bytes")
    version = b"\x03"
    checksum = hashlib.sha3_256(b".onion checksum" + service_key + version).digest()[:2]
    return base64.b32encode(service_key + checksum + version).decode().lower() + ".onion"


@dataclass(frozen=True)
class Invite:
    service_key: bytes
    fingerprint: bytes

    @property
    def onion(self) -> str:
        return onion_address(self.service_key)

    def matches(self, identity_public: bytes) -> bool:
        return fingerprint(identity_public)[:FPR_SIZE] == self.fingerprint


def _checksum(body: bytes) -> bytes:
    return blake2b(body, digest_size=2, person=b"dai-chat-inv", encoder=RawEncoder)


def make(service_key: bytes, identity_public: bytes) -> str:
    body = service_key + fingerprint(identity_public)[:FPR_SIZE]
    text = base64.b32encode(body + _checksum(body)).decode().lower().rstrip("=")
    return PREFIX + "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def parse(code: str) -> Invite:
    cleaned = "".join(code.split()).lower()
    if not cleaned.startswith(PREFIX):
        raise InviteError("not a Diamond Chat invitation")
    letters = cleaned[len(PREFIX):].replace("-", "").upper()
    try:
        raw = base64.b32decode(letters + "=" * (-len(letters) % 8))
    except (ValueError, TypeError) as exc:
        raise InviteError("mistyped") from exc
    if len(raw) != 32 + FPR_SIZE + 2 or _checksum(raw[:-2]) != raw[-2:]:
        raise InviteError("mistyped")
    if base64.b32encode(raw).decode().rstrip("=") != letters:  # the last letter's spare bits must be zero too
        raise InviteError("mistyped")
    return Invite(raw[:32], raw[32:32 + FPR_SIZE])
