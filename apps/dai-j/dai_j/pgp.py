# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Signed and encrypted mail (docs/MAIL.md §14-15): OpenPGP (RFC 3156) and S/MIME signatures, OpenPGP decryption,
and signing and encrypting what is sent (OpenPGP/MIME).

Everything goes through the system's own GnuPG (gpg, gpgsm) with fixed
arguments and no shell; J holds no keys and no cryptography of its own. The
person's keys stay in their GnuPG home, and passphrases are asked by
gpg-agent's own window, never by J. A decrypted message is shown and never
saved: J's store keeps only what arrived.
"""

from __future__ import annotations

import base64
import copy
import email
import email.policy
import os
import re
import secrets
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses
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
    """"signed" (OpenPGP), "smime_signed", "encrypted" (OpenPGP), "smime_encrypted", "inline_signed",
    "inline_encrypted" or ""."""
    message = email.message_from_bytes(raw[:MAX_INPUT], policy=email.policy.compat32)
    ctype = message.get_content_type()
    protocol = (message.get_param("protocol") or "").lower()
    if ctype == "multipart/signed" and protocol == "application/pgp-signature":
        return "signed"
    if ctype == "multipart/signed" and protocol in ("application/pkcs7-signature", "application/x-pkcs7-signature"):
        return "smime_signed"
    if ctype == "multipart/encrypted" and protocol == "application/pgp-encrypted":
        return "encrypted"
    if ctype in ("application/pkcs7-mime", "application/x-pkcs7-mime") and \
            (message.get_param("smime-type") or "enveloped-data").lower() in ("enveloped-data", "authenveloped-data"):
        return "smime_encrypted"
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


def protected_subject(inner: bytes) -> str:
    """The real subject a decrypted message carries inside (protected headers), or ""."""
    part = email.message_from_bytes(inner[:MAX_INPUT], policy=email.policy.default)
    if part.get_content_type() == "multipart/signed" and part.is_multipart():  # signed, then encrypted
        part = next(iter(part.iter_parts()), part)
    if (part.get_param("protected-headers") or "") != "v1":
        return ""
    return _clean(str(part.get("Subject", "")))


def decrypt(raw: bytes, run: Callable = subprocess.run) -> bytes | None:
    """The inner message of an OpenPGP- or S/MIME-encrypted mail, or None. Shown, never saved."""
    what = kind(raw)
    if what not in ("encrypted", "inline_encrypted", "smime_encrypted"):
        return None
    message = email.message_from_bytes(raw[:MAX_INPUT], policy=email.policy.compat32)
    if what == "smime_encrypted":
        der = message.get_payload(decode=True) or b""
        try:
            result = run(["gpgsm", "--batch", "--status-fd", "2", "--decrypt"], input=der, capture_output=True,
                         timeout=DECRYPT_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.SubprocessError):
            return None
        ok = der and result.returncode == 0 and b"[GNUPG:] DECRYPTION_OKAY" in (result.stderr or b"")
        return (result.stdout or None) if ok else None
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


# --------------------------------------------------------------------------
# Sending: OpenPGP/MIME (RFC 3156 §5 signed, §4 encrypted, §6.2 both at once)
# --------------------------------------------------------------------------

SIGN_TIMEOUT = 180          # gpg-agent may be waiting for the passphrase
ADDRESS = re.compile(r"^[^@\s<>,;\"']{1,64}@[A-Za-z0-9.-]{1,253}$")


class ProtectError(ValueError):
    """Why a message could not be signed or encrypted; nothing was sent."""


def _boundary() -> str:
    return "=-dai-j-" + secrets.token_hex(12)


def _headers(message: EmailMessage, content_type: str) -> bytes:
    """The outer headers (everything but Content-*), then MIME-Version and the new Content-Type, in CRLF form."""
    policy = email.policy.SMTP
    out = b"".join(policy.fold_binary(name, value) for name, value in message.items()
                   if not name.lower().startswith("content-") and name.lower() != "mime-version")
    return out + b"MIME-Version: 1.0\r\n" + policy.fold_binary("Content-Type", content_type)


PROTECTED = ("From", "To", "Cc", "Subject", "Date", "Message-ID", "In-Reply-To", "References")
HIDDEN_SUBJECT = "..."


def _inner(message: EmailMessage) -> bytes:
    """The body as a MIME part (its Content-* headers and content), canonical CRLF and 7-bit safe.

    The part also carries the real From, To, Cc, Subject and Date, marked protected-headers="v1": signed with the
    body, and inside the encryption, so the real subject travels only there."""
    part = copy.deepcopy(message)
    for name in list(part.keys()):
        if not name.lower().startswith("content-"):
            del part[name]
    for name in PROTECTED:
        for value in message.get_all(name, []):
            part[name] = value
    part.set_param("protected-headers", "v1")
    for leaf in part.walk():
        if not leaf.is_multipart() and leaf.get("Content-Transfer-Encoding", "").lower() in ("8bit", "binary"):
            payload = leaf.get_content()
            leaf.set_content(payload, subtype=leaf.get_content_subtype(), cte="quoted-printable")
    raw = part.as_bytes(policy=email.policy.SMTP)
    return re.sub(rb"(?<!\r)\n", b"\r\n", raw)


def _addresses(message: EmailMessage) -> list[str]:
    found = [address for _, address in getaddresses(message.get_all("To", []) + message.get_all("Cc", []))]
    return [a for a in dict.fromkeys(found) if ADDRESS.match(a)]


def _gpg(args: list[str], data: bytes, run: Callable) -> bytes:
    try:
        result = run(["gpg", "--batch", "--no-tty", "--status-fd", "2", "--armor", *args], input=data,
                     capture_output=True, timeout=SIGN_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        raise ProtectError("gpg") from None
    status = (result.stderr or b"").decode("utf-8", "replace")
    if result.returncode != 0 or not result.stdout:
        if "INV_RECP" in status or "NO_PUBKEY" in status:
            raise ProtectError("recipient_key")
        if "INV_SGNR" in status or "NO_SECKEY" in status or "secret key not available" in status:
            raise ProtectError("own_key")
        raise ProtectError("gpg")
    return result.stdout


MICALG = {"2": "sha-1", "8": "sha-256", "9": "sha-384", "10": "sha-512", "11": "sha-224"}  # OpenPGP hash ids


def signing_method(address: str, run: Callable = subprocess.run) -> str:
    """"openpgp" when there is an OpenPGP key of yours for the address, else "smime" for an S/MIME certificate,
    else ""."""
    if not ADDRESS.match(address):
        return ""
    for method, tool in (("openpgp", "gpg"), ("smime", "gpgsm")):
        try:
            found = run([tool, "--batch", "--with-colons", "--list-secret-keys", f"<{address}>"], capture_output=True,
                        timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            continue
        kinds = {line.split(b":", 1)[0] for line in (found.stdout or b"").splitlines()}
        if found.returncode == 0 and kinds & {b"sec", b"crs"}:  # gpg: a secret key; gpgsm: a certificate with one
            return method
    return ""


def _has_keys(tool: str, addresses: list[str], run: Callable) -> bool:
    """Whether gpg (OpenPGP keys) or gpgsm (certificates) has a public key for every address."""
    for address in addresses:
        try:
            found = run([tool, "--batch", "--with-colons", "--list-keys", f"<{address}>"], capture_output=True,
                        timeout=TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return False
        kinds = {line.split(b":", 1)[0] for line in (found.stdout or b"").splitlines()}
        if found.returncode != 0 or not kinds & {b"pub", b"crt", b"crs"}:
            return False
    return True


def _smime_encrypted(message: EmailMessage, sender: str, recipients: list[str], inner: bytes, sign: bool,
                     run: Callable) -> bytes:
    """S/MIME enveloped-data (RFC 8551 §3.3), to every recipient and to the sender; signed first when asked."""
    if sign:
        content_type, body = _smime_signature(sender, inner, run)
        inner = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    args = [arg for a in [*recipients, sender] for arg in ("--recipient", a)]
    try:
        result = run(["gpgsm", "--batch", "--status-fd", "2", "--encrypt", *args], input=inner, capture_output=True,
                     timeout=SIGN_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        raise ProtectError("gpg") from None
    if result.returncode != 0 or not result.stdout:
        raise ProtectError("recipient_key")
    outer = copy.deepcopy(message)
    del outer["Subject"]
    outer["Subject"] = HIDDEN_SUBJECT
    content_type = 'application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"'
    head = _headers(outer, content_type) + (b"Content-Transfer-Encoding: base64\r\n"
                                            b'Content-Disposition: attachment; filename="smime.p7m"\r\n')
    return head + b"\r\n" + base64.encodebytes(result.stdout).replace(b"\n", b"\r\n")


def _smime_signed(message: EmailMessage, sender: str, inner: bytes, run: Callable) -> bytes:
    """S/MIME multipart/signed (RFC 8551 §3.5.3) with gpgsm and the sender's certificate."""
    content_type, body = _smime_signature(sender, inner, run)
    return _headers(message, content_type) + b"\r\n" + body


def _smime_signature(sender: str, inner: bytes, run: Callable) -> tuple[str, bytes]:
    """(the multipart/signed Content-Type, its body) for an S/MIME signature over the inner part."""
    try:
        result = run(["gpgsm", "--batch", "--status-fd", "2", "--detach-sign", "--local-user", sender], input=inner,
                     capture_output=True, timeout=SIGN_TIMEOUT, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        raise ProtectError("gpg") from None
    status = (result.stderr or b"").decode("utf-8", "replace")
    if result.returncode != 0 or not result.stdout:
        raise ProtectError("own_key" if "No public key" in status or "NO_SECKEY" in status or "INV_SGNR" in status
                           else "gpg")
    created = re.search(r"\[GNUPG:\] SIG_CREATED \S+ \d+ (\d+)", status)
    micalg = MICALG.get(created.group(1) if created else "", "sha-256")
    der = base64.encodebytes(result.stdout).replace(b"\n", b"\r\n")
    boundary = _boundary()
    content_type = f'multipart/signed; protocol="application/pkcs7-signature"; micalg={micalg}; boundary="{boundary}"'
    b = boundary.encode()
    body = (b"This is an S/MIME signed message\r\n--" + b + b"\r\n" + inner + b"\r\n--" + b + b"\r\n"
            b'Content-Type: application/pkcs7-signature; name="smime.p7s"\r\nContent-Transfer-Encoding: base64\r\n'
            b'Content-Disposition: attachment; filename="smime.p7s"\r\n\r\n' + der + b"\r\n--" + b + b"--\r\n")
    return content_type, body


def protect(message: EmailMessage, sign: bool, encrypt: bool, run: Callable = subprocess.run,
            method: str | None = None) -> bytes:
    """The message, signed and/or encrypted with the sender's and the recipients' keys, as the bytes to send.

    Signing uses the sender's own key: OpenPGP when there is one, else their S/MIME certificate (gpg-agent asks
    for the passphrase in its own window). Encrypting (OpenPGP) needs a key for every recipient, and is also made
    to the sender, so the copy in "Sent" stays readable; the real subject travels only inside (protected headers),
    while the addresses stay outside, readable by the servers on the way.
    """
    sender = next((a for _, a in getaddresses(message.get_all("From", [])) if ADDRESS.match(a)), "")
    if not sender:
        raise ProtectError("own_key")
    inner = _inner(message)
    if encrypt:
        recipients = _addresses(message)
        if not recipients:
            raise ProtectError("recipient_key")
        chosen = method
        if chosen is None:  # OpenPGP when every recipient has an OpenPGP key, else S/MIME when all have certificates
            chosen = "smime" if not _has_keys("gpg", recipients, run) and _has_keys("gpgsm", recipients, run) \
                else "openpgp"
        if chosen == "smime":
            return _smime_encrypted(message, sender, recipients, inner, sign, run)
        args = ["--encrypt", *(arg for a in [*recipients, sender] for arg in ("--recipient", a))]
        if sign:
            args = ["--sign", "--local-user", sender, *args]
        armored = _gpg(args, inner, run)
        boundary = _boundary()
        content_type = f'multipart/encrypted; protocol="application/pgp-encrypted"; boundary="{boundary}"'
        b = boundary.encode()
        body = (b"This is an OpenPGP/MIME encrypted message (RFC 4880 and 3156)\r\n--" + b + b"\r\n"
                b"Content-Type: application/pgp-encrypted\r\nContent-Description: PGP/MIME version identification"
                b"\r\n\r\nVersion: 1\r\n\r\n--" + b + b"\r\n"
                b'Content-Type: application/octet-stream; name="encrypted.asc"\r\n'
                b'Content-Disposition: inline; filename="encrypted.asc"\r\n\r\n'
                + armored.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + b"\r\n--" + b + b"--\r\n")
        outer = copy.deepcopy(message)
        del outer["Subject"]
        outer["Subject"] = HIDDEN_SUBJECT  # the servers on the way see "...", the recipients the real one
        return _headers(outer, content_type) + b"\r\n" + body
    if not sign:
        return message.as_bytes(policy=email.policy.SMTP)
    if (method if method is not None else signing_method(sender, run)) == "smime":
        return _smime_signed(message, sender, inner, run)
    signature = _gpg(["--detach-sign", "--digest-algo", "SHA256", "--local-user", sender], inner, run)
    boundary = _boundary()
    content_type = (f'multipart/signed; micalg=pgp-sha256; protocol="application/pgp-signature"; '
                    f'boundary="{boundary}"')
    b = boundary.encode()
    body = (b"This is an OpenPGP/MIME signed message (RFC 4880 and 3156)\r\n--" + b + b"\r\n" + inner
            + b"\r\n--" + b + b"\r\n"
            b'Content-Type: application/pgp-signature; name="signature.asc"\r\n'
            b"Content-Description: OpenPGP digital signature\r\n\r\n"
            + signature.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n") + b"\r\n--" + b + b"--\r\n")
    return _headers(message, content_type) + b"\r\n" + body

