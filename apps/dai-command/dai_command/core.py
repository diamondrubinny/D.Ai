# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Pure logic for D.Ai Command: app index, calculator, layout fixer, history.

Nothing in this module touches the GUI, so it can be unit tested headless.
"""

from __future__ import annotations

import ast
import configparser
import math
import operator
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# --------------------------------------------------------------------------
# Desktop entries
# --------------------------------------------------------------------------

# Field codes from the Desktop Entry Specification; %% is a literal percent.
_FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")


@dataclass(frozen=True)
class AppEntry:
    """A launchable application parsed from a .desktop file."""

    desktop_id: str
    name: str
    exec_args: tuple[str, ...]
    icon: str = ""
    comment: str = ""
    search_terms: tuple[str, ...] = field(default_factory=tuple)
    terminal: bool = False


def _localized(section: configparser.SectionProxy, key: str, langs: Iterable[str]) -> str:
    for lang in langs:
        value = section.get(f"{key}[{lang}]")
        if value:
            return value
    return section.get(key, "")


def _desktop_langs() -> list[str]:
    """Language keys to try, e.g. he_IL.UTF-8 -> ['he_IL', 'he']."""
    raw = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    base = raw.split(".")[0].split("@")[0]
    langs = []
    if base:
        langs.append(base)
        if "_" in base:
            langs.append(base.split("_")[0])
    return langs


def parse_exec(exec_line: str) -> tuple[str, ...]:
    """Split an Exec= value into argv, dropping field codes."""
    cleaned = _FIELD_CODE.sub("", exec_line).replace("%%", "%")
    try:
        return tuple(arg for arg in shlex.split(cleaned) if arg)
    except ValueError:
        return ()


def parse_desktop_file(
    path: Path,
    desktop_id: str,
    current_desktops: Iterable[str] = ("LXQt",),
    langs: Iterable[str] | None = None,
) -> AppEntry | None:
    """Parse one .desktop file; return None when it should not be shown."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # keys are case sensitive
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    entry = parser["Desktop Entry"]

    if entry.get("Type", "Application") != "Application":
        return None
    if entry.getboolean("NoDisplay", fallback=False) or entry.getboolean("Hidden", fallback=False):
        return None

    desktops = {d.casefold() for d in current_desktops}
    only = {d.casefold() for d in entry.get("OnlyShowIn", "").split(";") if d}
    not_in = {d.casefold() for d in entry.get("NotShowIn", "").split(";") if d}
    if only and not (only & desktops):
        return None
    if not_in & desktops:
        return None

    try_exec = entry.get("TryExec")
    if try_exec and not (shutil.which(try_exec) or os.access(try_exec, os.X_OK)):
        return None

    exec_args = parse_exec(entry.get("Exec", ""))
    if not exec_args:
        return None

    langs = list(langs) if langs is not None else _desktop_langs()
    name = _localized(entry, "Name", langs)
    if not name:
        return None

    # Hebrew names are always searchable, so Hebrew speakers on an English
    # system can still type "דפדפן" to find the browser.
    search_langs = [*langs, "he"]
    terms = [name, entry.get("Name", ""), entry.get("GenericName", "")]
    terms += entry.get("Keywords", "").split(";")
    for lang in search_langs:
        terms += [entry.get(f"Name[{lang}]", ""), entry.get(f"GenericName[{lang}]", "")]
        terms += entry.get(f"Keywords[{lang}]", "").split(";")
    return AppEntry(
        desktop_id=desktop_id,
        name=name,
        exec_args=exec_args,
        icon=entry.get("Icon", ""),
        comment=_localized(entry, "Comment", langs) or _localized(entry, "GenericName", langs),
        search_terms=tuple(dict.fromkeys(t.strip().casefold() for t in terms if t.strip())),
        terminal=entry.getboolean("Terminal", fallback=False),
    )


def application_dirs() -> list[Path]:
    """XDG application directories, highest priority first."""
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) / "applications" for d in [data_home, *data_dirs.split(":")] if d]


def load_apps(dirs: Iterable[Path] | None = None) -> list[AppEntry]:
    """Index applications; the first directory providing a desktop id wins."""
    current = [d for d in os.environ.get("XDG_CURRENT_DESKTOP", "LXQt").split(":") if d]
    seen: set[str] = set()
    apps: list[AppEntry] = []
    for base in dirs if dirs is not None else application_dirs():
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.desktop")):
            desktop_id = str(path.relative_to(base)).replace(os.sep, "-")
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            app = parse_desktop_file(path, desktop_id, current)
            if app is not None:
                apps.append(app)
    return apps


def _match_score(query: str, terms: tuple[str, ...]) -> int:
    best = 0
    for index, term in enumerate(terms):
        weight = 3 if index == 0 else 1  # the display name counts most
        if term == query:
            score = 100
        elif term.startswith(query):
            score = 80
        elif any(word.startswith(query) for word in term.split()):
            score = 60
        elif query in term:
            score = 40
        else:
            continue
        best = max(best, score * weight)
    return best


def search_apps(apps: Iterable[AppEntry], query: str, limit: int = 6) -> list[AppEntry]:
    """Rank apps by how well their name, generic name or keywords match."""
    query = query.strip().casefold()
    if not query:
        return []
    scored = [(score, app) for app in apps if (score := _match_score(query, app.search_terms))]
    scored.sort(key=lambda item: (-item[0], item[1].name.casefold()))
    return [app for _, app in scored[:limit]]


# --------------------------------------------------------------------------
# Calculator (AST whitelist, never eval)
# --------------------------------------------------------------------------

_BIN_OPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable[[float], float]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS: dict[str, Callable[..., float]] = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log10,
    "ln": math.log,
    "abs": abs,
    "round": round,
}
_CONSTS = {"pi": math.pi, "e": math.e}
_MAX_EXPONENT = 1000
_MAX_MAGNITUDE = 1e100
_PERCENT_OF = re.compile(r"^\s*([\d.]+)\s*%\s*(?:of|מ|מתוך)\s*([\d.]+)\s*$", re.IGNORECASE)
_LOOKS_NUMERIC = re.compile(r"^[\d\s.+\-*/%()^a-z]+$", re.IGNORECASE)


class CalcError(ValueError):
    """The expression is not a safe arithmetic expression."""


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise CalcError("exponent too large")
        result = _BIN_OPS[type(node.op)](left, right)
        if isinstance(result, complex) or abs(result) > _MAX_MAGNITUDE:
            raise CalcError("result out of range")
        return result
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
        and 1 <= len(node.args) <= 2
    ):
        return _FUNCS[node.func.id](*(_eval_node(arg) for arg in node.args))
    raise CalcError("unsupported expression")


def calculate(expression: str) -> float | None:
    """Evaluate a safe arithmetic expression; None if it is not one."""
    text = expression.strip()
    if not text or len(text) > 200:
        return None
    if match := _PERCENT_OF.match(text):
        return float(match.group(1)) / 100 * float(match.group(2))
    if not _LOOKS_NUMERIC.match(text) or not re.search(r"\d", text):
        return None
    if not re.search(r"[+\-*/%^(]", text):
        return None  # a bare number is not a calculation
    try:
        tree = ast.parse(text.replace("^", "**"), mode="eval")
        value = _eval_node(tree)
    except (CalcError, SyntaxError, ZeroDivisionError, ValueError, OverflowError, TypeError):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def format_number(value: float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.10g}"


# --------------------------------------------------------------------------
# Wrong keyboard layout fixer (US QWERTY <-> Israeli SI-1452)
# --------------------------------------------------------------------------

_US = "qwertyuiopasdfghjkl;'zxcvbnm,./"
_IL = "/'קראטוןםפשדגכעיחלךף,זסבהנמצתץ."
US_TO_HE = dict(zip(_US, _IL))
HE_TO_US = {he: us for us, he in US_TO_HE.items()}
_HEBREW_LETTER = re.compile(r"[א-ת]")
_LATIN_LETTER = re.compile(r"[a-z]", re.IGNORECASE)


def fix_layout(text: str) -> tuple[str, str] | None:
    """Convert text typed in the wrong layout.

    Returns (converted_text, target_language) where target_language is
    'he' or 'en', or None when the text is not a candidate.
    """
    stripped = text.strip()
    if len(stripped) < 2:
        return None
    has_he = bool(_HEBREW_LETTER.search(stripped))
    has_en = bool(_LATIN_LETTER.search(stripped))
    if has_en and not has_he:
        converted = "".join(US_TO_HE.get(ch.lower(), ch) for ch in stripped)
        return (converted, "he") if _HEBREW_LETTER.search(converted) else None
    if has_he and not has_en:
        converted = "".join(HE_TO_US.get(ch, ch) for ch in stripped)
        return (converted, "en") if _LATIN_LETTER.search(converted) else None
    return None


def convert_layout(text: str) -> str | None:
    """Convert a whole selection to the other layout (for the global fixer).

    Unlike fix_layout() this accepts mixed text: the direction follows the
    majority script, and characters without a mapping are kept as they are.
    Returns None when there is nothing to convert.
    """
    he = len(_HEBREW_LETTER.findall(text))
    en = len(_LATIN_LETTER.findall(text))
    if he == en == 0:
        return None
    if en >= he:
        converted = "".join(US_TO_HE.get(ch.lower(), ch) if _LATIN_LETTER.match(ch) or ch in ";',./" else ch for ch in text)
    else:
        converted = "".join(HE_TO_US.get(ch, ch) for ch in text)
    return converted if converted != text else None


# --------------------------------------------------------------------------
# Command history (local file, 0600, ignore-space like bash)
# --------------------------------------------------------------------------


class History:
    def __init__(self, path: Path, limit: int = 200) -> None:
        self.path = path
        self.limit = limit

    @staticmethod
    def default_path() -> Path:
        state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
        return Path(state) / "dai" / "command-history"

    def load(self) -> list[str]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [line for line in lines if line.strip()][-self.limit :]

    def add(self, entry: str) -> None:
        """Record an entry unless it starts with a space (privacy opt-out)."""
        if not entry.strip() or entry.startswith(" "):
            return
        entries = [e for e in self.load() if e != entry] + [entry]
        entries = entries[-self.limit :]
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(entries) + "\n")
        os.replace(tmp, self.path)


# --------------------------------------------------------------------------
# UI strings (Hebrew when the locale is Hebrew, English otherwise)
# --------------------------------------------------------------------------

_STRINGS = {
    "history": ("From history", "מההיסטוריה"),
    "ask": ("Ask D.Ai…", "שאלו את D.Ai…"),
    "ai_soon": ("Local AI · Enter to ask (runs on this computer)", "AI מקומי · Enter לשאלה (רץ במחשב הזה)"),
    "ai_missing": ("Local AI is not ready. Install a model: dai-models install qwen2.5-0.5b",
                   "ה־AI המקומי לא מוכן. התקינו מודל: dai-models install qwen2.5-0.5b"),
    "ai_thinking": ("Thinking…", "חושב…"),
    "terminal": ("Run in terminal", "הרצה בטרמינל"),
    "background": ("Run in background", "הרצה ברקע"),
    "copy": ("Enter to copy", "Enter להעתקה"),
    "fix_he": ("Fix to Hebrew · Enter to copy", "תיקון לעברית · Enter להעתקה"),
    "fix_en": ("Fix to English · Enter to copy", "תיקון לאנגלית · Enter להעתקה"),
    "placeholder": ("Apps, commands, math…    ? ask    > terminal", "אפליקציות, פקודות, חישובים…    ? שאלה    > טרמינל"),
    "hints": ("Enter open  ·  ↑↓ move  ·  Esc close  ·  Alt+Shift language", "הפעלה Enter  ·  ניווט ↑↓  ·  סגירה Esc  ·  שפה Alt+Shift"),
    "mic": ("Local voice dictation (Whisper) — Phase 5", "הכתבה קולית מקומית (Whisper) — שלב 5"),
    "tune_review": ("D.Ai Tune · Enter to review and apply", "D.Ai Tune · Enter לבדיקה והחלה"),
    "tune_unknown": ("Not understood — Enter for examples", "לא הובן — Enter לדוגמאות"),
    "tune_hint": ("Configure the system in words, e.g. !block usb", "התאמת המערכת במילים, למשל !חסום דיסק און קי"),
    "query_name": ("D.Ai Command input", "שורת הפקודות של D.Ai"),
    "results_name": ("Results", "תוצאות"),
}


def ui_language() -> str:
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "he" if value.startswith("he") else "en"
    return "en"


def tr(key: str, lang: str | None = None) -> str:
    english, hebrew = _STRINGS[key]
    return hebrew if (lang or ui_language()) == "he" else english


# --------------------------------------------------------------------------
# Query interpretation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """One result row; `kind` tells the UI how to activate it."""

    kind: str  # app | calc | layout | terminal | run | ai | history | tune
    title: str
    subtitle: str = ""
    icon: str = ""
    payload: object = None


def build_actions(query: str, apps: Iterable[AppEntry], history: Iterable[str] = ()) -> list[Action]:
    """Turn the typed text into an ordered list of actions."""
    text = query.strip()
    if not text:
        return [
            Action("history", entry, tr("history"), "document-open-recent", entry)
            for entry in reversed(list(history)[-6:])
        ]

    if text.startswith("?"):
        question = text[1:].strip()
        return [
            Action(
                "ai",
                question or tr("ask"),
                tr("ai_soon"),
                "dialog-information",
                question,
            )
        ]
    if text.startswith("!"):
        return tune_actions(text[1:].strip())
    if text.startswith(">"):
        command = text[1:].strip()
        return [Action("terminal", command, tr("terminal"), "utilities-terminal", command)] if command else []
    if text.startswith("$"):
        command = text[1:].strip()
        return [Action("run", command, tr("background"), "system-run", command)] if command else []

    actions: list[Action] = []
    if (value := calculate(text)) is not None:
        result = format_number(value)
        actions.append(Action("calc", f"= {result}", tr("copy"), "accessories-calculator", result))

    actions.extend(
        Action("app", app.name, app.comment, app.icon, app) for app in search_apps(apps, text)
    )

    if not actions and (fixed := fix_layout(text)):
        converted, lang = fixed
        actions.append(Action("layout", converted, tr("fix_he" if lang == "he" else "fix_en"), "edit-paste", converted))

    first = text.split()[0]
    if shutil.which(first):
        actions.append(Action("run", text, tr("background"), "system-run", text))
        actions.append(Action("terminal", text, tr("terminal"), "utilities-terminal", text))
    return actions


def tune_actions(request: str) -> list[Action]:
    """Preview a D.Ai Tune plan; applying always happens in dai-tune itself."""
    if not request:
        return [Action("tune", tr("tune_hint"), "dai-tune help", "preferences-system", "")]
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_tune.catalog import CATALOG
        from dai_tune.context import Context
        from dai_tune.planner import plan_from_text
    except ImportError:
        return []
    lang = ui_language()
    plan = plan_from_text(request, Context(lang=lang))
    if not plan.ok:
        return [Action("tune", request, tr("tune_unknown"), "dialog-question", "")]
    icons = {"hardens": "security-high", "weakens": "security-low", "neutral": "preferences-system"}
    effects = {
        "hardens": ("hardens security", "מחזק אבטחה"),
        "weakens": ("weakens security", "מחליש אבטחה"),
        "neutral": ("neutral", "ניטרלי"),
    }
    return [
        Action(
            "tune",
            CATALOG[step.action].summary(step.params, lang),
            f"{effects[step.effect][lang == 'he']} · {tr('tune_review')}",
            icons[step.effect],
            request,
        )
        for step in plan.steps
    ]
