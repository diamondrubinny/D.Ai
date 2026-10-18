# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Writing mail (docs/MAIL.md §2 items 4-6): every paragraph keeps its own direction.

A message is sent as plain text plus an HTML alternative in which every
paragraph carries its direction: the one the writer chose (the right-to-left
and left-to-right buttons) or "auto", so mixed Hebrew and English arrive the
way they were written, in any mail client.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, format_datetime, getaddresses, localtime, make_msgid

from dai_i18n import pick, text as tr

ADDRESS = re.compile(r"^[^@\s<>,;\"]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")


@dataclass
class Draft:
    sender_name: str
    sender_address: str
    to: str
    cc: str = ""
    subject: str = ""
    paragraphs: list[tuple[str, str]] = field(default_factory=list)   # (text, "rtl" | "ltr" | "auto")
    in_reply_to: str = ""
    references: str = ""


def recipients(field_text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(valid (name, address) pairs, the parts that are not addresses)."""
    parts = [p.strip() for p in re.split(r"[,;\n]", field_text) if p.strip()]
    good, bad = [], []
    for part in parts:
        pairs = getaddresses([part])
        name, address = pairs[0] if pairs else ("", "")
        if ADDRESS.match(address):
            good.append((name, address))
        else:
            bad.append(part)
    return good, bad


def build(draft: Draft) -> EmailMessage:
    to, bad_to = recipients(draft.to)
    cc, bad_cc = recipients(draft.cc)
    if bad_to or bad_cc or not to:
        raise ValueError(", ".join(bad_to + bad_cc) or "no recipients")
    message = EmailMessage()
    message["From"] = formataddr((draft.sender_name, draft.sender_address))
    message["To"] = ", ".join(formataddr(p) for p in to)
    if cc:
        message["Cc"] = ", ".join(formataddr(p) for p in cc)
    message["Subject"] = draft.subject.replace("\n", " ").strip()
    message["Date"] = format_datetime(localtime())
    message["Message-ID"] = make_msgid(domain=draft.sender_address.split("@", 1)[1])
    if draft.in_reply_to:
        message["In-Reply-To"] = draft.in_reply_to
        message["References"] = (draft.references + " " + draft.in_reply_to).strip()
    message["User-Agent"] = "J (D.Ai OS)"
    text = "\n".join(t for t, _ in draft.paragraphs)
    message.set_content(text if text.endswith("\n") else text + "\n")
    blocks = "".join(f'<div dir="{d if d in ("rtl", "ltr") else "auto"}">{html.escape(t) or "<br>"}</div>'
                     for t, d in draft.paragraphs)
    message.add_alternative(f'<!doctype html><html><body>{blocks}</body></html>\n', subtype="html")
    return message


def _strip_prefix(subject: str, prefix: str) -> str:
    rest = re.sub(r"^((re|fw|fwd|השב|הע)\s*:\s*)+", "", subject.strip(), flags=re.IGNORECASE)
    return f"{prefix}: {rest}" if rest else f"{prefix}:"


def quoted(text: str, sender: str, date: float, lang: str) -> list[tuple[str, str]]:
    stamp = time.strftime("%d.%m.%Y %H:%M", time.localtime(date)) if date else ""
    intro = tr(lang, "On {stamp}, {sender} wrote:", "ב־{stamp}, {sender} כתב/ה:", stamp=stamp, sender=sender)
    lines = [("", "auto"), ("", "auto"), (intro, "auto")]
    lines += [("> " + line, "auto") for line in text.rstrip().split("\n")[:400]]
    return lines


def reply(original: dict, body_text: str, me: str, everyone: bool, lang: str) -> Draft:
    to = [original.get("sender_address") or ""]
    cc: list[str] = []
    if everyone:
        others, _ = recipients(original.get("recipients") or "")
        cc = [formataddr(p) for p in others if p[1].lower() not in (me.lower(), to[0].lower())]
    return Draft(sender_name="", sender_address=me, to=", ".join(to), cc=", ".join(cc),
                 subject=_strip_prefix(original.get("subject") or "", "Re"),
                 paragraphs=quoted(body_text, original.get("sender") or "", original.get("date") or 0, lang),
                 in_reply_to=original.get("message_id") or "", references=original.get("refs") or "")


def forward(original: dict, body_text: str, me: str, lang: str) -> Draft:
    head = pick(lang, "---------- Forwarded message ----------", "---------- הודעה שהועברה ----------")
    lines = [("", "auto"), (head, "auto"), (f"From: {original.get('sender_address') or ''}", "ltr"),
             (f"Subject: {original.get('subject') or ''}", "auto"), ("", "auto")]
    lines += [(line, "auto") for line in body_text.rstrip().split("\n")]
    return Draft(sender_name="", sender_address=me, to="", subject=_strip_prefix(original.get("subject") or "", "Fwd"),
                 paragraphs=lines)
