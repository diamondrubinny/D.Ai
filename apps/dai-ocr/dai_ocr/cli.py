# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-ocr: copy the text in an area of the screen (docs/V2.md F1).

  dai-ocr                  choose an area with the mouse; its text goes to the clipboard (Super+Shift+T)
  dai-ocr --file IMAGE     the text of a picture instead
  dai-ocr --print          print the text instead of copying it
  dai-ocr --lang he,en     read in these languages (default: the interface language and English)

Everything happens on this computer (Tesseract). The picture of the area is kept in memory only, for as
long as it is read, and never written to disk.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from dai_i18n import SUPPORTED, pick, ui_lang

# D.Ai's languages -> Tesseract's names for them (tesseract-ocr-<name> packages).
TESSERACT = {"he": "heb", "en": "eng", "ar": "ara", "ru": "rus", "es": "spa", "fr": "fra", "de": "deu", "pt": "por"}
MAX_IMAGE = 64 * 1024 * 1024  # a 4K screenshot is a few MB; anything far larger is not a screen area
PREVIEW = 120

Run = Callable[..., subprocess.CompletedProcess]


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def installed_languages(run: Run = subprocess.run) -> set[str]:
    """Tesseract's languages on this computer ("heb", "eng", ...)."""
    try:
        result = run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    lines = (result.stdout or "").splitlines()
    return {line.strip() for line in lines if re.fullmatch(r"[a-z_]{3,16}", line.strip())}


def languages(wanted: list[str], available: set[str]) -> str:
    """"heb+eng": the wanted D.Ai languages that are installed, in order, without repeats; English if none."""
    chosen: list[str] = []
    for code in wanted:
        name = TESSERACT.get(code.strip().lower()[:2])
        if name and name in available and name not in chosen:
            chosen.append(name)
    return "+".join(chosen) or "eng"


def clean(text: str) -> str:
    """Tesseract's text, tidied: no form feeds or trailing spaces, at most one empty line in a row."""
    text = text.replace("\f", "\n").replace("\r", "")
    lines = [line.rstrip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    return "\n".join(out).strip()


def preview(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= PREVIEW else one_line[:PREVIEW - 1].rstrip() + "…"


def choose_area(run: Run = subprocess.run) -> str | None:
    """The area the person drags with the mouse ("x,y wxh"), or None when they pressed Esc."""
    result = run(["slurp"], capture_output=True, text=True)
    area = (result.stdout or "").strip()
    if result.returncode != 0 or not re.fullmatch(r"-?\d+,-?\d+ \d+x\d+", area):
        return None
    return area


def capture(area: str, run: Run = subprocess.run) -> bytes:
    """A PNG of the area, in memory (grim writes it to stdout)."""
    result = run(["grim", "-g", area, "-"], capture_output=True)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("grim could not take the picture")
    return result.stdout


def read(image: bytes, langs: str, run: Run = subprocess.run) -> str:
    """The text in a picture, read on this computer."""
    if len(image) > MAX_IMAGE:
        raise RuntimeError("the picture is too large")
    result = run(["tesseract", "stdin", "stdout", "-l", langs], input=image, capture_output=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError("tesseract could not read the picture")
    return clean(result.stdout.decode("utf-8", errors="replace"))


def copy(text: str, run: Run = subprocess.run) -> bool:
    try:
        return run(["wl-copy"], input=text.encode(), timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def notify(title: str, body: str, run: Run = subprocess.run) -> None:
    try:
        run(["notify-send", "-a", "D.Ai", "-i", "edit-copy", title, body], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main(argv: list[str] | None = None, run: Run = subprocess.run) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if "--help" in args or "-h" in args:
        print(__doc__.strip())
        return 0
    if "--version" in args:
        from . import __author__, __version__
        print(f"dai-ocr {__version__} — {__author__}")
        return 0

    def option(name: str) -> str | None:
        if name in args and args.index(name) + 1 < len(args):
            return args[args.index(name) + 1]
        return None

    wanted = (option("--lang") or "").split(",") if option("--lang") else [lang, "en"]
    wanted = [code for code in wanted if code.strip().lower()[:2] in SUPPORTED] or ["en"]
    langs = languages(wanted, installed_languages(run))
    printing = "--print" in args
    try:
        if option("--file"):
            path = Path(option("--file"))
            if not path.is_file() or path.stat().st_size > MAX_IMAGE:
                print(say(lang, "No such picture: {path}", "אין תמונה כזו: {path}", path=path), file=sys.stderr)
                return 2
            image = path.read_bytes()
        else:
            area = choose_area(run)
            if area is None:
                return 1  # Esc: nothing to do
            image = capture(area, run)
        text = read(image, langs, run)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        message = say(lang, "Could not read the text: {error}", "לא הצלחתי לקרוא את הטקסט: {error}", error=exc)
        print(message, file=sys.stderr)
        if not printing:
            notify(say(lang, "Copy text from the screen", "העתקת טקסט מהמסך"), message, run)
        return 1
    if printing:
        print(text)
        return 0 if text else 1
    if not text:
        notify(say(lang, "No text found", "לא נמצא טקסט"),
               say(lang, "Try a larger area, or one with clearer text.", "נסו אזור גדול יותר, או טקסט ברור יותר."), run)
        return 1
    if not copy(text, run):
        print(text)
        return 1
    notify(say(lang, "Text copied ({count} characters)", "הטקסט הועתק ({count} תווים)", count=len(text)),
           preview(text), run)
    return 0
