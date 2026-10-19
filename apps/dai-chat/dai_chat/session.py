# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Diamond Chat session (docs/SEND.md §3): a signed handshake, then authenticated encryption.

Only libsodium primitives (PyNaCl), put together as below. **This construction needs an external security
review before release.**

Handshake, between an initiator I and a responder R who know each other's identity keys (from pairing):

  I -> R  HELLO  = version | eI | idI | sign_I(PROTOCOL "hello" | eI | idR)
  R -> I  REPLY  = eR | sign_R(PROTOCOL "reply" | eR | eI | idI)

  eI, eR   fresh X25519 keys for this session only (forward secrecy: erased when it ends)
  idI, idR Ed25519 identity keys

Each side checks the other's signature with the identity key it already knows, so an impostor on the
network (or a relay) cannot take part. Both signatures cover the other side's identity (and R's covers eI),
so a HELLO cannot be replayed to someone else, nor a REPLY to another HELLO.

Keys: k = BLAKE2b(key = X25519(e, e'), data = transcript, person "dai-chat-keys", 64 bytes)
      k[:32] encrypts I -> R and k[32:] R -> I.

Messages: XChaCha20-Poly1305 (IETF), nonce = 16 zero bytes | counter (8 bytes, big-endian), with the counter
and the direction as associated data. Each side expects exactly the next counter: a repeated, dropped or
reordered message is refused and the session is closed.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from nacl.bindings import (crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt,
                           crypto_scalarmult)
from nacl.encoding import RawEncoder
from nacl.hash import blake2b
from nacl.public import PrivateKey

from . import PROTOCOL
from .keys import Identity, verify

VERSION = 1
HELLO_SIZE = 1 + 32 + 32 + 64
REPLY_SIZE = 32 + 64
MAX_MESSAGE = 32 * 1024 * 1024  # a 25 MB picture and its header, encrypted
ALL_ZERO = bytes(32)


class HandshakeError(Exception):
    """The other side is not who they should be, or spoke another protocol."""


class SessionError(Exception):
    """A message failed its authentication, or came out of order: the session must close."""


def _shared(private: bytes, public: bytes) -> bytes:
    """X25519; libsodium refuses low-order points, and so do we (as a handshake failure, not a crash)."""
    try:
        return crypto_scalarmult(private, public)
    except Exception as exc:  # nacl.exceptions.RuntimeError
        raise HandshakeError("bad ephemeral key") from exc


def _keys(shared: bytes, transcript: bytes) -> tuple[bytes, bytes]:
    if shared == ALL_ZERO:  # a low-order point: refuse instead of encrypting with a known key
        raise HandshakeError("bad ephemeral key")
    material = blake2b(transcript, key=shared, digest_size=64, person=b"dai-chat-keys", encoder=RawEncoder)
    return material[:32], material[32:]


@dataclass
class Session:
    send_key: bytes
    receive_key: bytes
    peer: bytes  # the other side's identity key
    sent: int = 0
    received: int = 0
    _label_out: bytes = field(default=b"", repr=False)
    _label_in: bytes = field(default=b"", repr=False)

    def seal(self, plaintext: bytes) -> bytes:
        if len(plaintext) > MAX_MESSAGE - 16:
            raise SessionError("message too large")
        counter = struct.pack(">Q", self.sent)
        frame = crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, self._label_out + counter,
                                                           bytes(16) + counter, self.send_key)
        self.sent += 1
        return frame

    def open(self, frame: bytes) -> bytes:
        if len(frame) > MAX_MESSAGE:
            raise SessionError("message too large")
        counter = struct.pack(">Q", self.received)
        try:
            plaintext = crypto_aead_xchacha20poly1305_ietf_decrypt(frame, self._label_in + counter,
                                                                  bytes(16) + counter, self.receive_key)
        except Exception as exc:  # nacl.exceptions.CryptoError: forged, altered, replayed or out of order
            raise SessionError("a message failed its check") from exc
        self.received += 1
        return plaintext

    def close(self) -> None:
        """Forget the keys (as far as Python allows): the session cannot be decrypted later from this object."""
        self.send_key = self.receive_key = b""


class Initiator:
    def __init__(self, me: Identity, peer: bytes) -> None:
        self.me, self.peer = me, peer
        self._ephemeral = PrivateKey.generate()

    def hello(self) -> bytes:
        e = bytes(self._ephemeral.public_key)
        return bytes([VERSION]) + e + self.me.public + self.me.sign(PROTOCOL + b"hello" + e + self.peer)

    def finish(self, reply: bytes) -> Session:
        if len(reply) != REPLY_SIZE:
            raise HandshakeError("not a Diamond Chat reply")
        e_peer, signature = reply[:32], reply[32:]
        e_mine = bytes(self._ephemeral.public_key)
        if not verify(self.peer, PROTOCOL + b"reply" + e_peer + e_mine + self.me.public, signature):
            raise HandshakeError("the other computer is not the contact it claims to be")
        shared = _shared(bytes(self._ephemeral), e_peer)
        self._ephemeral = None  # forward secrecy: the private half is gone after this point
        send, receive = _keys(shared, e_mine + e_peer + self.me.public + self.peer)
        return Session(send, receive, self.peer, _label_out=b"I>R", _label_in=b"R>I")


class Responder:
    """Answers a HELLO from a known contact; `known` decides who may talk to us."""

    def __init__(self, me: Identity, known) -> None:
        self.me, self.known = me, known

    def answer(self, hello: bytes) -> tuple[bytes, Session]:
        if len(hello) != HELLO_SIZE or hello[0] != VERSION:
            raise HandshakeError("not a Diamond Chat hello, or another version")
        e_peer, peer, signature = hello[1:33], hello[33:65], hello[65:]
        if not self.known(peer):
            raise HandshakeError("not a contact")
        if not verify(peer, PROTOCOL + b"hello" + e_peer + self.me.public, signature):
            raise HandshakeError("the signature does not match the contact")
        ephemeral = PrivateKey.generate()
        e_mine = bytes(ephemeral.public_key)
        reply = e_mine + self.me.sign(PROTOCOL + b"reply" + e_mine + e_peer + peer)
        shared = _shared(bytes(ephemeral), e_peer)
        del ephemeral
        receive, send = _keys(shared, e_peer + e_mine + peer + self.me.public)
        return reply, Session(send, receive, peer, _label_out=b"R>I", _label_in=b"I>R")
