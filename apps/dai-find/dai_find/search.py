# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Search the home folder for a parsed query.

No index is kept on disk (nothing to leak, nothing to keep in sync): the
walk is bounded by a file count and a time budget, skips hidden folders,
caches and vendored code, and never follows symlinks out of the home folder.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .query import KINDS, Query, _bare

SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "site-packages", "snap", "go", "target",
             "build", "dist", "Trash"}
DEFAULT_DIRS = {
    "downloads": ("Downloads", "הורדות"),
    "documents": ("Documents", "מסמכים"),
    "desktop": ("Desktop", "שולחן העבודה"),
    "pictures": ("Pictures", "תמונות"),
    "music": ("Music", "מוזיקה"),
    "videos": ("Videos", "וידאו"),
}
XDG_KEYS = {"downloads": "DOWNLOAD", "documents": "DOCUMENTS", "desktop": "DESKTOP",
            "pictures": "PICTURES", "music": "MUSIC", "videos": "VIDEOS"}


@dataclass(frozen=True)
class Hit:
    path: Path
    when: float     # modification time: when it was downloaded, saved or last edited
    size: int
    kind: str
    snippet: str = ""   # the text around a content match (docs/BEYOND.md §11)

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.when)


def user_dirs(home: Path) -> dict[str, Path]:
    """XDG user folders (~/.config/user-dirs.dirs), with the usual names as fallback."""
    found: dict[str, Path] = {}
    config = home / ".config" / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            match = re.match(r'XDG_(\w+)_DIR="(.*)"', line.strip())
            if match:
                value = Path(match.group(2).replace("$HOME", str(home)))
                for name, key in XDG_KEYS.items():
                    if key == match.group(1) and value != home:
                        found[name] = value
    except OSError:
        pass
    for name, candidates in DEFAULT_DIRS.items():
        if name not in found:
            for candidate in candidates:
                if (home / candidate).is_dir():
                    found[name] = home / candidate
                    break
    return found


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    for kind in ("pdf", "image", "video", "audio", "spreadsheet", "presentation", "archive", "document"):
        if suffix in KINDS[kind]:
            return kind
    return "file"


def _name_matches(name: str, words: list[str]) -> bool:
    name = name.casefold()
    return all(any(form in name for form in _bare(word.casefold())) for word in words)


@dataclass(frozen=True)
class _Entry:
    path: Path
    name: str
    when: float
    size: int


# root → (built at, complete, entries). Memory only, for a few seconds, so
# typing in D.Ai Command does not walk the disk on every key press.
_CACHE: dict[Path, tuple[float, bool, list[_Entry]]] = {}


def _listing(root: Path, max_files: int, budget: float, ttl: float) -> tuple[list[_Entry], bool]:
    cached = _CACHE.get(root)
    if ttl and cached and time.monotonic() - cached[0] < ttl:
        return cached[2], cached[1]
    deadline = time.monotonic() + budget
    entries: list[_Entry] = []
    stack = [root]
    while stack and len(entries) < max_files and time.monotonic() < deadline:
        directory = stack.pop()
        try:
            items = list(os.scandir(directory))
        except OSError:
            continue
        for item in items:
            if item.name.startswith("."):
                continue  # hidden files and folders: config, caches, keys
            try:
                if item.is_dir(follow_symlinks=False):
                    if item.name not in SKIP_DIRS:
                        stack.append(Path(item.path))
                elif item.is_file(follow_symlinks=False):
                    info = item.stat(follow_symlinks=False)
                    # mtime, not ctime: renaming or copying an old file must not make it "new".
                    entries.append(_Entry(Path(item.path), item.name, info.st_mtime, info.st_size))
            except OSError:
                continue
    complete = not stack
    if ttl:
        _CACHE[root] = (time.monotonic(), complete, entries)
    return entries, complete


def search(query: Query, home: Path | None = None, limit: int = 20, max_files: int = 200_000,
           budget: float = 2.0, ttl: float = 0.0) -> list[Hit]:
    """Matching files, newest first. An unspecific query returns nothing."""
    if not query.specific:
        return []
    home = (home or Path.home()).resolve()
    dirs = user_dirs(home)
    roots = [dirs[f] for f in query.folders if f in dirs] or [home]
    extensions = query.extensions
    since = query.since.timestamp() if query.since else None
    until = query.until.timestamp() if query.until else None
    snippets: dict[Path, str] | None = None
    if query.content:
        snippets = _content_matches(home, query.content, max_files, budget)
    hits: list[Hit] = []
    for root in roots:
        if not root.is_dir():
            continue
        entries, _ = _listing(root.resolve(), max_files, budget, ttl)
        for entry in entries:
            if extensions and entry.path.suffix.lower() not in extensions:
                continue
            if (since and entry.when < since) or (until and entry.when >= until):
                continue
            if query.words and not _name_matches(entry.name, query.words):
                continue
            if snippets is not None and entry.path not in snippets and not (
                    query.names_too and _name_matches(entry.name, query.content)):
                continue
            hits.append(Hit(entry.path, entry.when, entry.size, kind_of(entry.path),
                            snippets.get(entry.path, "") if snippets else ""))
    hits.sort(key=lambda hit: hit.when, reverse=True)
    return hits[:limit]


def _content_matches(home: Path, phrases: list[str], max_files: int, budget: float) -> dict[Path, str]:
    """Path → snippet for the files whose text has the phrases. Without an index yet (a new computer),
    a quick one is built first within a short budget, so the first content search still answers."""
    from . import index
    if index.status(home) is None:
        entries, _ = _listing(home, max_files, budget, 0.0)
        index.build(home, entries, budget=min(10.0, max(budget, 2.0)))
    return {match.path: match.snippet for match in index.lookup(home, phrases)}


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
