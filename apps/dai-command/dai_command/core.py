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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from dai_i18n import pick, ui_lang

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
    raw = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""  # i18n: ok (Name[pt_BR] keys in .desktop files)
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
# Wrong keyboard layout fixer: US QWERTY <-> Hebrew (SI-1452), Russian (ЙЦУКЕН) and Arabic (PC), as in
# /usr/share/X11/xkb/symbols/{il,ru,ara}. Arabic's B key types one character, the ligature ﻻ (U+FEFB).
# --------------------------------------------------------------------------

_US = "qwertyuiopasdfghjkl;'zxcvbnm,./"
_IL = "/'קראטוןםפשדגכעיחלךף,זסבהנמצתץ."
US_TO_HE = dict(zip(_US, _IL))
HE_TO_US = {he: us for us, he in US_TO_HE.items()}
_RU_KEYS, _RU = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./", "ёйцукенгшщзхъфывапролджэячсмитьбю."
_ARA_KEYS, _ARA = "`qwertyuiop[]asdfghjkl;'zxcvbnm,./", "ذضصثقفغعهخحجدشسيبلاتنمكطئءؤرﻻىةوزظ"
LAYOUTS = {   # xkb layout -> (US key -> character, character -> US key, the letters of that script, language)
    "il": (US_TO_HE, HE_TO_US, re.compile(r"[א-ת]"), "he"),
    "ru": (dict(zip(_RU_KEYS, _RU)), {c: k for k, c in zip(_RU_KEYS, _RU) if c != "."}, re.compile(r"[а-яё]",
                                                                                                  re.IGNORECASE), "ru"),
    "ara": (dict(zip(_ARA_KEYS, _ARA)), {c: k for k, c in zip(_ARA_KEYS, _ARA)}, re.compile(r"[\u0621-\u064a\ufefb]"),
            "ar"),
}
_HEBREW_LETTER = LAYOUTS["il"][2]
_LATIN_LETTER = re.compile(r"[a-z]", re.IGNORECASE)


def other_layout(environment: Path | None = None) -> str:
    """The person's own non-Latin layout (DAI_LAYOUTS in labwc's environment, as D.Ai Tune sets it)."""
    layouts = os.environ.get("DAI_LAYOUTS", "")
    path = environment or Path.home() / ".config/labwc/environment"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DAI_LAYOUTS="):
                layouts = line.split("=", 1)[1]
    except OSError:
        pass
    return next((code for code in layouts.split(",") if code in LAYOUTS), "il")


def _script(text: str) -> tuple[str | None, int]:
    """The non-Latin layout whose letters are in text (the most of them), and how many."""
    counts = {code: len(table[2].findall(text)) for code, table in LAYOUTS.items()}
    code = max(counts, key=lambda c: counts[c])
    return (code, counts[code]) if counts[code] else (None, 0)


def _from_latin(text: str, code: str, keep_others: bool) -> str:
    keys = LAYOUTS[code][0]
    return "".join(keys.get(ch.lower(), ch) if (not keep_others or _LATIN_LETTER.match(ch) or ch in "`;',./[]")
                   else ch for ch in text)


def fix_layout(text: str, layout: str | None = None) -> tuple[str, str] | None:
    """Convert text typed in the wrong layout.

    Returns (converted_text, target_language): "en", or the language of the person's other layout ("he",
    "ru" or "ar"); None when the text is not a candidate.
    """
    stripped = text.strip()
    if len(stripped) < 2:
        return None
    code, letters = _script(stripped)
    has_en = bool(_LATIN_LETTER.search(stripped))
    if has_en and not letters:
        target = layout or other_layout()
        converted = "".join(LAYOUTS[target][0].get(ch.lower(), ch) for ch in stripped)
        return (converted, LAYOUTS[target][3]) if LAYOUTS[target][2].search(converted) else None
    if letters and not has_en:
        converted = "".join(LAYOUTS[code][1].get(ch, ch) for ch in stripped)
        return (converted, "en") if _LATIN_LETTER.search(converted) else None
    return None


def convert_layout(text: str, layout: str | None = None) -> str | None:
    """Convert a whole selection to the other layout (for the global fixer).

    Unlike fix_layout() this accepts mixed text: the direction follows the
    majority script, and characters without a mapping are kept as they are.
    Returns None when there is nothing to convert.
    """
    code, letters = _script(text)
    en = len(_LATIN_LETTER.findall(text))
    if letters == en == 0:
        return None
    if en >= letters:
        converted = _from_latin(text, layout or other_layout(), keep_others=True)
    else:
        converted = "".join(LAYOUTS[code][1].get(ch, ch) for ch in text)
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
    "ai_soon": ("Diamond · Enter to ask (runs on this computer)", "Diamond · Enter לשאלה (רץ במחשב הזה)"),
    "ai_remote": ("Diamond · Enter to ask (sent to {provider}, your own key)", "Diamond · Enter לשאלה (נשלח ל־{provider}, במפתח שלך)"),
    "ai_missing": ("Diamond is not ready. Install a model: dai-models install qwen2.5-0.5b",
                   "Diamond לא מוכן. התקינו מודל: dai-models install qwen2.5-0.5b"),
    "ai_thinking": ("Thinking…", "חושב…"),
    "terminal": ("Run in terminal", "הרצה בטרמינל"),
    "background": ("Run in background", "הרצה ברקע"),
    "copy": ("Enter to copy", "Enter להעתקה"),
    "fix_he": ("Fix to Hebrew · Enter to copy", "תיקון לעברית · Enter להעתקה"),
    "fix_en": ("Fix to English · Enter to copy", "תיקון לאנגלית · Enter להעתקה"),
    "fix_ru": ("Fix to Russian · Enter to copy", "תיקון לרוסית · Enter להעתקה"),
    "fix_ar": ("Fix to Arabic · Enter to copy", "תיקון לערבית · Enter להעתקה"),
    "placeholder": ("Apps, commands, math…    ? ask    + add / build    > terminal",
                    "אפליקציות, פקודות, חישובים…    ? שאלה    + הוספה / בנייה    > טרמינל"),
    "hints": ("Enter open  ·  ↑↓ move  ·  Esc close  ·  Alt+Shift language", "הפעלה Enter  ·  ניווט ↑↓  ·  סגירה Esc  ·  שפה Alt+Shift"),
    "mic": ("Speak (local, Whisper)", "דיבור (מקומי, Whisper)"),
    "listening": ("🎙 Listening… click the microphone again to finish", "🎙 מקשיב… לחצו שוב על המיקרופון לסיום"),
    "transcribing": ("Transcribing on this computer…", "מתמלל במחשב הזה…"),
    "tune_review": ("D.Ai Tune · Enter to review and apply", "D.Ai Tune · Enter לבדיקה והחלה"),
    "tune_unknown": ("Not understood — Enter for examples", "לא הובן — Enter לדוגמאות"),
    "tune_hint": ("Configure the system in words, e.g. !block usb", "התאמת המערכת במילים, למשל !חסום דיסק און קי"),
    "forge_hint": ("Add or build anything, e.g. +install antivirus · +build an app for…",
                   "הוסיפו או בנו כל דבר, למשל +תתקין אנטי וירוס · +תבנה אפליקציה ל…"),
    "forge_setup": ("D.Ai Forge · Enter to review and set up (admin)", "D.Ai Forge · Enter לבדיקה והקמה (מנהל)"),
    "forge_remove": ("D.Ai Forge · Enter to review and remove (admin)", "D.Ai Forge · Enter לבדיקה והסרה (מנהל)"),
    "forge_build": ("Build with Diamond · runs in a sandbox · Enter", "בנייה עם Diamond · רץ בארגז חול · Enter"),
    "forge_edit": ("Update this app with Diamond · previous version kept · Enter",
                   "עדכון האפליקציה עם Diamond · הגרסה הקודמת נשמרת · Enter"),
    "forge_ai_recipe": ("No recipe yet · Diamond will write one for review · Enter",
                        "אין מתכון עדיין · Diamond יכתוב מתכון לבדיקה · Enter"),
    "build_app": ("Build app: ", "בניית אפליקציה: "),
    "update_app": ("Update app: ", "עדכון אפליקציה: "),
    "find_hint": ("Find files as you remember them: “find the pdf I downloaded last week”",
                  "מציאת קבצים כמו שזוכרים אותם: „מצא את ה־PDF שהורדתי בשבוע שעבר”"),
    "find_none": ("No matching files", "לא נמצאו קבצים מתאימים"),
    "privacy_now": ("Right now · Enter for the privacy log", "עכשיו · Enter ליומן הפרטיות"),
    "privacy_log": ("privacy log (30 days, on this computer)", "יומן פרטיות (30 יום, במחשב הזה)"),
    "move_title": ("Bring files and bookmarks from Windows", "העברת קבצים וסימניות מ־Windows"),
    "move_hint": ("D.Ai Move · shows what will be copied first · nothing is overwritten · Enter",
                  "D.Ai Move · מראה קודם מה יועתק · שום דבר לא נדרס · Enter"),
    "build_this": ("Build or add it: ", "לבנות או להוסיף: "),
    "build_this_hint": ("Not found · D.Ai Forge can build it or add it, after your review · Enter",
                        "לא נמצא · D.Ai Forge יכול לבנות או להוסיף את זה, אחרי שתאשרו · Enter"),
    "evolve_hint": ("D.Ai suggests · Enter to review · Delete to hide", "הצעה של D.Ai · Enter לבדיקה · Delete להסתרה"),
    "heal_title": ("Help & repair: what is not working?", "עזרה ותיקון: מה לא עובד?"),
    "heal_hint": ("D.Ai Heal · explains and fixes with your OK · Super+F1 · Enter",
                  "D.Ai Heal · מסביר ומתקן באישורכם · Super+F1 · Enter"),
    "store_title": ("D.Ai Store", "חנות D.Ai"),
    "store_hint": ("Find and set up software · what it sets up is shown first · no account · Enter",
                   "מוצאים ומקימים תוכנות · מה זה מקים מוצג קודם · בלי חשבון · Enter"),
    "way_hint": ("Diamond's Way: a whole computer in one file (check, plan, apply, export) · Enter",
                 "דרך היהלום: מחשב שלם בקובץ אחד (check, plan, apply, export) · Enter"),
    "fact_hint": ("From D.Ai's own guide · Enter copies it", "מהמדריך של D.Ai · Enter מעתיק"),
    "ask_more": ("Ask Diamond about it", "לשאול את Diamond על זה"),
    "explain_title": ("D.Ai Explain: what is on the screen", "D.Ai מסביר: מה שעל המסך"),
    "explain_hint": ("Diamond reads the screen and explains it in your language · Enter", "Diamond קורא את המסך ומסביר בשפה שלך · Enter"),
    "captions_title": ("D.Ai Live Captions", "כתוביות חיות D.Ai"),
    "captions_hint": ("Subtitles for whatever the computer plays · on this computer only · Enter",
                      "כתוביות למה שהמחשב משמיע · על המחשב הזה בלבד · Enter"),
    "settings_title": ("D.Ai Settings", "הגדרות D.Ai"),
    "settings_hint": ("Security, appearance, language and this computer, in one window · every change has a plan and undo · Enter",
                      "אבטחה, מראה, שפה והמחשב הזה, בחלון אחד · לכל שינוי תוכנית וביטול · Enter"),
    "focus_title": ("Focus for {n} minutes", "פוקוס ל־{n} דקות"),
    "focus_hint": ("D.Ai Focus · pop-ups hidden and a warmer light until the timer ends · Enter",
                   "D.Ai Focus · ההתראות מוסתרות והתאורה חמה עד שהטיימר נגמר · Enter"),
    "game_title": ("Game mode", "מצב משחק"),
    "game_hint": ("D.Ai Focus · full performance and no pop-ups until you end it · Enter",
                  "D.Ai Focus · ביצועים מלאים ובלי התראות עד שתסיימו · Enter"),
    "game_stop_title": ("End game mode", "סיום מצב משחק"),
    "game_stop_hint": ("D.Ai Focus · the power profile and pop-ups go back to what they were · Enter",
                       "D.Ai Focus · פרופיל החשמל וההתראות חוזרים למה שהיו · Enter"),
    "focus_stop_title": ("End the focus session", "סיום סשן הפוקוס"),
    "focus_stop_hint": ("D.Ai Focus · pop-ups and the light go back to what they were · Enter",
                        "D.Ai Focus · ההתראות והתאורה חוזרות למה שהיו · Enter"),
    "ocr_title": ("Copy text from the screen", "העתקת טקסט מהמסך"),
    "ocr_hint": ("D.Ai OCR · choose an area, its text is copied · read on this computer · Super+Shift+T",
                 "D.Ai OCR · בוחרים אזור והטקסט שבו מועתק · נקרא על המחשב הזה · Super+Shift+T"),
    "chat_title": ("Send to {name}: {text}", "שליחה אל {name}: {text}"),
    "chat_hint": ("Diamond Chat · encrypted end to end · waits on this computer until {name} is online · Enter",
                  "Diamond Chat · מוצפן מקצה לקצה · ממתין במחשב הזה עד שהמחשב של {name} יתחבר · Enter"),
    "clip_title": ("Clipboard history", "היסטוריית העתקות"),
    "clip_hint": ("D.Ai Clip · Super+V · in memory only, never passwords · Enter",
                  "D.Ai Clip · Super+V · בזיכרון בלבד, אף פעם לא סיסמאות · Enter"),
    "backup_setup": ("Set up automatic encrypted backup", "הגדרת גיבוי מוצפן אוטומטי"),
    "backup_setup_hint": ("Connect an external drive · Enter", "חברו דיסק חיצוני · Enter"),
    "backup_now": ("Back up now", "גיבוי עכשיו"),
    "backup_connected": ("Backup drive connected · Enter", "דיסק הגיבוי מחובר · Enter"),
    "backup_disconnected": ("Connect the backup drive first", "חברו קודם את דיסק הגיבוי"),
    "backup_last": ("Last backup:", "גיבוי אחרון:"),
    "backup_details": ("Enter for details", "Enter לפרטים"),
    "doctor_open": ("D.Ai Doctor · Enter for details and fixes", "D.Ai Doctor · Enter לפרטים ולתיקון"),
    "query_name": ("D.Ai Command input", "שורת הפקודות של D.Ai"),
    "results_name": ("Results", "תוצאות"),
}


def ui_language() -> str:
    return ui_lang()


def tr(key: str, lang: str | None = None) -> str:
    return pick(lang or ui_language(), *_STRINGS[key])


# --------------------------------------------------------------------------
# Query interpretation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """One result row; `kind` tells the UI how to activate it."""

    kind: str  # app | calc | layout | terminal | run | ai | history | tune | forge | file | doctor | privacy | backup | move | clip | ocr | chat | heal | evolve
    title: str
    subtitle: str = ""
    icon: str = ""
    payload: object = None


def build_actions(query: str, apps: Iterable[AppEntry], history: Iterable[str] = ()) -> list[Action]:
    """Turn the typed text into an ordered list of actions."""
    text = query.strip()
    if not text:
        return evolve_actions() + [
            Action("history", entry, tr("history"), "document-open-recent", entry)
            for entry in reversed(list(history)[-6:])
        ]

    if text.startswith("?"):
        question = text[1:].strip()
        return [
            Action(
                "ai",
                question or tr("ask"),
                ai_where_label(),
                "dialog-information",
                question,
            )
        ]
    if text.startswith("!"):
        return tune_actions(text[1:].strip())
    if text.startswith("+"):
        return forge_actions(text[1:].strip())
    if text.startswith(">"):
        command = text[1:].strip()
        return [Action("terminal", command, tr("terminal"), "utilities-terminal", command)] if command else []
    if text.startswith("$"):
        command = text[1:].strip()
        return [Action("run", command, tr("background"), "system-run", command)] if command else []

    if (HEAL_WORDS.search(text) or HEAL_WORDS.search(_heal_english(text))) and shutil.which("dai-heal"):
        return [Action("heal", tr("heal_title"), tr("heal_hint"), "help-browser", "")]
    if (chat := chat_actions(text)) is not None:
        return chat
    if (found := find_actions(text)) is not None:
        return found
    if (answers := doctor_actions(text)) is not None:
        return answers
    if (privacy := privacy_actions(text)) is not None:
        return privacy
    if (backup := backup_actions(text)) is not None:
        return backup
    if MOVE_WORDS.search(text) and shutil.which("dai-move"):
        return [Action("move", tr("move_title"), tr("move_hint"), "document-import", "")]
    if CLIP_WORDS.search(text) and shutil.which("dai-clip"):
        return [Action("clip", tr("clip_title"), tr("clip_hint"), "edit-paste", "")]
    if OCR_WORDS.search(text) and shutil.which("dai-ocr"):
        return [Action("ocr", tr("ocr_title"), tr("ocr_hint"), "edit-copy", "")]
    if (focus := focus_actions(text)) is not None:
        return focus
    if SETTINGS_WORDS.search(text.strip()) and shutil.which("dai-settings"):
        return [Action("settings", tr("settings_title"), tr("settings_hint"), "preferences-system", "")]
    if STORE_WORDS.search(text.strip()) and shutil.which("dai-store"):
        return [Action("store", tr("store_title"), tr("store_hint"), "system-software-install", "")]
    if WAY_WORDS.search(text.strip()) and shutil.which("dai-way"):
        return [Action("terminal", "dai-way examples", tr("way_hint"), "text-x-script", "dai-way examples")]
    if CAPTIONS_WORDS.search(text.strip()) and shutil.which("dai-captions"):
        return [Action("captions", tr("captions_title"), tr("captions_hint"), "accessories-text-editor", "")]
    if EXPLAIN_WORDS.search(text.strip()) and shutil.which("dai-explain"):
        return [Action("explain", tr("explain_title"), tr("explain_hint"), "help-about", "")]

    actions: list[Action] = fact_actions(text)
    if (value := calculate(text)) is not None:
        result = format_number(value)
        actions.append(Action("calc", f"= {result}", tr("copy"), "accessories-calculator", result))

    actions.extend(
        Action("app", app.name, app.comment, app.icon, app) for app in search_apps(apps, text)
    )

    if not actions and (fixed := fix_layout(text)):
        converted, lang = fixed
        actions.append(Action("layout", converted, tr(f"fix_{lang}"), "edit-paste", converted))

    first = text.split()[0]
    if shutil.which(first):
        actions.append(Action("run", text, tr("background"), "system-run", text))
        actions.append(Action("terminal", text, tr("terminal"), "utilities-terminal", text))
    elif not any(a.kind in ("app", "calc") for a in actions) and shutil.which("dai-forge-gui"):
        # Nothing on this computer does it yet: offer to build or add it (docs/EVOLVE.md §3).
        actions.append(Action("forge", tr("build_this") + text, tr("build_this_hint"), "applications-development", text))
    return actions


EVOLVE_ICONS = {"wish": "applications-development", "repeat": "appointment-soon", "filetype": "system-software-install",
                "doctor": "preferences-system", "heal": "help-browser"}


def evolve_actions(limit: int = 2) -> list[Action]:
    """What D.Ai Evolve noticed (read from its last scan; nothing is scanned here)."""
    try:
        from dai_evolve.scan import saved
    except ImportError:
        return []
    lang = ui_language()
    return [Action("evolve", f"✦ {s.title(lang)}", f"{s.why(lang)} · {tr('evolve_hint')}", EVOLVE_ICONS.get(s.kind, ""), s)
            for s in saved()[:limit]]


FILE_ICONS = {
    "pdf": "application-pdf", "image": "image-x-generic", "video": "video-x-generic", "audio": "audio-x-generic",
    "spreadsheet": "x-office-spreadsheet", "presentation": "x-office-presentation", "archive": "package-x-generic",
    "document": "x-office-document", "file": "text-x-generic",
}


def chat_actions(text: str, folder: Path | None = None) -> list[Action] | None:
    """Diamond Chat: "send Dana: see you at six", "שלח לדנה: מגיעה בשש" (only to someone already a contact)."""
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_chat.quick import find_contact, parse
    except ImportError:
        return None
    asked = parse(text)
    if asked is None:
        return None
    names, words = asked
    try:
        contact = find_contact(names, folder)
    except Exception:  # noqa: BLE001 - a broken chat store must not break the command bar
        return None
    if contact is None:
        return None
    lang = ui_language()
    short = words if len(words) <= 60 else words[:59] + "…"
    return [Action("chat", tr("chat_title", lang).format(name=contact.name, text=short),
                   tr("chat_hint", lang).format(name=contact.name), "internet-chat", (contact.public, words))]


def find_actions(text: str, home: Path | None = None) -> list[Action] | None:
    """D.Ai Find: "find the pdf I downloaded last week", "התמונות מאתמול".

    None when the text is not a find request, so other interpretations apply.
    """
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_find.query import is_find_request, parse
        from dai_find.search import human_size, search
    except ImportError:
        return None
    if not is_find_request(text):
        return None
    lang = ui_language()
    query = parse(text, lang=lang)
    if not query.specific:
        return [Action("file", tr("find_hint"), "dai-find", "system-search", None)]
    # Typing repeats the search on every key: a short memory-only cache keeps it instant.
    hits = search(query, home, limit=8, budget=0.8, ttl=30)
    if not hits:
        return [Action("file", tr("find_none"), tr("find_hint"), "system-search", None)]
    base = home or Path.home()
    rows = []
    for hit in hits:
        try:
            folder = "~/" + str(hit.path.parent.relative_to(base)) if hit.path.parent != base else "~"
        except ValueError:
            folder = str(hit.path.parent)
        detail = f"{hit.date:%d.%m.%Y %H:%M} · {human_size(hit.size)} · {folder}"
        if hit.snippet:  # a content match: what the file says around the words
            detail = f"“{hit.snippet[:80]}” · {detail}"
        rows.append(Action("file", hit.path.name, detail, FILE_ICONS.get(hit.kind, "text-x-generic"), str(hit.path)))
    return rows


_DOCTOR_CACHE: dict[str, tuple[float, list]] = {}
DOCTOR_ICONS = {"bad": "dialog-error", "warn": "dialog-warning", "ok": "emblem-ok-symbolic"}


def doctor_actions(text: str) -> list[Action] | None:
    """D.Ai Doctor: "why is my computer slow?", "מה תופס את הדיסק?".

    The bar shows the main findings; Enter opens the full diagnosis with fixes.
    """
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_doctor.diagnose import diagnose, topic_for
        from dai_doctor.facts import collect
    except ImportError:
        return None
    topic = topic_for(text)
    if topic is None:
        return None
    lang = ui_language()
    cached = _DOCTOR_CACHE.get(topic)
    if cached and time.monotonic() - cached[0] < 15:  # typing must stay instant
        findings = cached[1]
    else:
        findings = diagnose(collect(topics=(topic,), sample=0.25, budget=1.0), (topic,), lang)
        _DOCTOR_CACHE[topic] = (time.monotonic(), findings)
    shown = [f for f in findings if f.level != "ok"][:4] or findings[:1]
    subtitle = tr("doctor_open")
    return [Action("doctor", f.title, f"{f.detail} · {subtitle}" if f.detail else subtitle,
                   DOCTOR_ICONS[f.level], topic) for f in shown]


PRIVACY_QUESTION = re.compile(
    r"(?:who(?:'s| is)? (?:using|recording|listening|watching)|privacy log|(?:mic|microphone|camera|webcam) (?:log|in use)|"
    r"מי (?:משתמש|מקליט|מצלם|מאזין)|יומן (?:ה)?פרטיות|יומן (?:ה)?(?:מיקרופון|מצלמה)|(?:ה)?(?:מיקרופון|מצלמה) בשימוש)",
    re.IGNORECASE)


def privacy_actions(text: str) -> list[Action] | None:
    """D.Ai Privacy: "who is using my microphone?", "יומן פרטיות"."""
    if not PRIVACY_QUESTION.search(text):
        return None
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_privacy.log import log_path, read
        from dai_privacy.sensors import Use, current
        from dai_privacy.text import describe, t
    except ImportError:
        return None
    lang = ui_language()
    rows = [Action("privacy", describe(use, lang), tr("privacy_now"), "dialog-warning", "log") for use in current()]
    if not rows:
        rows.append(Action("privacy", t("nothing", lang), tr("privacy_now"), "security-high", "log"))
    for entry in reversed(read(log_path(), days=30)[-3:]):
        use = Use(entry.get("device", "video"), entry.get("app", "?"), entry.get("pid", 0))
        when = time.strftime("%d.%m %H:%M", time.localtime(entry.get("time", 0)))
        rows.append(Action("privacy", describe(use, lang, stopped=entry.get("event") == "stop"),
                           f"{when} · {tr('privacy_log')}", "document-open-recent", "log"))
    return rows


MOVE_WORDS = re.compile(r"(?:(?:import|move|copy|bring|transfer)\b.*\bfrom (?:my )?(?:old )?windows|from windows to|"
                        r"(?:העבר|תעביר|להעביר|ייבוא|לייבא|תייבא|העתק|תעתיק|להעתיק|העתיק)\S*.*(?:מ|מה)(?:ווינדוס|windows|מחשב הישן))",
                        re.IGNORECASE)
# Something broke, in general words (a specific "the printer doesn't work" goes to D.Ai Doctor).
HEAL_WORDS = re.compile(r"^(?:משהו|something)\b.*(?:לא עובד|נתקע|השתבש|broke|broken|not working|wrong)|"
                        r"\bcrash(?:ed|es)?\b|קרס|קריסה|תקלה|help me fix|fix my (?:computer|pc)|עזרה ותיקון|"
                        r"(?:תתקן|תקן) את המחשב", re.IGNORECASE)
HEAL_LANG = Path(__file__).parent / "lang"  # "что-то не работает", "quelque chose ne marche pas" (docs/I18N.md §10)


def _heal_english(text: str) -> str:
    from dai_i18n import keywords

    return keywords.translate(keywords.normalize(text), HEAL_LANG)


CLIP_WORDS = re.compile(r"\bclipboard\b|what (?:did i copy|i copied)|copy history|paste history|"
                        r"(?:היסטוריי?ת|יומן) (?:ה)?(?:העתקות|לוח|הדבקות)|מה העתקתי|לוח (?:ה)?(?:העתקות|גזירים)", re.IGNORECASE)
# Only about the screen or a picture: "read the text file" stays with D.Ai Find.
OCR_WORDS = re.compile(r"\bocr\b|\btext (?:from|on|in) (?:the |my |this )?(?:screen|image|picture|photo)\b|"
                       r"טקסט (?:מ|ב|על )(?:ה)?(?:מסך|תמונה)|זיהוי טקסט", re.IGNORECASE)
# D.Ai Focus (docs/BEYOND.md §5): "focus for 40 minutes", "פוקוס ל-40 דקות", "מצב ריכוז", "בלי הפרעות".
FOCUS_WORDS = re.compile(r"\bfocus(?: mode| session| time)?\b|(?:מצב )?(?:פוקוס|ריכוז)\b|בלי הפרעות", re.IGNORECASE)
FOCUS_STOP = re.compile(r"\b(?:stop|end|cancel)\b|סיים|סיימי|עצור|עצרי|הפסק|הפסיקי|בטל", re.IGNORECASE)
FOCUS_MINUTES = re.compile(r"\b(\d{1,3})\b")
GAME_WORDS = re.compile(r"\bgam(?:e|ing) mode\b|מצב משחק(?:ים)?", re.IGNORECASE)
# D.Ai Settings (docs/BEYOND.md §6): "settings", "הגדרות", "security settings".
SETTINGS_WORDS = re.compile(r"^(?:(?:open |show |system |security |d\.?ai )?settings|preferences|(?:פתח |הצג |הגדרות ה?)?הגדרות(?: מערכת| אבטחה)?)$", re.IGNORECASE)
# D.Ai Store (docs/BEYOND.md §9): "store", "app store", "חנות", "חנות אפליקציות", "software".
WAY_WORDS = re.compile(r"^(?:(?:diamond'?s )?way|dai-way|דרך היהלום|דרך)$", re.IGNORECASE)
# D.Ai Explain (docs/EXPLAIN.md): "explain this screen", "what is this error", "מה זה", "מה כתוב על המסך".
EXPLAIN_WORDS = re.compile(r"^(?:explain(?: (?:this|the|my))?(?: screen| error| window| message)?|what (?:is|does) (?:this|that)(?: (?:screen|error|message|window|mean))?\??|"
                           r"what am i (?:looking at|seeing)\??|(?:תסביר|הסבר)(?: לי)?(?: את)?(?: (?:ה)?(?:מסך|שגיאה|חלון|הודעה))?|מה זה\??|מה (?:ה)?(?:שגיאה|הודעה)(?: הזאת| הזו)?\??|מה כתוב (?:על |ב)?(?:ה)?מסך\??)$", re.IGNORECASE)
CAPTIONS_WORDS = re.compile(r"^(?:(?:open |show |start |live |d\.?ai )?(?:live )?captions|subtitles|(?:פתח |הצג |הפעל )?(?:ה)?כתוביות(?: חיות)?|תמלול חי)$", re.IGNORECASE)
STORE_WORDS = re.compile(r"^(?:(?:open |show |d\.?ai )?(?:app |apps |software )?store|software|apps|(?:פתח |הצג )?(?:ה)?חנות(?: (?:ה)?(?:אפליקציות|תוכנות))?|תוכנות)$", re.IGNORECASE)
BACKUP_WORDS = re.compile(r"\bback\s?ups?\b|\bback (?:my|the) |גיבוי|לגבות|\bגבה\b|תגבה|שחזר|לשחזר|שחזור", re.IGNORECASE)


def focus_actions(text: str) -> list[Action] | None:
    """D.Ai Focus: "focus for 40 minutes" starts a session (25 without a number); "stop focus" ends it."""
    if not shutil.which("dai-focus"):
        return None
    if GAME_WORDS.search(text):
        if FOCUS_STOP.search(text):
            return [Action("focus", tr("game_stop_title"), tr("game_stop_hint"), "process-stop", "game-stop")]
        return [Action("focus", tr("game_title"), tr("game_hint"), "applications-games", "game")]
    if not FOCUS_WORDS.search(text):
        return None
    if FOCUS_STOP.search(text):
        return [Action("focus", tr("focus_stop_title"), tr("focus_stop_hint"), "process-stop", "stop")]
    found = FOCUS_MINUTES.search(text)
    minutes = max(5, min(180, int(found.group(1)))) if found else 25
    return [Action("focus", tr("focus_title").format(n=minutes), tr("focus_hint"), "appointment-new", str(minutes))]


def backup_actions(text: str) -> list[Action] | None:
    """D.Ai Backup: "גבה את הקבצים שלי", "when was my last backup?"."""
    if not BACKUP_WORDS.search(text):
        return None
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_backup.config import load
    except ImportError:
        return None
    settings = load()
    if settings is None:
        return [Action("backup", tr("backup_setup"), tr("backup_setup_hint"), "drive-harddisk", "setup")]
    connected = (settings.repo_path / "config").is_file()
    when = time.strftime("%d.%m.%Y %H:%M", time.localtime(settings.last_backup)) if settings.last_backup else "—"
    state = tr("backup_connected") if connected else tr("backup_disconnected")
    return [Action("backup", tr("backup_now"), state, "document-save", "now"),
            Action("backup", f"{tr('backup_last')} {when}", f"{settings.repo} · {tr('backup_details')}",
                   "document-open-recent", "status")]


# A question about the system (docs/AI.md §6): the answer from D.Ai's own guide appears at once, no model needed.
QUESTION_WORDS = re.compile(r"^(?:how|what|where|which|can i|why|is there|do i)\b|\?$|^(?:איך|כיצד|מה|איפה|היכן|האם|למה|אפשר)\b", re.IGNORECASE)


def fact_actions(text: str) -> list[Action]:
    """Up to two facts from D.Ai's guide for a question about the system, then "ask Diamond about it"."""
    if not QUESTION_WORDS.search(text.strip()):
        return []
    try:
        from dai_ai.knowledge import relevant
        from dai_i18n import ui_lang
    except ImportError:
        return []
    facts = relevant(text, ui_lang(), limit=2)
    if not facts:
        return []
    rows = [Action("fact", fact, tr("fact_hint"), "help-faq", fact) for fact in facts]
    rows.append(Action("ai", text.strip(), tr("ask_more") + " · " + ai_where_label(), "dialog-information", text.strip()))
    return rows


def ai_where_label() -> str:
    """"runs on this computer", or the provider the person chose for general questions (docs/PROVIDERS.md)."""
    try:
        from dai_ai.client import where
        provider = where("general")
    except Exception:  # noqa: BLE001 - no dai_ai on the path: the local wording
        provider = "local"
    return tr("ai_soon") if provider == "local" else tr("ai_remote").format(provider=provider)


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
            f"{pick(lang, *effects[step.effect])} · {tr('tune_review')}",
            icons[step.effect],
            request,
        )
        for step in plan.steps
    ]


def forge_actions(request: str) -> list[Action]:
    """Preview a D.Ai Forge request; review and confirmation happen in dai-forge."""
    if not request:
        return [Action("forge", tr("forge_hint"), "dai-forge help", "system-software-install", "")]
    try:  # installed next to dai_command in /usr/lib/dai
        from dai_forge.apps import list_apps
        from dai_forge.intent import classify
        from dai_forge.recipes import install_requests, load_library, remove_requests
        from dai_tune.catalog import CATALOG
        from dai_tune.context import Context
        from dai_tune.planner import build_plan
    except ImportError:
        return []
    lang = ui_language()
    intent = classify(request, load_library(), (a.name for a in list_apps()))
    if intent.kind in ("recipe", "remove") and intent.recipe is not None:
        removing = intent.kind == "remove"
        requests = remove_requests(intent.recipe) if removing else install_requests(intent.recipe)
        plan = build_plan(requests, Context(lang=lang))
        rows = [Action("forge", intent.recipe.title(lang), tr("forge_remove" if removing else "forge_setup"),
                       "edit-delete" if removing else "system-software-install", request)]
        icons = {"hardens": "security-high", "weakens": "security-low", "neutral": "preferences-system"}
        rows += [
            Action("forge", CATALOG[step.action].summary(step.params, lang), "", icons[step.effect], request)
            for step in plan.steps
        ]
        return rows
    if intent.kind == "app":
        return [Action("forge", tr("build_app") + intent.text, tr("forge_build"), "applications-development", request)]
    if intent.kind == "edit":
        return [Action("forge", tr("update_app") + intent.app_name, tr("forge_edit"), "document-edit", request)]
    return [Action("forge", request, tr("forge_ai_recipe"), "dialog-question", request)]
