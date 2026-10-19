# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Showing mail safely (docs/MAIL.md §5).

HTML mail is rebuilt from an allow-list: no scripts, no styles that can
hide or fake text, no forms, no frames, and nothing loaded from the network
(remote images are tracking pixels). Links keep only http, https and mailto
and show where they really go. Every paragraph gets dir="auto" so Hebrew and
English each read in their own direction.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from dai_style import color

ALLOWED = {"p", "br", "div", "span", "b", "strong", "i", "em", "u", "s", "a", "ul", "ol", "li", "blockquote", "pre",
           "code", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "td", "th", "hr", "sub", "sup",
           "small", "big", "font", "center"}
BLOCKS = {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "pre", "center"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "noscript", "template", "svg",
                     "math", "form", "select", "textarea", "button", "frameset", "frame", "audio", "video", "canvas"}
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "source", "wbr"}
SAFE_URL = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)
DIRECTIONS = {"rtl", "ltr", "auto"}


class _Cleaner(HTMLParser):
    def __init__(self, blocked_label: str) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skip = 0
        self.blocked = 0
        self.blocked_label = blocked_label

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.skip:
            if tag in DROP_WITH_CONTENT and tag not in VOID:
                self.skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            self.skip = 1
            return
        if tag == "img":
            self.blocked += 1
            alt = next((v for k, v in attrs if k.lower() == "alt" and v), "")
            self.out.append(f"<span>[{html.escape(alt or self.blocked_label)}]</span>")
            return
        if tag not in ALLOWED:
            return
        kept = []
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            href = values.get("href", "").strip()
            if SAFE_URL.match(href):
                kept.append(f'href="{html.escape(href, quote=True)}"')
                kept.append(f'title="{html.escape(href, quote=True)}"')  # where it really goes
        if values.get("dir", "").lower() in DIRECTIONS:
            kept.append(f'dir="{values["dir"].lower()}"')
        elif tag in BLOCKS:
            kept.append('dir="auto"')
        if tag in ("td", "th"):
            for name in ("colspan", "rowspan"):
                if values.get(name, "").isdigit():
                    kept.append(f'{name}="{min(int(values[name]), 50)}"')
        if tag == "font":
            tag = "span"  # its colour and size can hide text
        self.out.append(f"<{tag}{' ' if kept else ''}{' '.join(kept)}>")
        if tag not in VOID:
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = "span" if tag.lower() == "font" else tag.lower()
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip -= 1
            return
        if tag in self.open:
            while self.open:
                last = self.open.pop()
                self.out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        return "".join(self.out) + "".join(f"</{t}>" for t in reversed(self.open))


def clean_html(source: str, blocked_label: str = "image blocked") -> tuple[str, int]:
    """(safe HTML, how many images were blocked)."""
    cleaner = _Cleaner(blocked_label)
    cleaner.feed(source[:2_000_000])
    cleaner.close()
    return cleaner.result(), cleaner.blocked


def text_to_html(text: str) -> str:
    """Plain text as paragraphs that each find their own direction; links become clickable."""
    out = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        escaped = html.escape(paragraph, quote=False)
        escaped = re.sub(r"(https?://[^\s<>\"']+)", lambda m: f'<a href="{m.group(1)}" title="{m.group(1)}">'
                         f"{m.group(1)}</a>", escaped)
        quoted = paragraph.startswith(">")
        style = f' style="color:{color("muted")}"' if quoted else ""
        out.append(f'<p dir="auto"{style}>{escaped or "&nbsp;"}</p>')
    return "".join(out)


def html_to_text(source: str) -> str:
    """For replies: the readable text of an HTML message."""
    cleaned, _ = clean_html(source, "")
    cleaned = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", cleaned)
    text = html.unescape(re.sub(r"<[^>]+>", "", cleaned))
    return re.sub(r"\n{3,}", "\n\n", text).strip()
