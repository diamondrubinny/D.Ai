# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Signed and encrypted mail (docs/MAIL.md §14): OpenPGP (RFC 3156) and S/MIME signatures, OpenPGP decryption.

Everything goes through the system's own GnuPG (gpg, gpgsm) with fixed
arguments and no shell; J holds no keys and no cryptography of its own. The
person's keys stay in their GnuPG home, and passphrases are asked by
gpg-agent's own window, never by J. A decrypted message is shown and never
saved: J's store keeps only what arrived.
"""

from __future__ import annotations

import email
import email.policy
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TIMEOUT = 20
DECRYPT_TIMEOUT = 180       # gpg-agent may be waiting for the passphrase
MAX_INPUT = 32 * 2**20


@dataclass
class Signature:
    state: str              # good | bad | unknown_key | error
    who: str = ""           # the signer as their key names them
    fingerprint: str = ""
    trusted: bool = False   # the person (or their web of trust) marked the key as theirs
    kind: str = "openpgp"   # openpgp | smime


def _clean(text: str) -> str:
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))
    return text.strip()[:200]


def kind(raw: bytes) -> str:
    """"signed" (OpenPGP), "smime_signed", "encrypted" (OpenPGP), "inline_signed", "inline_encrypted" or ""."""
    message = email.message_from_bytes(raw[:MAX_INPUT], policy=email.policy.compat32)
    ctype = message.get_content_type()
    protocol = (message.get_param("protocol") or "").lower()
    if ctype == "multipart/signed" and protocol == "application/pgp-signature":
        return "signed"
    if ctype == "multipart/signed" and protocol in ("application/pkcs7-signature", "application/x-pkcs7-signature"):
        return "smime_signed"
    if ctype == "multipart/encrypted" and protocol == "application/pgp-encrypted":
        return "encrypted"
    head = raw[:MAX_INPUT]
    if b"-----BEGIN PGP SIGNED MESSAGE-----" in head:
        return "inline_signed"
    if b"-----BEGIN PGP MESSAGE-----" in head:
        return "inline_encrypted"
    return ""


def _signed_parts(raw: bytes) -> tuple[bytes, bytes] | None:
    """(the signed part exactly as sent, in CRLF form; the detached signature), or None (RFC 3156 §5, RFC 8551)."""
    message = email.message_from_bytes(raw, policy=email.policy.compat32)
    boundary = message.get_boundary()
    if not boundary:
        return None
    marker = b"--" + boundary.encode("ascii", "replace")
    # Find the body: after the headers, the part between the first two boundary lines, byte for byte.
    head_end = re.search(rb"\r?\n\r?\n", raw)
    body = raw[head_end.end():] if head_end else b""
    pieces = re.split(rb"(?:^|\r?\n)" + re.escape(marker) + rb"(?:--)?[ \t]*(?=\r?\n|$)", body)
    if len(pieces) < 3:
        return None
    signed = re.sub(rb"^\r?\n", b"", pieces[1], count=1)
    signed = re.sub(rb"\r?\n", b"\r\n", signed)  # signatures are over the canonical CRLF form
    parts = message.get_payload()
    if not isinstance(parts, list) or len(parts) < 2:
        return None
    signature = parts[1].get_payload(decode=True) or b""
    return signed, signature


def _status(output: str, smime: bool) -> Signature:
    sig = Signature("error", kind="smime" if smime else "openpgp")
    for line in output.splitlines():
        words = line.split()
        if len(words) < 2 or words[0] != "[GNUPG:]":
            continue
        tag = words[1]
        if tag == "GOODSIG":
            sig.state, sig.who = "good", _clean(" ".join(words[3:]))
        elif tag == "BADSIG":
            sig.state, sig.who = "bad", _clean(" ".join(words[3:]))
        elif tag in ("ERRSIG", "NO_PUBKEY") and sig.state not in ("good", "bad"):
            sig.state = "unknown_key"
        elif tag == "VALIDSIG" and len(words) > 2:
            sig.fingerprint = words[2]
        elif tag in ("TRUST_FULLY", "TRUST_ULTIMATE"):
            sig.trusted = True
    return sig


def verify(raw: bytes, run: Callable = subprocess.run) -> Signature | None:
    """The signature on a signed message, checked by gpg (OpenPGP) or gpgsm (S/MIME); None when it has none."""
    what = kind(raw)
    smime = what == "smime_signed"
    if what not in ("signed", "smime_signed"):
        return None
    parts = _signed_parts(raw[:MAX_INPUT])
    if parts is None:
        return Signature("error", kind="smime" if smime else "openpgp")
    signed, signature = parts
    with tempfile.TemporaryDirectory(prefix="dai-j-") as tmp:  # 0700, removed at once
        data, sig = Path(tmp) / "signed", Path(tmp) / "signature"
        data.write_bytes(signed)
        sig.write_bytes(signature)
        tool = ["gpgsm", "--batch", "--status-fd", "1", "--verify", str(sig), str(data)] if smime else \
            ["gpg", "--batch", "--no-tty", "--status-fd", "1", "--verify", str(sig), str(data)]
        try:
            result = run(tool, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return Signature("error", kind="smime" if smime else "openpgp")
    return _status(result.stdout, smime)


def decrypt(raw: bytes, run: Callable = subprocess.run) -> bytes | None:
    """The inner message of an OpenPGP-encrypted mail, or None. Shown, never saved."""
    if kind(raw) not in ("encrypted", "inline_encrypted"):
        return None
    message = email.message_from_bytes(raw[:MAX_INPUT], policy=email.policy.compat32)
    if message.is_multipart():
        parts = message.get_payload()
        armored = parts[1].get_payload(decode=True) if isinstance(parts, list) and len(parts) > 1 else b""
    else:
        payload = message.get_payload(decode=True) or b""
        start = payload.find(b"-----BEGIN PGP MESSAGE-----")
        armored = payload[start:] if start >= 0 else b""
    if not armored:
        return None
    try:
        result = run(["gpg", "--batch", "--no-tty", "--status-fd", "2", "--decrypt"], input=armored,
                     capture_output=True, timeout=DECRYPT_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or b"[GNUPG:] DECRYPTION_OKAY" not in (result.stderr or b""):
        return None
    inner = result.stdout or b""
    if not message.is_multipart():  # inline: the clear text, wrapped as a plain message to show
        return b"Content-Type: text/plain; charset=utf-8\r\n\r\n" + inner
    return inner
