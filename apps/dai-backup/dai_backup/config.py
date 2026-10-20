# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Settings and the recovery key, both private to the user (0600)."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_DIR = "D.Ai-Backup"
DEFAULT_FOLDERS = ("Documents", "Pictures", "Desktop", "Music", "Videos")
EXCLUDES = ("**/.cache", "**/node_modules", "**/__pycache__", "**/.Trash-*", "**/*.part", "**/.venv", "**/venv")
MACHINES = ".local/share/dai/vm/machines"   # where D.Ai VM keeps the disks (docs/VM.md)


def config_dir(home: Path | None = None) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    return (Path(base) if base else (home or Path.home()) / ".config") / "dai"


@dataclass
class Settings:
    repo: str
    folders: list[str]
    created: float = 0.0
    last_backup: float = 0.0
    last_maintenance: float = 0.0
    last_reminder: float = 0.0
    history: list[dict] = field(default_factory=list)   # recent runs: time, ok, detail
    machines: bool = False                              # D.Ai VM disks too (docs/VM.md §13): big, so a choice

    @property
    def repo_path(self) -> Path:
        return Path(self.repo)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def settings_path(home: Path | None = None) -> Path:
    return config_dir(home) / "backup.json"


def key_path(home: Path | None = None) -> Path:
    return config_dir(home) / "backup.key"


def load(home: Path | None = None) -> Settings | None:
    try:
        data = json.loads(settings_path(home).read_text(encoding="utf-8"))
        return Settings(**{k: v for k, v in data.items() if k in Settings.__dataclass_fields__})
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save(settings: Settings, home: Path | None = None) -> None:
    settings.history = settings.history[-20:]
    _write_private(settings_path(home), json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n")


def new_key(home: Path | None = None) -> str:
    """A random recovery key, saved for scheduled runs and shown once to the user."""
    raw = secrets.token_hex(16).upper()  # 128 bits, easy to copy by hand
    key = "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))
    _write_private(key_path(home), key + "\n")
    return key


def candidate_drives(user: str | None = None, roots: tuple[str, ...] = ("/media", "/run/media")) -> list[Path]:
    """Mounted removable drives (udisks mounts them under /media/<user>/<label>)."""
    user = user or os.environ.get("USER") or Path.home().name
    found = []
    for root in roots:
        base = Path(root) / user
        try:
            found += sorted(p for p in base.iterdir() if p.is_dir() and os.access(p, os.W_OK))
        except OSError:
            continue
    return found
