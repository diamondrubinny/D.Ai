# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The .dway text (docs/WAY.md §2) as a Program: sentences, apps and exact actions, with their line numbers.

No code runs here and nothing is interpreted beyond headings, `let` values and `use:` includes; a line that is
not a heading, a value, an include or inside a section is an error with its line number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 64 * 1024
MAX_LINES = 400
MAX_DEPTH = 3
HEADINGS = {
    "setup": "setup", "הגדרות": "setup", "settings": "setup",
    "apps": "apps", "אפליקציות": "apps", "applications": "apps",
    "exact": "exact", "מדויק": "exact",
}
NAME_KEYS = ("diamond", "יהלום")
LET_KEYS = ("let", "יהי", "תהי")
USE_KEYS = ("use", "כלול", "כללי")
VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
VALUE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
APP_ID = re.compile(r"^[A-Za-z][\w-]*(\.[A-Za-z][\w-]*)+$")


class WayError(ValueError):
    def __init__(self, message: str, line: int = 0, file: str = "") -> None:
        super().__init__(message)
        self.message, self.line, self.file = message, line, file

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}: " if self.line else (f"{self.file}: " if self.file else "")
        return where + self.message


@dataclass(frozen=True)
class Line:
    text: str
    number: int
    file: str


@dataclass
class Program:
    name: str = ""
    values: dict[str, str] = field(default_factory=dict)
    setup: list[Line] = field(default_factory=list)     # D.Ai Tune sentences
    apps: list[Line] = field(default_factory=list)      # recipe ids, recipe sentences, Flathub ids
    exact: list[Line] = field(default_factory=list)     # "@ action.id key=value ..."
    files: list[str] = field(default_factory=list)      # the file and what it included, in order

    @property
    def empty(self) -> bool:
        return not (self.setup or self.apps or self.exact)


def _split_key(line: str) -> tuple[str, str] | None:
    """("let", "minutes = 10") for "let minutes = 10"; ("setup", "") for "setup:"."""
    match = re.match(r"^([A-Za-z]+|[֐-׿]+)\s*:?\s*(.*)$", line)  # i18n: ok (Hebrew keywords)
    if not match:
        return None
    return match.group(1).lower(), match.group(2).strip()


def parse_text(text: str, file: str = "<text>", values: dict[str, str] | None = None, defer: bool = False) -> Program:
    """One file's text, without following includes (parse() does that). defer: leave $values for parse()."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise WayError(f"the file is larger than {MAX_BYTES // 1024} KB", 0, file)
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise WayError(f"more than {MAX_LINES} lines", 0, file)
    program = Program(values=dict(values or {}), files=[file])
    section = ""
    for number, raw in enumerate(lines, 1):
        stripped = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("@") else raw.rstrip()
        if not stripped.strip():
            continue
        indented = stripped[:1].isspace()
        content = stripped.strip()
        if content.startswith("@"):
            if section != "exact":
                raise WayError("an exact action (@ …) belongs under exact:", number, file)
            program.exact.append(Line(content, number, file))
            continue
        key = _split_key(content)
        if not indented and key is not None:
            keyword, rest = key
            if keyword in NAME_KEYS and content[len(keyword):].lstrip().startswith(":"):
                program.name = rest
                continue
            if keyword in LET_KEYS:
                name, _, value = rest.partition("=")
                name, value = name.strip(), value.strip()
                if not VALUE_NAME.match(name) or not value:
                    raise WayError("expected: let NAME = VALUE", number, file)
                program.values[name] = _substitute(value, program.values, number, file)
                continue
            if keyword in USE_KEYS and content[len(keyword):].lstrip().startswith(":"):
                program.files.append(rest)   # resolved by parse()
                continue
            if keyword in HEADINGS and content.endswith(":") and not rest:
                section = HEADINGS[keyword]
                continue
        if not section:
            raise WayError("expected a heading first: setup:, apps: or exact:", number, file)
        getattr(program, section).append(Line(content, number, file))
    if not defer:
        _substitute_all(program)
    return program


def _substitute_all(program: Program) -> None:
    for name in ("setup", "apps", "exact"):
        lines = getattr(program, name)
        lines[:] = [Line(_substitute(line.text, program.values, line.number, line.file), line.number, line.file) for line in lines]


def _substitute(text: str, values: dict[str, str], number: int, file: str) -> str:
    def value(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise WayError(f"unknown value ${name} (define it: let {name} = …)", number, file)
        return values[name]
    return VARIABLE.sub(value, text)


def parse(path: Path, depth: int = 0, values: dict[str, str] | None = None) -> Program:
    """A file and its includes (same folder only), as one Program."""
    if depth > MAX_DEPTH:
        raise WayError("includes nested too deep", 0, str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise WayError(f"cannot read: {exc.strerror or exc}", 0, str(path)) from exc
    program = parse_text(text, path.name, values, defer=True)
    includes = program.files[1:]
    program.files = [path.name]
    for include in includes:
        if "/" in include.replace("\\", "/") or include.startswith(".") or not include.endswith(".dway"):
            raise WayError(f"use: only a .dway file from the same folder ({include})", 0, path.name)
        other = parse(path.with_name(include), depth + 1, program.values)
        program.values.update(other.values)
        program.setup += other.setup
        program.apps += other.apps
        program.exact += other.exact
        program.files += other.files
        if not program.name:
            program.name = other.name
    if depth == 0:
        _substitute_all(program)
    return program


def parse_exact(line: str) -> tuple[str, dict]:
    """"@ firewall.open_port port=8080 proto=tcp" → ("firewall.open_port", {"port": 8080, "proto": "tcp"})."""
    body = line.lstrip("@").strip()
    parts = body.split()
    if not parts or not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", parts[0]):
        raise WayError("expected: @ action.id key=value …")
    params: dict = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if not sep or not VALUE_NAME.match(key):
            raise WayError(f"expected key=value, got {part}")
        params[key] = _value(value)
    return parts[0], params


def _value(raw: str):
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if "," in raw:
        return [_value(v) for v in raw.split(",") if v]
    return raw


def format_exact(action: str, params: dict) -> str:
    def one(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return ",".join(one(v) for v in value)
        return str(value)
    return "@ " + " ".join([action, *(f"{k}={one(v)}" for k, v in params.items())])
