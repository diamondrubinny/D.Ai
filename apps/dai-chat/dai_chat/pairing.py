# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Becoming contacts (docs/SEND.md §0), as Briar's "add a contact at a distance" does: each person types the
other's invitation code (invite.py), then the two computers swap their full identity keys, and each checks
the key it got against the code it typed.

  I -> R  PAIR = "P" | idI | svcI | sign_I(PROTOCOL "pair-req" | idI | svcI | fprR)
  R -> I  ACK  = idR | svcR | sign_R(PROTOCOL "pair-ack" | idR | svcR | idI)

  id   the Ed25519 identity key;  svc  the onion service key;  fpr  the 10 fingerprint bytes in a code

R answers only someone whose code R typed (the fingerprint of idI and svcI must match a code it is waiting
on); I keeps the answer only if idR and svcR match the code I typed. The new contact is "unverified" until
the two people compare the six symbols (sas.py). Nothing secret travels: the keys are public, and each
signature proves the sender holds its key and binds the answer to this request.
"""
from __future__ import annotations

from . import PROTOCOL
from .invite import FPR_SIZE, Invite
from .keys import Identity, fingerprint, verify

MARK = b"P"
PAIR_SIZE = 1 + 32 + 32 + 64
ACK_SIZE = 32 + 32 + 64


class PairingError(Exception):
    """Not a code we are waiting on, or the keys do not match the code."""


def request(me: Identity, my_service: bytes, theirs: Invite) -> bytes:
    body = me.public + my_service
    return MARK + body + me.sign(PROTOCOL + b"pair-req" + body + theirs.fingerprint)


def answer(me: Identity, my_service: bytes, frame: bytes, waiting) -> tuple[bytes, bytes, bytes]:
    """`waiting(fpr)` gives the Invite we typed for that fingerprint, or None.
    Returns (the ACK frame, their identity key, their service key)."""
    if len(frame) != PAIR_SIZE or frame[:1] != MARK:
        raise PairingError("not a pairing request")
    public, service, signature = frame[1:33], frame[33:65], frame[65:]
    expected = waiting(fingerprint(public)[:FPR_SIZE])
    if expected is None or expected.service_key != service:
        raise PairingError("we are not waiting for this code")
    if not verify(public, PROTOCOL + b"pair-req" + public + service + fingerprint(me.public)[:FPR_SIZE], signature):
        raise PairingError("the request is not signed by its key")
    body = me.public + my_service
    return body + me.sign(PROTOCOL + b"pair-ack" + body + public), public, service


def finish(me: Identity, theirs: Invite, frame: bytes) -> bytes:
    """Checks the ACK against the code we typed; returns their identity key."""
    if len(frame) != ACK_SIZE:
        raise PairingError("not a pairing answer")
    public, service, signature = frame[:32], frame[32:64], frame[64:]
    if not theirs.matches(public) or service != theirs.service_key:
        raise PairingError("the answer does not match the code")
    if not verify(public, PROTOCOL + b"pair-ack" + public + service + me.public, signature):
        raise PairingError("the answer is not signed by its key")
    return public
