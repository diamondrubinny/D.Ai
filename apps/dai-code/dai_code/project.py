# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The project: root, safe paths, file listing, context selection, redaction."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_LIST = 400
MAX_READ = 64 * 1024
MAX_EDIT = 12 * 1024
CONTEXT_BUDGET = 14_000  # characters of file content sent with a question
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "build", "dist", "target", ".tox",
             ".mypy_cache", ".pytest_cache", ".idea", ".vscode", ".cache", ".next", "vendor"}
# Never sent to the model and never edited.
SENSITIVE = ("*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "id_rsa*", "id_ed25519*", "id_ecdsa*", ".env", ".env.*",
             "*.env", ".netrc", ".npmrc", ".pypirc", "credentials*", "*secret*", "*.gpg", "*.asc")
SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), "[REDACTED GITHUB TOKEN]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED SLACK TOKEN]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED JWT]"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b(\s*[:=]\s*)(['\"]?)[^\s'\"]{4,}\3"),
     r"\1\2\3[REDACTED]\3"),
]
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[֐-׿]{2,}")
STOP = {"the", "and", "for", "with", "what", "where", "how", "this", "that", "does", "from", "into", "file", "code",
        "את", "של", "איפה", "מה", "איך", "זה", "על", "עם"}


class ProjectError(ValueError):
    pass


def find_root(start: Path) -> Path:
    start = start.resolve()
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=10, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return start


def is_sensitive(rel: Path) -> bool:
    if ".git" in rel.parts:
        return True
    return any(fnmatch.fnmatch(rel.name.lower(), pattern) for pattern in SENSITIVE)


def redact(text: str) -> str:
    for pattern, replacement in SECRETS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class Project:
    root: Path

    @staticmethod
    def open(start: Path | None = None) -> "Project":
        root = find_root(start or Path.cwd())
        if root == Path("/") or root == Path.home():
            raise ProjectError(f"refusing to treat {root} as a project; cd into a project folder or use --root")
        return Project(root)

    def resolve(self, name: str, for_edit: bool = False) -> Path:
        """A path inside the project (symlinks resolved), or ProjectError."""
        candidate = (self.root / name).resolve() if not Path(name).is_absolute() else Path(name).resolve()
        try:
            rel = candidate.relative_to(self.root)
        except ValueError as exc:
            raise ProjectError(f"{name} is outside the project ({self.root})") from exc
        if is_sensitive(rel):
            raise ProjectError(f"{rel} looks sensitive (secrets/keys/.git); D.Ai Code does not read or edit it")
        if for_edit and candidate.exists() and not candidate.is_file():
            raise ProjectError(f"{rel} is not a regular file")
        return candidate

    def files(self) -> list[Path]:
        """Project files (relative), from git when possible."""
        names: list[str] = []
        try:
            out = subprocess.run(["git", "-C", str(self.root), "ls-files", "-co", "--exclude-standard"],
                                 capture_output=True, text=True, timeout=20, check=False)
            if out.returncode == 0:
                names = [n for n in out.stdout.splitlines() if n]
        except (OSError, subprocess.TimeoutExpired):
            names = []
        if not names:
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
                for filename in sorted(filenames):
                    names.append(str(Path(dirpath, filename).relative_to(self.root)))
                if len(names) > MAX_LIST * 5:
                    break
        result = []
        for name in names:
            rel = Path(name)
            if any(part in SKIP_DIRS for part in rel.parts) or is_sensitive(rel):
                continue
            result.append(rel)
        return result

    def read_text(self, rel: Path, limit: int = MAX_READ) -> str | None:
        """UTF-8 text of a project file (redacted), or None for binary/huge/unreadable files."""
        path = self.resolve(str(rel))
        try:
            data = path.read_bytes()[: limit + 1]
        except OSError:
            return None
        if len(data) > limit or b"\0" in data[:4096]:
            return None
        try:
            return redact(data.decode("utf-8"))
        except UnicodeDecodeError:
            return None

    def tree(self, files: list[Path] | None = None) -> str:
        listing = [str(f) for f in (files if files is not None else self.files())]
        more = f"\n… and {len(listing) - MAX_LIST} more files" if len(listing) > MAX_LIST else ""
        return "\n".join(listing[:MAX_LIST]) + more

    def context_for(self, question: str, budget: int = CONTEXT_BUDGET, must: list[Path] | None = None) -> str:
        """The most relevant files for a question, within a character budget."""
        words = {w.casefold() for w in WORD.findall(question)} - STOP
        files = self.files()
        scored: list[tuple[int, Path, str]] = []
        for rel in files:
            text = self.read_text(rel, limit=MAX_READ)
            if text is None:
                continue
            name = str(rel).casefold()
            score = sum(10 for w in words if w in name)
            body = text.casefold()
            score += sum(min(body.count(w), 5) for w in words)
            if rel in (must or []):
                score += 1000
            if score:
                scored.append((score, rel, text))
        scored.sort(key=lambda item: (-item[0], str(item[1])))
        parts, used = [], 0
        for _score, rel, text in scored:
            remaining = budget - used
            if remaining < 400:
                break
            snippet = text if len(text) <= remaining else text[: remaining - 40] + "\n… (truncated)"
            parts.append(f"=== {rel} ===\n{snippet}")
            used += len(snippet)
        return "\n\n".join(parts)
