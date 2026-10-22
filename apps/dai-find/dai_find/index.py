# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The content index: what the documents in the home folder say (docs/BEYOND.md §11).

A single SQLite file with an FTS5 table, owned by the user (0600) in the cache folder, so it never
leaves the computer and D.Ai Backup does not carry it. Built by `dai-find index` (a user timer runs
it when the computer is up, at the lowest priority) and refreshed incrementally: only files whose
size or modification time changed are read again, and files that vanished are forgotten.

Text comes from plain files (.txt .md .csv), from the XML inside Office and OpenDocument zips (no
libraries), and from `pdftotext` for the first pages of a PDF. Nothing else is parsed: a file that
cannot be read is skipped, never executed or converted.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .query import HE_PREFIX

INDEX_REL = Path(".cache") / "dai" / "find-index.sqlite"
PLAIN = {".txt", ".md", ".csv", ".rst", ".log"}
ZIPPED = {
    ".docx": ("word/document.xml",),
    ".pptx": ("ppt/slides/",),
    ".xlsx": ("xl/sharedStrings.xml",),
    ".odt": ("content.xml",),
    ".odp": ("content.xml",),
    ".ods": ("content.xml",),
}
PDF = {".pdf"}
MAX_FILE_BYTES = 20 * 1024 * 1024    # larger files are left alone
MAX_TEXT = 200_000                   # characters kept per file
PDF_PAGES = 20
# Two-letter Hebrew prefixes that reach a word in running text (ו + ה/ב/ל/מ/ש/כ, ש/כ + ה/ב/ל/מ).
HE_DOUBLE = ("וה", "וב", "ול", "ומ", "וש", "וכ", "שה", "שב", "של", "שמ", "כש", "מה", "לה", "בה")
Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Match:
    path: Path
    snippet: str


@dataclass
class Report:
    indexed: int = 0      # files read this run
    removed: int = 0      # files forgotten this run
    total: int = 0        # files in the index afterwards
    complete: bool = True # False when the time budget ended the walk


def index_path(home: Path) -> Path:
    return home / INDEX_REL


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    conn = sqlite3.connect(path)
    if not existed:
        os.chmod(path, 0o600)
    conn.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS content USING fts5"
                 "(path UNINDEXED, body, tokenize='unicode61 remove_diacritics 2')")
    return conn


def _strip_xml(data: bytes) -> str:
    text = data.decode("utf-8", "ignore")
    text = re.sub(r"</(?:w:p|text:p|text:h|a:p|si)>", "\n", text)  # paragraph ends become line breaks
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", text)


def extract(path: Path, run: Run = subprocess.run) -> str | None:
    """The text of a document, or None when the file is not one this index reads."""
    suffix = path.suffix.lower()
    try:
        if suffix in PLAIN:
            with path.open("rb") as handle:
                return handle.read(MAX_TEXT * 2).decode("utf-8", "ignore")[:MAX_TEXT]
        if suffix in ZIPPED:
            parts = []
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    if any(member == want or (want.endswith("/") and member.startswith(want) and member.endswith(".xml"))
                           for want in ZIPPED[suffix]):
                        info = archive.getinfo(member)
                        if info.file_size > MAX_FILE_BYTES:
                            continue
                        parts.append(_strip_xml(archive.read(member)))
                        if sum(len(p) for p in parts) > MAX_TEXT:
                            break
            return "\n".join(parts)[:MAX_TEXT]
        if suffix in PDF:
            result = run(["pdftotext", "-q", "-l", str(PDF_PAGES), "-enc", "UTF-8", str(path), "-"],
                         capture_output=True, text=True, timeout=60, check=False)
            return (result.stdout or "")[:MAX_TEXT] if result.returncode == 0 else ""
    except (OSError, zipfile.BadZipFile, subprocess.SubprocessError, UnicodeDecodeError):
        return ""
    return None


def readable(path: Path) -> bool:
    return path.suffix.lower() in PLAIN or path.suffix.lower() in ZIPPED or path.suffix.lower() in PDF


def build(home: Path, entries, budget: float = 120.0, run: Run = subprocess.run) -> Report:
    """Refresh the index from the files listed (path, mtime, size), within a time budget."""
    report = Report()
    deadline = time.monotonic() + budget
    conn = _connect(index_path(home))
    try:
        known = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT path, mtime, size FROM files")}
        seen = set()
        for entry in entries:
            path = Path(entry.path)
            if not readable(path) or entry.size > MAX_FILE_BYTES:
                continue
            key = str(path)
            seen.add(key)
            if known.get(key) == (entry.when, entry.size):
                continue
            if time.monotonic() > deadline:
                report.complete = False
                break
            text = extract(path, run)
            if text is None:
                continue
            conn.execute("DELETE FROM content WHERE path = ?", (key,))
            conn.execute("INSERT INTO content (path, body) VALUES (?, ?)", (key, text))
            conn.execute("INSERT OR REPLACE INTO files (path, mtime, size) VALUES (?, ?, ?)", (key, entry.when, entry.size))
            report.indexed += 1
        if report.complete:
            for key in set(known) - seen:
                conn.execute("DELETE FROM content WHERE path = ?", (key,))
                conn.execute("DELETE FROM files WHERE path = ?", (key,))
                report.removed += 1
        conn.commit()
        report.total = conn.execute("SELECT count(*) FROM files").fetchone()[0]
    finally:
        conn.close()
    return report


def status(home: Path) -> int | None:
    """How many files the index knows, or None when there is no index yet."""
    path = index_path(home)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT count(*) FROM files").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def clear(home: Path) -> bool:
    path = index_path(home)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _forms(word: str) -> list[str]:
    """FTS5 terms for one word: the word with any ending, and in Hebrew also with the prefixes that
    attach to it in running text (שכירות → השכירות, לשכירות, ושה…)."""
    word = re.sub(r'["*]', "", word)
    if not word:
        return []
    forms = [word]
    if re.search(r"[֐-׿]", word):  # i18n: ok (Hebrew letters)
        forms += [letter + word for letter in HE_PREFIX] + [double + word for double in HE_DOUBLE]
    return [f'"{form}" *' for form in forms]


def fts_query(phrases: list[str]) -> str:
    """Every phrase must appear; a phrase's words in order, each with any ending."""
    groups = []
    for phrase in phrases:
        words = [w for w in re.findall(r"[\w֐-׿]+", phrase) if w]  # i18n: ok
        if not words:
            continue
        if len(words) == 1:
            groups.append("(" + " OR ".join(_forms(words[0])) + ")")
        else:
            # A phrase of several words: the exact phrase, with the usual endings on its last word.
            groups.append('("' + " ".join(words) + '" *)')
    return " AND ".join(groups)


def lookup(home: Path, phrases: list[str], limit: int = 200) -> list[Match]:
    """Files whose text has every phrase, best first, with a snippet around the match."""
    query = fts_query(phrases)
    path = index_path(home)
    if not query or not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT path, snippet(content, 1, '', '', '…', 12) FROM content WHERE content MATCH ? "
                "ORDER BY bm25(content) LIMIT ?", (query, limit)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [Match(Path(row[0]), re.sub(r"\s+", " ", row[1]).strip()) for row in rows]
