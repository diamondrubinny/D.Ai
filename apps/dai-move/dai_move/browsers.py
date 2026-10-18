# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Bookmarks from Chrome and Edge, and the names of saved Wi-Fi networks.

Bookmarks are written as a standard HTML bookmarks file that Firefox (and
every other browser) can import. Wi-Fi passwords are encrypted by Windows
for the old computer (DPAPI) and cannot be read, so only names are listed.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

BROWSERS = {
    "Chrome": "AppData/Local/Google/Chrome/User Data/Default/Bookmarks",
    "Edge": "AppData/Local/Microsoft/Edge/User Data/Default/Bookmarks",
}
WLAN = "ProgramData/Microsoft/Wlansvc/Profiles/Interfaces"
SAFE_URL = re.compile(r"^(?:https?|ftp)://", re.IGNORECASE)


def _walk(node: dict, out: list[str], depth: int) -> int:
    count = 0
    if node.get("type") == "url":
        url = node.get("url", "")
        if SAFE_URL.match(url):  # never javascript: or file: links
            out.append(f'{"    " * depth}<DT><A HREF="{html.escape(url, quote=True)}">{html.escape(node.get("name", url))}</A>')
            count += 1
    elif node.get("type") == "folder" or "children" in node:
        out.append(f'{"    " * depth}<DT><H3>{html.escape(node.get("name", ""))}</H3>')
        out.append(f'{"    " * depth}<DL><p>')
        for child in node.get("children", []):
            count += _walk(child, out, depth + 1)
        out.append(f'{"    " * depth}</DL><p>')
    return count


def bookmarks_html(windows_home: Path) -> tuple[str, int]:
    """One HTML file with every browser's bookmarks; (content, number of links)."""
    lines = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>",
             '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
             "<TITLE>Bookmarks from Windows</TITLE>", "<H1>Bookmarks from Windows</H1>", "<DL><p>"]
    total = 0
    for browser, relative in BROWSERS.items():
        path = windows_home / relative
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        roots = data.get("roots", {}) if isinstance(data, dict) else {}
        lines.append(f"    <DT><H3>{browser}</H3>")
        lines.append("    <DL><p>")
        for key in ("bookmark_bar", "other", "synced"):
            if isinstance(roots.get(key), dict):
                total += _walk(roots[key], lines, 2)
        lines.append("    </DL><p>")
    lines.append("</DL><p>")
    return "\n".join(lines) + "\n", total


def wifi_names(windows_root: Path) -> list[str]:
    names = set()
    for profile in (windows_root / WLAN).glob("*/*.xml"):
        try:
            text = profile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(r"<name>([^<]{1,64})</name>", text)
        if match:
            names.add(html.unescape(match.group(1)))
    return sorted(names)


# Outlook keeps mail in .pst files (and .ost, a copy of an Exchange or Outlook.com mailbox) in these places.
OUTLOOK = ("Documents/Outlook Files", "AppData/Local/Microsoft/Outlook")


def outlook_files(home: Path) -> list[Path]:
    """The Outlook data files of a Windows user, to hand to J (docs/MAIL.md §11). Only read; no symlinks."""
    found = []
    for relative in OUTLOOK:
        folder = home / relative
        if not folder.is_dir() or folder.is_symlink():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in (".pst", ".ost") and path.is_file() and not path.is_symlink():
                found.append(path)
    return found

