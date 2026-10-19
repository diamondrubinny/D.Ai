# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""A received message is checked before anyone sees it (docs/SEND.md, "Requests and checks").

Everything runs on this computer: nothing is sent anywhere to be checked. Text is checked for what phishing
looks like; pictures are re-drawn in a sandbox by pictures.py, and ClamAV (when its daemon is installed) scans
text and pictures for known malware and phishing signatures.

These are warning signs, not proof: a message with none of them can still be a trick, and the window says so.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}/[^\s<>\"']*", re.IGNORECASE)
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly", "cutt.ly", "rb.gy", "t.ly",
              "shorturl.at", "tiny.cc", "rebrand.ly"}
# Names that phishing pretends to be (Israeli banks and payment apps included); a link that contains one but is
# not on the real site is a classic trick.
BRANDS = {
    "paypal": ("paypal.com",), "apple": ("apple.com", "icloud.com"), "microsoft": ("microsoft.com", "live.com"),
    "google": ("google.com",), "amazon": ("amazon.com",), "facebook": ("facebook.com",), "whatsapp": ("whatsapp.com",),
    "netflix": ("netflix.com",), "leumi": ("leumi.co.il",), "hapoalim": ("bankhapoalim.co.il",),
    "discount": ("discountbank.co.il",), "mizrahi": ("mizrahi-tefahot.co.il",), "paybox": ("payboxapp.com",),
    "israelpost": ("israelpost.co.il",), "gov": ("gov.il",),
}
ASKS = re.compile(
    r"\b(?:password|passcode|verification code|one[- ]time code|otp|pin code|cvv|card number|log ?in to verify|"
    r"verify your (?:account|identity)|confirm your (?:account|details|payment)|account (?:will be )?(?:suspended|"
    r"locked|blocked)|urgent(?:ly)?|act now|within 24 hours|you (?:have )?won|claim your prize|gift card|wire "
    r"transfer|crypto(?:currency)? wallet|seed phrase)\b|"
    r"(?:ה)?סיסמ|(?:ה)?קוד (?:ה)?אימות|(?:ה)?קוד (?:ה)?חד[ -]פעמי|מספר (?:ה)?כרטיס|(?:ה)?תעודת (?:ה)?זהות|"
    r"אמת(?:ו)? את (?:ה)?חשבון|החשבון (?:שלך |שלכם )?(?:ייחסם|"
    r"יינעל|נחסם|הושעה)|דחוף|בתוך 24 שעות|זכית|פרס|כרטיס מתנה|העברה בנקאית|ארנק (?:ה)?קריפטו", re.IGNORECASE)
RISKY_FILES = re.compile(r"\b[\w-]+\.(?:exe|scr|bat|cmd|msi|apk|jar|vbs|js|ps1|lnk|iso|img|docm|xlsm)\b", re.IGNORECASE)
# Letters from other alphabets that look like Latin ones ("pаypal" with a Cyrillic а).
LOOKALIKES = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
                            "ѕ": "s", "ԁ": "d", "ɡ": "g", "ӏ": "l", "ο": "o", "α": "a", "ρ": "p", "ν": "v", "κ": "k",
                            "τ": "t", "ı": "i", "0": "o", "1": "l"})
BIDI_CONTROLS = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩",
                 "‎", "‏", "؜"}

Run = Callable[..., subprocess.CompletedProcess]


@dataclass
class Verdict:
    reasons: list[str] = field(default_factory=list)  # keys of REASONS
    malware: bool = False

    @property
    def suspicious(self) -> bool:
        return self.malware or bool(self.reasons)


# What each sign means, for the window and the command line (English, Hebrew).
REASONS = {
    "malware": ("ClamAV recognised malware or a known phishing message", "‏ClamAV זיהה נוזקה או הודעת פישינג מוכרת"),
    "lookalike": ("a link pretends to be a well-known site", "קישור שמתחזה לאתר מוכר"),
    "punycode": ("a link uses look-alike letters (xn--)", "קישור עם אותיות שנראות כמו אחרות (xn--)"),
    "ip_link": ("a link goes to a bare IP address", "קישור לכתובת IP במקום לשם אתר"),
    "shortener": ("a shortened link hides where it goes", "קישור מקוצר שמסתיר לאן הוא מוביל"),
    "plain_http": ("a link is not encrypted (http)", "קישור לא מוצפן (http)"),
    "asks": ("it asks for a password, a code, card details or urgent action",
             "מבקשים סיסמה, קוד, פרטי כרטיס או פעולה דחופה"),
    "risky_file": ("it mentions a program file to open (.exe, .apk …)", "מוזכר קובץ תוכנה לפתיחה (‎.exe, .apk …)"),
    "hidden_direction": ("it hides the real order of its letters (direction controls)",
                         "מוסתר בה הסדר האמיתי של האותיות (תווי כיוון)"),
}


def _host(link: str) -> str:
    try:
        return (urlsplit(link if "://" in link else "http://" + link).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def _readable(host: str) -> str:
    """xn--... labels as the letters they show (IDNA), so a look-alike domain is compared as it looks."""
    labels = []
    for label in host.split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna")
            except UnicodeError:
                pass
        labels.append(label)
    return ".".join(labels)


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def check_text(text: str) -> list[str]:
    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if any(char in BIDI_CONTROLS for char in text):
        add("hidden_direction")
    for link in URL.findall(text):
        host = _host(link)
        if not host:
            continue
        if link.lower().startswith("http://"):
            add("plain_http")
        if "xn--" in host or any(ord(c) > 127 for c in host):
            add("punycode")
        if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
            add("ip_link")
        if host in SHORTENERS:
            add("shortener")
        flat = unicodedata.normalize("NFKC", _readable(host)).translate(LOOKALIKES)
        for brand, real in BRANDS.items():
            if brand in flat and not any(_on(host, domain) for domain in real):
                add("lookalike")
    if ASKS.search(text):
        add("asks")
    if RISKY_FILES.search(text):
        add("risky_file")
    return reasons


def clamav(data: bytes, run: Run = subprocess.run) -> bool:
    """True when ClamAV's daemon is installed, answers, and recognises something (exit code 1)."""
    if not shutil.which("clamdscan"):
        return False
    try:
        return run(["clamdscan", "--no-summary", "--stdout", "-"], input=data, capture_output=True,
                   timeout=60).returncode == 1
    except (OSError, subprocess.TimeoutExpired):
        return False


def check(kind: int, body: bytes, run: Run = subprocess.run) -> Verdict:
    """The verdict for a received message (message.TEXT or message.PICTURE, after pictures.clean)."""
    from .message import TEXT

    verdict = Verdict()
    if kind == TEXT:
        verdict.reasons = check_text(body.decode("utf-8", "replace"))
    verdict.malware = clamav(body, run)
    if verdict.malware:
        verdict.reasons.insert(0, "malware")
    return verdict


def describe(reasons: list[str], lang: str) -> str:
    from dai_i18n import pick

    return "; ".join(pick(lang, *REASONS[r]) for r in reasons if r in REASONS)
