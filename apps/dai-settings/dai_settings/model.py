# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The settings D.Ai Settings shows (docs/BEYOND.md §6): each one is a D.Ai Tune action.

A Setting knows how to read its current value from the system (the same files and tools the action
writes) and how to turn a chosen value into a Tune request. Nothing here changes anything: the plan is
built by dai_tune.planner and applied by dai_tune.cli.apply_plan, through the same root helper, journal and
undo as "dai-tune" itself. A setting whose tool is not on this computer reads as None and is not shown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dai_i18n import pick
from dai_tune import catalog
from dai_tune.context import Context, read_text
from dai_tune.parser import Request

Value = bool | str | None
Reader = Callable[[Context], Value]
Requester = Callable[[Value], list[Request]]

GROUPS = {
    "security": ("Security and privacy", "אבטחה ופרטיות"),
    "appearance": ("Appearance and language", "מראה ושפה"),
    "system": ("This computer", "המחשב הזה"),
}


@dataclass(frozen=True)
class Setting:
    key: str
    group: str
    kind: str                        # toggle | choice | text | button
    title: tuple[str, str]
    read: Reader
    request: Requester
    choices: tuple[tuple[str, tuple[str, str]], ...] = ()   # (value, (en, he)) for kind "choice"
    hint: tuple[str, str] = ("", "")
    placeholder: str = ""            # for kind "text"
    on_only: bool = False            # a toggle that can only be turned on (no action turns it off)

    def label(self, lang: str) -> str:
        return pick(lang, *self.title)

    def sample(self) -> Value:
        """A value this setting accepts, to ask the catalog about the action behind it."""
        if self.kind == "choice":
            return self.choices[0][0]
        if self.kind == "text":
            return self.placeholder
        return True

    def scope(self) -> str:
        """"system" when the change needs the root helper (an administrator), else "user"."""
        requests = self.request(self.sample())
        return catalog.CATALOG[requests[0].action].scope if requests else "user"

    def choice_label(self, value: str, lang: str) -> str:
        for candidate, names in self.choices:
            if candidate == value:
                return pick(lang, *names)
        return value


# -- readers ------------------------------------------------------------------

def _file_word(ctx: Context, relative: str, default: str) -> str:
    value = read_text(ctx.user_path(relative)).strip()
    return value or default


def _env_value(path: Path, key: str) -> str:
    for line in read_text(path).splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def read_lock(ctx: Context) -> str:
    seconds = catalog.lock_timeout_seconds(ctx)
    minutes = str(seconds // 60)
    return minutes if any(minutes == v for v, _ in LOCK_CHOICES) else "custom"


def read_updates(ctx: Context) -> bool:
    text = read_text(ctx.path(catalog.AUTO_UPGRADES))
    if not text:
        return True  # Debian's default from unattended-upgrades' own 20auto-upgrades is on; our file absent = untouched
    return 'Unattended-Upgrade "1"' in text


def _blocked(kind: str) -> Reader:
    return lambda ctx: ctx.path(f"/etc/modprobe.d/dai-tune-{kind}.conf").exists()


def read_ssh(ctx: Context) -> bool | None:
    if not ctx.path("/usr/sbin/sshd").exists():
        return None
    return ctx.run(["systemctl", "is-enabled", "ssh.service"], check=False).stdout.strip() == "enabled"


def read_antivirus(ctx: Context) -> str | None:
    if not ctx.path("/usr/bin/clamscan").exists():
        return None
    timer = read_text(ctx.path(catalog.AV_TIMER))
    if not timer:
        return "off"
    return "weekly" if "OnCalendar=weekly" in timer else "daily"


def read_snapshots(ctx: Context) -> bool | None:
    from dai_tune import snapshots
    if not ctx.path("/usr/bin/snapper").exists():
        return None
    return snapshots.enabled(ctx)


def read_language(ctx: Context) -> str:
    value = _env_value(ctx.user_path(catalog.LANGUAGE_ENV), "LANGUAGE")
    code = value.split(":")[0].strip() if value else ""
    return code if code in catalog.UI_LOCALES else (ctx.lang if ctx.lang in catalog.UI_LOCALES else "en")


def read_layouts(ctx: Context) -> str:
    return _env_value(ctx.user_path(catalog.LABWC_ENV), "DAI_LAYOUTS") or "us,il"


def read_timezone(ctx: Context) -> str:
    return catalog.current_timezone(ctx) or ""


def read_hostname(ctx: Context) -> str:
    return read_text(ctx.path("/etc/hostname")).strip()


def read_power(ctx: Context) -> str | None:
    if not ctx.path("/usr/bin/powerprofilesctl").exists():
        return None
    return catalog.current_power_profile(ctx) or "balanced"


# -- requests -----------------------------------------------------------------

def _one(action: str, **params: Any) -> list[Request]:
    return [Request(action, params, source="D.Ai Settings")]


def _toggle(on_action: str, off_action: str | None = None, **params: Any) -> Requester:
    def make(value: Value) -> list[Request]:
        if value:
            return _one(on_action, **params)
        return _one(off_action, **params) if off_action else []
    return make


def _enabled(action: str, **extra: Any) -> Requester:
    return lambda value: _one(action, enabled=bool(value), **extra)


def _choice(action: str, name: str, convert: Callable[[str], Any] = str) -> Requester:
    return lambda value: _one(action, **{name: convert(str(value))})


def _antivirus(value: Value) -> list[Request]:
    if value == "off":
        return _one("antivirus.schedule", enabled=False)
    return _one("antivirus.schedule", enabled=True, frequency=str(value))


def _layouts(value: Value) -> list[Request]:
    layouts = [part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()]
    return _one("keyboard.layouts", layouts=layouts)


# Texts in dicts, so the i18n extractor sees every (English, Hebrew) pair (docs/I18N.md).
TITLES = {
    "lock": ("Lock the screen", "נעילת המסך"),
    "updates": ("Automatic security updates", "עדכוני אבטחה אוטומטיים"),
    "usb": ("Block USB storage devices", "חסימת התקני אחסון USB"),
    "camera": ("Block the camera", "חסימת המצלמה"),
    "ssh": ("Remote login (SSH)", "כניסה מרחוק (SSH)"),
    "antivirus": ("Virus scans of your files", "סריקות וירוסים לקבצים שלכם"),
    "snapshots": ("A snapshot before every update", "תמונת מצב לפני כל עדכון"),
    "theme": ("Theme", "ערכת נושא"),
    "touch": ("Touch mode", "מצב מגע"),
    "sounds": ("System sounds", "צלילי המערכת"),
    "language": ("Language of D.Ai", "השפה של D.Ai"),
    "layouts": ("Keyboard languages", "שפות מקלדת"),
    "timezone": ("Time zone", "אזור זמן"),
    "hostname": ("Computer name", "שם המחשב"),
    "power": ("Power", "צריכת חשמל"),
    "clean": ("Free disk space", "פינוי מקום בדיסק"),
}
HINTS = {
    "lock": ("An organization policy may cap this.", "מדיניות ארגונית יכולה להגביל את זה."),
    "updates": ("Turning them off needs a typed confirmation.", "כיבוי דורש אישור מוקלד."),
    "ssh": ("Opens port 22 to the local network.", "פותח את פורט 22 לרשת המקומית."),
    "snapshots": ("Needs a Btrfs system disk; the way back is D.Ai Rescue.", "דורש דיסק Btrfs; הדרך חזרה היא D.Ai Rescue."),
    "language": ("From the next login.", "מהכניסה הבאה."),
    "layouts": ("Up to four, separated by commas: us,il,ru. Alt+Shift switches.",
                "עד ארבע, מופרדות בפסיקים: us,il,ru. ‏Alt+Shift מחליף."),
    "clean": ("Downloaded package files and old logs. Cannot be undone; nothing you use is lost.",
              "קבצי התקנה שהורדו ויומנים ישנים. אי אפשר לבטל; שום דבר שבשימוש לא נמחק."),
}
CHOICES = {
    "lock": {"1": ("after 1 minute", "אחרי דקה"), "5": ("after 5 minutes", "אחרי 5 דקות"),
             "10": ("after 10 minutes", "אחרי 10 דקות"), "30": ("after 30 minutes", "אחרי 30 דקות"),
             "0": ("never", "אף פעם")},
    "antivirus": {"daily": ("every day", "כל יום"), "weekly": ("every week", "כל שבוע"), "off": ("off", "כבוי")},
    "power": {"power-saver": ("battery saver", "חיסכון בסוללה"), "balanced": ("balanced", "מאוזן"),
              "performance": ("performance", "ביצועים")},
}
NO_HINT = ("", "")


def _choices(key: str) -> tuple[tuple[str, tuple[str, str]], ...]:
    return tuple(CHOICES[key].items())


def _catalog_choices(names: dict[str, tuple[str, str]]) -> tuple[tuple[str, tuple[str, str]], ...]:
    return tuple(names.items())


LOCK_CHOICES = _choices("lock")

SETTINGS: tuple[Setting, ...] = (
    Setting("lock", "security", "choice", TITLES["lock"], read_lock, _choice("session.lock", "minutes", int),
            LOCK_CHOICES, HINTS["lock"]),
    Setting("updates", "security", "toggle", TITLES["updates"], read_updates, _enabled("updates.auto"), hint=HINTS["updates"]),
    Setting("usb", "security", "toggle", TITLES["usb"], _blocked("usb_storage"),
            _toggle("device.block", "device.allow", kind="usb_storage")),
    Setting("camera", "security", "toggle", TITLES["camera"], _blocked("camera"),
            _toggle("device.block", "device.allow", kind="camera")),
    Setting("ssh", "security", "toggle", TITLES["ssh"], read_ssh, _enabled("service.ssh"), hint=HINTS["ssh"]),
    Setting("antivirus", "security", "choice", TITLES["antivirus"], read_antivirus, _antivirus, _choices("antivirus")),
    Setting("snapshots", "security", "toggle", TITLES["snapshots"], read_snapshots, _toggle("snapshots.enable"),
            on_only=True, hint=HINTS["snapshots"]),
    Setting("theme", "appearance", "choice", TITLES["theme"], lambda c: _file_word(c, catalog.THEME_FILE, "night"),
            _choice("appearance.theme", "theme"), _catalog_choices(catalog.THEME_NAMES)),
    Setting("touch", "appearance", "choice", TITLES["touch"], lambda c: _file_word(c, catalog.TOUCH_FILE, "auto"),
            _choice("appearance.touch", "mode"), _catalog_choices(catalog.TOUCH_NAMES)),
    Setting("sounds", "appearance", "choice", TITLES["sounds"], lambda c: _file_word(c, catalog.SOUNDS_FILE, "on"),
            _choice("system.sounds", "mode"), _catalog_choices(catalog.SOUND_NAMES)),
    Setting("language", "appearance", "choice", TITLES["language"], read_language, _choice("session.language", "lang"),
            _catalog_choices(catalog.LANGUAGE_NAMES), HINTS["language"]),
    Setting("layouts", "appearance", "text", TITLES["layouts"], read_layouts, _layouts, hint=HINTS["layouts"],
            placeholder="us,il"),
    Setting("timezone", "system", "text", TITLES["timezone"], read_timezone, _choice("system.timezone", "timezone"),
            placeholder="Asia/Jerusalem"),
    Setting("hostname", "system", "text", TITLES["hostname"], read_hostname, _choice("system.hostname", "hostname"),
            placeholder="my-computer"),
    Setting("power", "system", "choice", TITLES["power"], read_power, _choice("power.profile", "profile"), _choices("power")),
    Setting("clean", "system", "button", TITLES["clean"], lambda c: "", lambda value: _one("system.clean"), hint=HINTS["clean"]),
)


def by_key(key: str) -> Setting:
    for setting in SETTINGS:
        if setting.key == key:
            return setting
    raise KeyError(key)


def snapshot(ctx: Context) -> dict[str, Value]:
    """Every setting's current value; None means "not on this computer"."""
    values: dict[str, Value] = {}
    for setting in SETTINGS:
        try:
            values[setting.key] = setting.read(ctx)
        except Exception:  # noqa: BLE001 - one unreadable setting must not hide the rest
            values[setting.key] = None
    return values


def matches(setting: Setting, query: str, lang: str) -> bool:
    """A plain search over the titles in both languages and the key."""
    needle = query.strip().casefold()
    if not needle:
        return True
    haystack = " ".join([setting.key, *setting.title, *(n for _, names in setting.choices for n in names),
                         pick(lang, *GROUPS[setting.group])]).casefold()
    return needle in haystack
