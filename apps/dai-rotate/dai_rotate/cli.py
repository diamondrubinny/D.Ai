# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-rotate: the screen follows the tablet (docs/MOBILE.md A3).

  dai-rotate run              follow the accelerometer (started with the session; quiet when there is none)
  dai-rotate status           the choice, the sensor, the screens and their transform
  dai-rotate set MODE         auto | off (rotation lock) | normal | 90 | 180 | 270; a fixed one is applied now
  dai-rotate apply            apply the choice now (a fixed orientation; nothing for auto or off)
  dai-rotate --version | --help
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dai_i18n import pick, ui_lang

from . import __author__, __version__, rotate


def say(lang: str, en: str, he: str, **kwargs: object) -> str:
    return pick(lang, en, he).format(**kwargs)


def main(argv: list[str] | None = None, home: Path | None = None, runner=rotate.run, which=shutil.which) -> int:
    args = list(sys.argv if argv is None else argv)[1:]
    lang = ui_lang()
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if args[0] == "--version":
        print(f"dai-rotate {__version__} — {__author__}")
        return 0
    verb = args[0]
    if verb == "status":
        choice = rotate.mode(home)
        print(say(lang, "Choice: {mode}", "בחירה: {mode}", mode=choice))
        print(say(lang, "Sensor: {state}", "חיישן: {state}", state=say(lang, "monitor-sensor is installed", "monitor-sensor מותקן")
                  if which("monitor-sensor") else say(lang, "no iio-sensor-proxy (no accelerometer follows)", "אין iio-sensor-proxy (אין חיישן שאפשר לעקוב אחריו)")))
        for name in rotate.outputs(runner):
            print(say(lang, "Screen {name}: transform {transform}", "מסך {name}: סיבוב {transform}",
                      name=name, transform=rotate.current_transform(runner, name) or "?"))
        return 0
    if verb == "set":
        value = args[1] if len(args) > 1 else ""
        if value not in rotate.MODES:
            print(say(lang, "dai-rotate set auto|off|normal|90|180|270", "dai-rotate set auto|off|normal|90|180|270"), file=sys.stderr)
            return 2
        rotate.set_mode(value, home)
        if value in rotate.TRANSFORMS:
            ok = rotate.apply(value, runner)
            print(say(lang, "The screen is turned to {t}.", "המסך סובב ל-{t}.", t=value) if ok
                  else say(lang, "Saved; no screen could be turned now (is this a Wayland session?).",
                           "נשמר; אי אפשר היה לסובב מסך עכשיו (האם זה סשן Wayland?)."))
        elif value == "off":
            print(say(lang, "Rotation lock: the screen stays as it is.", "נעילת סיבוב: המסך נשאר כמו שהוא."))
        else:
            print(say(lang, "The screen follows the tablet.", "המסך עוקב אחרי הטאבלט."))
        return 0
    if verb == "apply":
        choice = rotate.mode(home)
        if choice in rotate.TRANSFORMS:
            return 0 if rotate.apply(choice, runner) else 1
        return 0
    if verb == "run":
        if not which("monitor-sensor"):
            print(say(lang, "No iio-sensor-proxy here; nothing to follow.", "אין כאן iio-sensor-proxy; אין אחרי מה לעקוב."))
            return 0
        try:
            rotate.follow(rotate.sensor_lines(), runner, home)
        except KeyboardInterrupt:
            pass
        return 0
    print(say(lang, "Unknown command: {verb}. dai-rotate --help", "פקודה לא מוכרת: {verb}. dai-rotate --help", verb=verb), file=sys.stderr)
    return 2
