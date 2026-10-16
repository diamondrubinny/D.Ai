"""Execution context: filesystem root, home, command runner and language.

Tests swap the root for a temporary directory and the runner for a fake, so
every action can be exercised without touching the real system.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

# Commands run with a fixed, minimal environment (no inherited PATH tricks).
SAFE_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "DEBIAN_FRONTEND": "noninteractive",
}


class ActionError(RuntimeError):
    """An action failed while being applied or undone."""


def run_command(argv: Sequence[str]) -> subprocess.CompletedProcess:
    """Run argv (never through a shell) and capture its output."""
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=900,
        env=SAFE_ENV,
        check=False,
    )


def spawn_detached(argv: Sequence[str]) -> None:
    subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@dataclass
class Context:
    root: Path = Path("/")
    home: Path = field(default_factory=Path.home)
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess] = run_command
    spawner: Callable[[Sequence[str]], None] = spawn_detached
    lang: str = "en"

    def path(self, absolute: str | os.PathLike) -> Path:
        """Map an absolute system path into this context's root."""
        return self.root / str(absolute).lstrip("/")

    def user_path(self, relative: str) -> Path:
        return self.home / relative

    def run(self, argv: Sequence[str], check: bool = True) -> subprocess.CompletedProcess:
        result = self.runner(argv)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
            raise ActionError(f"{argv[0]} failed (exit {result.returncode}): {' '.join(detail)}")
        return result


def detect_lang() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "he" if value.startswith("he") else "en"
    return "en"


def write_file(path: Path, content: str | bytes, mode: int = 0o644) -> None:
    """Atomically replace a file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    tmp = path.with_name(f".{path.name}.dai-tune.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return default
