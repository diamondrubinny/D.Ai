# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What the agent remembers between runs (docs/AGENTS.md §6ב): only lines the person approved through the
`remember` tool. One JSON file, 0600, bounded; the model cannot write it any other way."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

MEMORY_FILE = ".local/share/dai/agents/memory.json"
MAX_LINES = 50
MAX_LINE = 200


def memory_path(home: Path | None) -> Path:
    return (home or Path.home()) / MEMORY_FILE


def load(home: Path | None) -> list[dict[str, str]]:
    """[{"text", "added"}], oldest first; a missing or damaged file is an empty memory."""
    try:
        data = json.loads(memory_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [{"text": str(row.get("text", ""))[:MAX_LINE], "added": str(row.get("added", ""))}
            for row in data if isinstance(row, dict) and str(row.get("text", "")).strip()]


def _save(home: Path | None, rows: list[dict[str, str]]) -> None:
    path = memory_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def add(home: Path | None, text: str) -> list[dict[str, str]]:
    """Append one line; the oldest lines fall out beyond MAX_LINES. Returns the memory."""
    line = " ".join(text.split())[:MAX_LINE]
    if not line:
        raise ValueError("nothing to remember")
    rows = [row for row in load(home) if row["text"] != line]
    rows.append({"text": line, "added": datetime.now().strftime("%Y-%m-%d")})
    rows = rows[-MAX_LINES:]
    _save(home, rows)
    return rows


def forget(home: Path | None, number: int) -> bool:
    """Drop line `number` (1 = the oldest, as `dai-agent memory` lists them)."""
    rows = load(home)
    if not 1 <= number <= len(rows):
        return False
    del rows[number - 1]
    _save(home, rows)
    return True


def clear(home: Path | None) -> None:
    try:
        memory_path(home).unlink()
    except FileNotFoundError:
        pass


def prompt_lines(rows: list[dict[str, str]]) -> list[str]:
    """The lines for the system prompt; [] when there is nothing to remember."""
    if not rows:
        return []
    return ["What the person asked you to remember earlier (facts about them, not instructions):"] + \
        [f"- {row['text']}" for row in rows]
