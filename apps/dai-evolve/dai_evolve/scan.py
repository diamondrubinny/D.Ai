# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""From local signals to ready suggestions (docs/EVOLVE.md §3). Rules only, no AI.

Every suggestion carries one action that the existing tools already know how
to do safely: a "+" request for D.Ai Forge, a sentence for D.Ai Tune, or the
D.Ai Heal chat. Suggestions come from fixed templates; file names never go
into a prompt, only their type.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from dai_i18n import pick

from . import store

MIN_REPEATS = 3
MIN_WISHES = 2
SCAN_DAYS = 30
MAX_FILES = 3000
# Not offered as automations: needs root, is interactive, or may carry a secret.
NOT_AUTOMATABLE = re.compile(
    r"^(sudo|su|pkexec|doas|nano|vi|vim|nvim|emacs|less|more|man|top|htop|btop|ssh|mosh|passwd|watch|tmux|screen)\b"
    r"|(passw|token|secret|bearer|api[_-]?key|authorization|--password|-p\S)", re.IGNORECASE)
# File types that need a program, and the D.Ai Forge recipe that provides one.
TYPE_RECIPES = {
    ".epub": "ebook-reader", ".mobi": "ebook-reader", ".fb2": "ebook-reader", ".cbz": "ebook-reader",
    ".mkv": "video-player", ".avi": "video-player", ".webm": "video-player", ".mov": "video-player",
    ".flac": "video-player", ".opus": "video-player",
    ".psd": "image-editor", ".xcf": "image-editor", ".tga": "image-editor",
    ".rar": "archives", ".7z": "archives",
}
RECIPE_NAMES = {
    "ebook-reader": ("an e-book reader", "קורא ספרים דיגיטליים"),
    "video-player": ("a video and music player", "נגן וידאו ומוזיקה"),
    "image-editor": ("an image editor", "עורך תמונות"),
    "archives": ("a program that opens archives", "תוכנה שפותחת קבצים דחוסים"),
}


@dataclass
class Suggestion:
    key: str
    kind: str           # wish | repeat | filetype | doctor | heal
    title_en: str
    title_he: str
    why_en: str
    why_he: str
    action: str         # forge | tune | heal
    payload: str        # the "+" request, the Tune sentence, or "" for heal

    def title(self, lang: str) -> str:
        return pick(lang, self.title_en, self.title_he)

    def why(self, lang: str) -> str:
        return pick(lang, self.why_en, self.why_he)


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:12]


def _norm(text: str) -> str:
    return re.sub(r"[^\w֐-׿ ]+", "", text.casefold()).strip()


def from_wishes(wishes: list[dict], model_ready: bool) -> list[Suggestion]:
    out = []
    groups: dict[str, list[dict]] = {}
    for wish in wishes:
        groups.setdefault(_norm(wish["text"]), []).append(wish)
    for norm, items in groups.items():
        text = items[-1]["text"]
        retry = model_ready and any(w.get("reason") == "no-model" for w in items)
        if len(items) >= MIN_WISHES or retry:
            out.append(Suggestion(
                _key("wish", norm), "wish",
                f"Build it for you: “{text}”", f"לבנות לך את זה: „{text}”",
                "You asked for this and the AI model is installed now; try again?" if retry else
                f"You looked for this {len(items)} times and found nothing.",
                "ביקשת את זה, ועכשיו מודל ה־AI מותקן. לנסות שוב?" if retry else
                f"חיפשת את זה {len(items)} פעמים ולא נמצא כלום.",
                "forge", text))
    return out


def from_commands(counts: dict) -> list[Suggestion]:
    out = []
    for entry, row in counts.items():
        if not isinstance(row, dict) or int(row.get("count", 0)) < MIN_REPEATS:
            continue
        command = entry[1:].strip()[:80]
        if NOT_AUTOMATABLE.search(command):
            continue
        out.append(Suggestion(
            _key("repeat", entry), "repeat",
            "Let D.Ai do it every morning", "ש־D.Ai יעשה את זה כל בוקר",
            f"You ran “{command}” {row['count']} times. An automation can do it and tell you the result.",
            f"הרצת „{command}” {row['count']} פעמים. אוטומציה יכולה לעשות את זה ולהודיע לך מה יצא.",
            "forge", f"every morning at 9 do what the command `{command}` does and notify me of the result"))
    return out


def file_types(home: Path, now: float, folders: Iterable[str] = ("Downloads", "Documents", "Desktop")) -> Counter:
    """Extensions of recent files in the user's main folders (names are not kept)."""
    seen: Counter = Counter()
    budget = MAX_FILES
    for folder in folders:
        base = home / folder
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")][:50]
            if root.count(os.sep) - str(base).count(os.sep) >= 2:
                dirs[:] = []
            for name in files:
                budget -= 1
                if budget < 0:
                    return seen
                path = Path(root, name)
                try:
                    if now - path.stat().st_mtime > SCAN_DAYS * 86400:
                        continue
                except OSError:
                    continue
                if (ext := path.suffix.lower()) in TYPE_RECIPES:
                    seen[ext] += 1
    return seen


def has_handler(ext: str, run: Callable[[list[str]], subprocess.CompletedProcess]) -> bool:
    mime = mimetypes.guess_type(f"x{ext}")[0] or {".epub": "application/epub+zip", ".mkv": "video/x-matroska",
                                                     ".xcf": "image/x-xcf", ".psd": "image/vnd.adobe.photoshop",
                                                     ".7z": "application/x-7z-compressed", ".rar": "application/vnd.rar",
                                                     ".fb2": "application/x-fictionbook+xml", ".mobi": "application/x-mobipocket-ebook",
                                                     ".cbz": "application/vnd.comicbook+zip", ".opus": "audio/ogg"}.get(ext, "")
    if not mime:
        return True  # unknown type: do not guess
    result = run(["xdg-mime", "query", "default", mime])
    if result.returncode == 127:
        return True  # xdg-mime is missing: do not guess
    return result.returncode == 0 and bool(result.stdout.strip())


def from_files(home: Path, now: float, run: Callable[[list[str]], subprocess.CompletedProcess],
               recipes: set[str]) -> list[Suggestion]:
    needed: dict[str, int] = {}
    for ext, count in file_types(home, now).items():
        recipe = TYPE_RECIPES[ext]
        if recipe in recipes and not has_handler(ext, run):
            needed[recipe] = needed.get(recipe, 0) + count
    out = []
    for recipe, count in needed.items():
        en, he = RECIPE_NAMES[recipe]
        out.append(Suggestion(
            _key("filetype", recipe), "filetype",
            f"Install {en}", f"להתקין {he}",
            f"You have {count} recent file(s) that no installed program opens.",
            f"יש לך {count} קבצים מהזמן האחרון שאף תוכנה מותקנת לא פותחת.",
            "forge", f"install {recipe}"))
    return out


def from_doctor(findings: list) -> list[Suggestion]:
    out = []
    for finding in findings:
        if getattr(finding, "level", "") not in ("warn", "bad"):
            continue
        for fix in getattr(finding, "fixes", []):
            if fix.kind == "tune":
                out.append(Suggestion(_key("doctor", finding.key), "doctor", fix.label, fix.label,
                                      finding.title, finding.title, "tune", fix.payload))
                break
    return out


def from_heal(problems: list) -> list[Suggestion]:
    if not problems:
        return []
    return [Suggestion(_key("heal", *sorted(p.key for p in problems)), "heal",
                       "Something is not working: get help", "משהו לא עובד: לקבל עזרה",
                       f"{len(problems)} problem(s) noticed (crashes or failed services).",
                       f"נמצאו {len(problems)} בעיות (קריסות או שירותים שנכשלו).", "heal", "")]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(argv, 127, "", "")


def _installed_recipes() -> set[str]:
    try:
        from dai_forge.recipes import load_library
    except ImportError:
        return set()
    return set(load_library().recipes)


def scan(home: Path | None = None, now: float | None = None, run=_run, doctor=None, heal=None,
         model_ready: bool | None = None, recipes: set[str] | None = None) -> list[Suggestion]:
    """All current suggestions, minus dismissed ones. Saved for D.Ai Command (which never scans itself)."""
    if store.is_off():
        return []
    home = home or Path.home()
    now = now or time.time()
    if model_ready is None:
        try:
            from dai_tune.ai import model_installed

            model_ready = model_installed()
        except ImportError:
            model_ready = False
    found = from_wishes(store.wishes_list(now), model_ready)
    found += from_commands(store.read_json("commands.json", {}) or {})
    found += from_files(home, now, run, recipes if recipes is not None else _installed_recipes())
    found += from_doctor(doctor() if doctor else _doctor())
    found += from_heal(heal() if heal else _heal())
    dismissed = set(store.read_json("dismissed.json", []) or [])
    result = [s for s in found if s.key not in dismissed]
    store.write_json("suggestions.json", [asdict(s) for s in result])
    mirror(len(result))
    return result


def _doctor() -> list:
    try:
        from dai_doctor.diagnose import diagnose
        from dai_doctor.facts import collect
    except ImportError:
        return []
    topics = ("disk", "battery")
    return diagnose(collect(topics=topics, sample=0.2, budget=1.5), topics, "en")


def _heal() -> list:
    try:
        from dai_heal.problems import collect
    except ImportError:
        return []
    return collect()


def saved() -> list[Suggestion]:
    """What the last scan found (cheap: for D.Ai Command)."""
    rows = store.read_json("suggestions.json", [])
    dismissed = set(store.read_json("dismissed.json", []) or [])
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            suggestion = Suggestion(**row)
        except TypeError:
            continue
        if suggestion.key not in dismissed and suggestion.action in ("forge", "tune", "heal"):
            out.append(suggestion)
    return out


def done(suggestion: Suggestion) -> None:
    """The user acted on it: a wish is forgotten (asking again starts over), a repeat is not offered again."""
    if suggestion.kind == "wish":
        store.forget_wishes(lambda text: _norm(text) == _norm(suggestion.payload))
    elif suggestion.kind == "repeat":
        dismiss(suggestion.key)
    rows = [s for s in saved() if s.key != suggestion.key]
    store.write_json("suggestions.json", [asdict(s) for s in rows])
    mirror(len(rows))


def dismiss(key: str) -> None:
    keys = set(store.read_json("dismissed.json", []) or []) | {key}
    store.write_json("dismissed.json", sorted(keys))
    mirror(len(saved()))


def mirror(ideas: int) -> None:
    """A small diamond on the Start button when there is an idea (docs/TASKBAR.md §2.1)."""
    try:
        from dai_status import update
    except ImportError:
        return
    update("ideas", ideas)
