# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Who you are in Diamond Chat (docs/SEND.md §3): one Ed25519 identity key per person.

The private key's 32-byte seed lives in the desktop keyring (gnome-keyring, through `secret-tool`), as J's
passwords do. Only when there is no keyring at all (a session without one), it is kept in a file readable
by you alone (0600) on the encrypted disk, and `where` says so.
"""
from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nacl.hash import blake2b
from nacl.encoding import RawEncoder
from nacl.signing import SigningKey, VerifyKey

ATTRIBUTES = ["application", "dai-chat", "kind", "identity"]


def fingerprint(public: bytes, size: int = 32) -> bytes:
    """A hash of a public identity key; its first 10 bytes go in invitation codes."""
    return blake2b(public, digest_size=size, person=b"dai-chat-fpr", encoder=RawEncoder)


@dataclass
class Identity:
    signing: SigningKey

    @classmethod
    def generate(cls) -> "Identity":
        return cls(SigningKey.generate())

    @property
    def public(self) -> bytes:
        return bytes(self.signing.verify_key)

    def sign(self, message: bytes) -> bytes:
        return self.signing.sign(message).signature

    def seed(self) -> bytes:
        return bytes(self.signing)


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    try:
        VerifyKey(public).verify(message, signature)
        return True
    except Exception:  # nacl.exceptions.BadSignatureError, or a malformed key
        return False


class FileStore:
    """The fallback: a 0600 file in a 0700 folder."""

    where = "file"

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> bytes | None:
        try:
            data = base64.b64decode(self.path.read_text(encoding="ascii").strip(), validate=True)
        except (OSError, ValueError):
            return None
        return data if len(data) == 32 else None

    def save(self, seed: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(base64.b64encode(seed).decode() + "\n")


class KeyringStore:
    """gnome-keyring through secret-tool; the seed crosses only stdin/stdout, never a command line."""

    where = "keyring"

    def __init__(self, run: Callable = subprocess.run, kind: str = "identity") -> None:
        """`kind` is "identity", or "onion" for the key of the Tor onion service (tor.py)."""
        self.run, self.kind = run, kind
        self.attributes = ATTRIBUTES[:3] + [kind]

    def available(self) -> bool:
        try:
            result = self.run(["secret-tool", "search", *self.attributes], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode in (0, 1)  # 1: nothing stored yet, but the keyring answered

    def load(self) -> bytes | None:
        try:
            result = self.run(["secret-tool", "lookup", *self.attributes], capture_output=True, text=True, timeout=10)
            data = base64.b64decode((result.stdout or "").strip(), validate=True) if result.returncode == 0 else b""
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
        return data if len(data) == 32 else None

    def save(self, seed: bytes) -> None:
        result = self.run(["secret-tool", "store", f"--label=Diamond Chat {self.kind}", *self.attributes],
                          input=base64.b64encode(seed).decode(), capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise OSError("the keyring refused to store the key")


def load_or_create(stores: list) -> tuple[Identity, str]:
    """The identity from the first store that has one; otherwise a new one, saved in the first store that works."""
    for store in stores:
        seed = store.load()
        if seed:
            return Identity(SigningKey(seed)), store.where
    identity = Identity.generate()
    for store in stores:
        try:
            store.save(identity.seed())
            return identity, store.where
        except OSError:
            continue
    raise OSError("there is nowhere to keep the identity key")
