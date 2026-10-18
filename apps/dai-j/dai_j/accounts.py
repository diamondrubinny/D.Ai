# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Accounts and where their passwords live (docs/MAIL.md §4, §5).

The account list (no passwords) is ~/.local/share/dai-j/accounts.json, 0600 in
a 0700 folder. Passwords go to the desktop keyring (Secret Service, through
secret-tool) and never into a file; without a keyring J keeps the password in
memory for this session only. secret-tool reads the password from stdin, so
it never appears in a process list.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .discover import Server

SERVICE = "dai-j"


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    path = base / "dai-j"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


@dataclass
class Account:
    address: str
    name: str                 # the sender name people see
    incoming: Server
    outgoing: Server
    folders: dict[str, str] = field(default_factory=dict)   # role (sent, trash, drafts, archive, junk) -> IMAP name

    @property
    def id(self) -> str:
        return self.address.lower()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        return cls(address=data["address"], name=data.get("name", ""), incoming=Server(**data["incoming"]),
                   outgoing=Server(**data["outgoing"]), folders=dict(data.get("folders", {})))


def load(directory: Path | None = None) -> list[Account]:
    path = (directory or data_dir()) / "accounts.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    result = []
    for row in rows if isinstance(rows, list) else []:
        try:
            result.append(Account.from_dict(row))
        except (KeyError, TypeError):
            continue  # a damaged entry is skipped, not fatal
    return result


def save(accounts: list[Account], directory: Path | None = None) -> None:
    directory = directory or data_dir()
    data = json.dumps([a.to_dict() for a in accounts], ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".accounts.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / "accounts.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Keyring:
    """Passwords in the Secret Service; a session-only memory when there is none."""

    def __init__(self, runner=subprocess.run, which=shutil.which) -> None:
        self.runner = runner
        self.which = which
        self.memory: dict[str, str] = {}

    def available(self) -> bool:
        return self.which("secret-tool") is not None

    def _run(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess | None:
        try:
            return self.runner(["secret-tool", *args], input=stdin, capture_output=True, text=True, timeout=20,
                               check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def store(self, account_id: str, password: str) -> bool:
        """True when the keyring keeps it; otherwise it is kept for this session only."""
        self.memory[account_id] = password
        if not self.available():
            return False
        result = self._run(["store", f"--label=J: {account_id}", "service", SERVICE, "account", account_id], password)
        return result is not None and result.returncode == 0

    def get(self, account_id: str) -> str | None:
        if account_id in self.memory:
            return self.memory[account_id]
        if not self.available():
            return None
        result = self._run(["lookup", "service", SERVICE, "account", account_id])
        if result is None or result.returncode != 0 or not result.stdout:
            return None
        self.memory[account_id] = result.stdout.rstrip("\n")
        return self.memory[account_id]

    def forget(self, account_id: str) -> None:
        self.memory.pop(account_id, None)
        if self.available():
            self._run(["clear", "service", SERVICE, "account", account_id])
