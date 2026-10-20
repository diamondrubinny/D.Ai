# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Turn Hebrew or English text into action requests (offline, rule based).

The parser only produces *requests*: an action id from the catalog plus raw
parameters. The planner validates them; nothing here touches the system.
A future local-LLM parser must produce the same structure and goes through
the same validation.
"""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from dai_i18n import keywords


@dataclass(frozen=True)
class Request:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    source: str = ""  # the clause it came from, for display


@dataclass
class ParseResult:
    requests: list[Request] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

OFF = r"(?:\b(?:block|disable|turn off|switch off|deny|stop)\b|חסום|תחסום|לחסום|חסימת|כבה|תכבה|לכבות|כיבוי|נטרל|תנטרל|לנטרל|בטל|תבטל|לבטל)"
ON = r"(?:\b(?:allow|enable|unblock|turn on|switch on|start)\b|אפשר|תאפשר|לאפשר|הפעל|תפעיל|להפעיל|הפעלת|הדלק|תדליק|להדליק|שחרר|תשחרר|לשחרר)"

DEVICES = {
    "usb_storage": r"(?:usb|flash drive|thumb drive|disk on key|removable storage|דיסק און קי|דיסק-און-קי|דיסקים ניידים|זיכרון נייד|אחסון נייד|התקני אחסון|החסנה נתיקה)",
    "camera": r"(?:camera|webcam|מצלמה|המצלמה|מצלמת)",
    "bluetooth": r"(?:bluetooth|בלוטות|בלוטוס|בלו טות)",
}

# "Cancel the block" means allow, even though it contains a "block" word.
UNBLOCK = r"(?:\bremove the block\b|(?:בטל|תבטל|לבטל|הסר|תסיר|להסיר|שחרר|תשחרר)\s+(?:את\s+)?ה?חסימ)"

OPEN_PORT = r"(?:\b(?:open|allow|expose)\b|פתח|תפתח|לפתוח|פתיחת|אפשר)"
CLOSE_PORT = r"(?:\b(?:close|block|deny)\b|סגור|תסגור|לסגור|סגירת|חסום|תחסום)"
PORT = r"(?:port|פורט|פורטים|יציאה)\s*(?:(?:tcp|udp)\s*)?(\d{1,5})"
ANYWHERE = r"(?:anywhere|any network|internet|everyone|world|public|מכל מקום|מכל רשת|לאינטרנט|מהאינטרנט|לכולם|לכל העולם|ציבורי)"

UPDATES = r"(?:auto(?:matic)?[- ]?updates?|security updates|unattended|עדכונים אוטומטיים|עדכון אוטומטי|עדכוני אבטחה)"
VIRTUALIZATION = r"(?:virtual ?machines?|virtuali[sz]ation|\bkvm\b|מכונות וירטואליות|מכונה וירטואלית|וירטואליזציה)"
# D.Ai VM (docs/VM.md stage 3): "start Windows", "snapshot Windows before the update". The machine may be named
# ("the machine called office"); otherwise the only machine is meant and Tune says so when there are several.
WINDOWS_MACHINE = r"(?:\bwindows\b|\b(?:virtual )?machine\b|ווינדוס|וינדוס|windows|המכונה הווירטואלית|המכונה)"
MACHINE_NAME = r"(?:(?:called|named|בשם)\s+([A-Za-z0-9][A-Za-z0-9_.-]{0,39}))"
SNAPSHOT = r"(?:\bsnapshot\b|צילום מצב|תמונת מצב)"
START = r"(?:\b(?:start|boot|launch|run|open)\b|הפעל|תפעיל|להפעיל|הפעלת|הדלק|תדליק|פתח|תפתח)"
SHUTDOWN = r"(?:\b(?:shut ?down|stop|turn off|switch off|power off|close)\b|כבה|תכבה|לכבות|כיבוי|סגור|תסגור)"
BEFORE_UPDATE = r"(?:before (?:the |an? )?(?:windows )?updates?|לפני (?:ה)?עדכון(?:ים)?)"

# D.Ai TV (docs/TV.md stage 2): the phone as the remote; Kodi's services stay off until this is said.
TV_REMOTE = r"(?:\b(?:remote control|control (?:the |my )?tv|tv remote|kodi remote|phone as (?:a |the )?remote)\b|"\
            r"שלט מהטלפון|שליטה מרחוק בטלוויזיה|שלט לטלוויזיה|שלט רחוק|לשלוט בטלוויזיה)"

TV_NIGHT = r"(?:\bnight mode\b|\bnight\b.*\b(?:tv|television)\b|מצב לילה)"
TV_CHILDREN = r"(?:children'?s? (?:profile|mode)|kids'? (?:profile|mode)|פרופיל (?:ה)?ילדים|מצב (?:ה)?ילדים|פרופיל לילדים)"
PIN = r"(?:\b(?:pin|code)\b|קוד|פין)\s*:?\s*([0-9]{4,8})"
TV_CHANNELS = r"(?:\blive channels?\b|\bchannels? (?:list|playlist)\b|\bmy channels\b|\biptv\b|ערוצים חיים|ערוצי טלוויזיה|רשימת (?:ה)?ערוצים|ערוצים מ)"
PLAYLIST_PATH = r"((?:~|/)[^\s]+\.m3u8?)"

INSTALL = r"^(?:please\s+)?(?:install|add app|התקן|תתקין|להתקין|התקנת)\s+(.+)$"
REMOVE = r"^(?:please\s+)?(?:remove|uninstall|delete app|הסר|תסיר|להסיר|הסרת|מחק את|תמחק את)\s+(.+)$"

TIMEZONE = r"(?:time ?zone|אזור זמן|אזור הזמן|שעון של|לפי שעון)"
TIMEZONE_ALIASES = {
    "ירושלים": "Asia/Jerusalem", "ישראל": "Asia/Jerusalem", "תל אביב": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem", "israel": "Asia/Jerusalem", "tel aviv": "Asia/Jerusalem",
    "לונדון": "Europe/London", "london": "Europe/London",
    "פריז": "Europe/Paris", "paris": "Europe/Paris",
    "ברלין": "Europe/Berlin", "berlin": "Europe/Berlin",
    "מוסקבה": "Europe/Moscow", "moscow": "Europe/Moscow",
    "ניו יורק": "America/New_York", "new york": "America/New_York",
    "לוס אנג'לס": "America/Los_Angeles", "los angeles": "America/Los_Angeles",
    "טוקיו": "Asia/Tokyo", "tokyo": "Asia/Tokyo",
    "utc": "UTC", "גריניץ'": "UTC", "greenwich": "UTC",
}

HOSTNAME = r"(?:hostname|host name|computer name|device name|rename (?:the |this )?(?:computer|pc|machine)|שם מחשב|שם המחשב|שם המכשיר|שם המכונה)"

LOCK = r"(?:\block\b|\block screen\b|\bscreen ?lock\b|נעל|תנעל|לנעול|נעילת מסך|נעילה|מסך נעילה)"
MINUTES = r"(\d{1,3})\s*(?:minutes?|mins?|min|דקות|דקה|ד')"
NEVER = r"(?:never|off|disable|אף פעם|לעולם לא|בלי נעילה|כבה|תכבה|בטל)"

# D.Ai's system sounds (docs/SOUNDS.md): off, quiet or on. Checked in this order, so "quiet" wins over "on".
SOUNDS = [
    ("off", r"(?:\b(?:mute|silence|turn off|switch off|disable|no) (?:the |all )?(?:system |d\.ai )?sounds?\b|"
            r"\bsounds? off\b|השתק(?:ת|ו)? (?:את )?(?:כל )?(?:ה)?צלילי(?:ם|ם של המערכת| המערכת)?|"
            r"(?:כבה|כיבוי|תכבה) (?:את )?(?:ה)?צלילי(?:ם|ם של המערכת| המערכת)?|בלי צלילים|ללא צלילים)"),
    ("quiet", r"(?:\b(?:quiet|quieter|soft|softer|lower) (?:system )?sounds?\b|צלילים (?:שקטים|חלשים|רכים)|"
              r"(?:הנמך|הנמכת) (?:את )?(?:ה)?צלילים)"),
    ("on", r"(?:\b(?:turn on|switch on|enable|unmute) (?:the |all )?(?:system |d\.ai )?sounds?\b|\bsounds? on\b|"
           r"(?:הפעל|הפעלת|תפעיל|החזר) (?:את )?(?:ה)?צלילי(?:ם|ם של המערכת| המערכת)?)"),
]

# The D.Ai theme (docs/V2.md D1b). Not "night light" (that is wlsunset, Super+Alt+N).
THEMES = [
    ("contrast", r"(?:\bhigh[ -]contrast\b|ניגודיות גבוהה)"),
    ("day", r"(?:\b(?:light|day|bright) (?:theme|mode|design)\b|ערכת נושא בהירה|ערכת צבעים בהירה|מצב בהיר|עיצוב בהיר)"),
    ("night", r"(?:\b(?:dark|night) (?:theme|design)\b|\bdark mode\b|ערכת נושא כהה|ערכת צבעים כהה|מצב כהה|עיצוב כהה)"),
]

# The touch profile (docs/MOBILE.md A1). "off" and "auto" are tried before "on", which is the bare phrase.
TOUCH_WORD = r"(?:\btouch(?:[ -]screen)? mode\b|\btouch (?:screen )?(?:profile|layout)\b|מצב מגע|מצב מסך מגע)"
TOUCH = [
    ("auto", r"(?:\bauto(?:matic)?\b.*" + TOUCH_WORD + r"|" + TOUCH_WORD + r".*\bauto(?:matic)?\b|"
             r"אוטומטי.*" + TOUCH_WORD + r"|" + TOUCH_WORD + r".*אוטומטי)"),
    ("off", r"(?:\b(?:no|disable|turn off|switch off|stop|without)\b.*" + TOUCH_WORD + r"|" + TOUCH_WORD + r" off\b|"
            r"(?:כבה|בטל|תכבה|תבטל|ללא|בלי) (?:את )?(?:ה)?" + TOUCH_WORD + r")"),
    ("on", TOUCH_WORD),
]

ROTATE_WORD = r"(?:\brotat(?:e|ion|ing)\b|\borientation\b|סיבוב|סובב|תסובב|לסובב|הסיבוב)"
SCREEN_WORD = r"(?:\bscreen\b|\bdisplay\b|מסך|המסך|תצוגה)"
ROTATION = [
    ("auto", r"(?:\bauto(?:matic)?(?:ally)?\b|אוטומטי|אוטומטית)"),
    ("off", r"(?:\block\b|\bdon'?t\b|\bstop\b|\bnever\b|\bturn off\b|\bdisable\b|נעל|תנעל|נעילת|אל תסובב|בטל|כבה|הפסק)"),
    ("normal", r"(?:\bupright\b|\bback\b|\bstraight\b|\bnormal\b|ישר|חזרה|רגיל|בחזרה)"),
    ("180", r"(?:\b180\b|upside down|הפוך)"),
    ("270", r"(?:\b270\b)"),
    ("90", r"(?:\b90\b)"),
]

KEYBOARD = r"(?:keyboard|layouts?|מקלדת|שפות מקלדת|שפות הקלדה)"
LANGUAGES = [
    ("il", r"(?:hebrew|עברית)"), ("us", r"(?:english|אנגלית)"), ("ru", r"(?:russian|רוסית)"),
    ("ara", r"(?:arabic|ערבית)"), ("fr", r"(?:french|צרפתית)"), ("de", r"(?:german|גרמנית)"),
    ("es", r"(?:spanish|ספרדית)"), ("it", r"(?:italian|איטלקית)"), ("ua", r"(?:ukrainian|אוקראינית)"),
    ("pt", r"(?:portuguese|פורטוגזית)"),
]

# The language D.Ai itself speaks (docs/I18N.md §9), in each of the eight languages.
UI_LANGUAGE = (r"(?:\b(?:language|interface language|display language)\b|שפה|שפת הממשק|שפת המערכת|язык|"
               r"اللغة|لغة|\bidioma\b|\blangue\b|\bsprache\b|\blíngua\b)")
UI_LANGUAGES = [
    ("he", r"(?:hebrew|עברית|иврит|العبرية|hebreo|hébreu|hebräisch|hebraico)"),
    ("en", r"(?:english|אנגלית|английский|الإنجليزية|inglés|anglais|englisch|inglês)"),
    ("ar", r"(?:arabic|ערבית|арабский|العربية|árabe|arabe|arabisch)"),
    ("ru", r"(?:russian|רוסית|русский|الروسية|ruso|russe|russisch|russo)"),
    ("es", r"(?:spanish|ספרדית|испанский|الإسبانية|español|espagnol|spanisch|espanhol)"),
    ("fr", r"(?:french|צרפתית|французский|الفرنسية|francés|français|französisch|francês)"),
    ("de", r"(?:german|גרמנית|немецкий|الألمانية|alemán|allemand|deutsch|alemão)"),
    ("pt", r"(?:portuguese|פורטוגזית|португальский|البرتغالية|portugués|portugais|portugiesisch|português)"),
]

PUBLIC = r"(?:public mode|public network|cafe mode|מצב ציבורי|רשת ציבורית|מצב בית קפה|מצב נסיעה)"
PRIVACY = r"(?:privacy mode|private mode|מצב פרטיות|מצב פרטי)"

CLEAN = (r"(?:free (?:up )?(?:disk )?space|clean (?:up )?(?:the )?(?:system|disk|computer)|clear (?:the )?caches?|"
         r"פנה מקום|תפנה מקום|לפנות מקום|פינוי מקום|נקה את (?:המערכת|הדיסק|המחשב)|תנקה את (?:המערכת|הדיסק|המחשב)|ניקוי (?:המערכת|הדיסק))")
RESTART_SERVICE = r"(?:restart|הפעל מחדש(?: את)?|תפעיל מחדש(?: את)?)\s+(?:the\s+)?(?:service|השירות)\s+([a-z0-9@._-]+)"
SNAPSHOTS_ON = (r"(?:(?:enable|turn on|take|keep) (?:system )?snapshots?|snapshots? before (?:each |every |any )?(?:software )?updates?|"
                r"(?:הפעל|תפעיל|להפעיל) (?:צילום|תמונות|תמונת) מצב|(?:צילום|תמונות|תמונת) מצב (?:של המערכת )?לפני (?:כל )?עדכון)")
UNDO_UPDATE = (r"(?:undo (?:the )?(?:last|latest|recent) (?:software |system )?update|roll ?back (?:the )?(?:last |latest )?update|"
               r"revert (?:the )?(?:last|latest) update|(?:בטל|תבטל|לבטל) את העדכון האחרון|"
               r"(?:החזר|תחזיר|שחזר|תשחזר) (?:את )?(?:המחשב|המערכת) (?:ל)?(?:מצב )?(?:ש)?לפני העדכון)")
POWER = {
    "power-saver": r"(?:battery saver|power sav(?:er|ing)|save (?:the )?battery|low power mode|חיסכון ב(?:סוללה|חשמל)|לחסוך (?:ב)?סוללה|מצב חיסכון)",
    "performance": r"(?:performance mode|high performance|max(?:imum)? performance|מצב ביצועים|ביצועים מרביים|ביצועים מקסימליים)",
    "balanced": r"(?:balanced (?:power|mode)|power balanced|מצב מאוזן|צריכת חשמל מאוזנת)",
}

# Hebrew attaches "and" (ו) to the next verb: "חסום usb וכבה בלוטות'".
_HE_VERBS = (
    "כבה|תכבה|הפעל|תפעיל|חסום|תחסום|אפשר|תאפשר|פתח|תפתח|סגור|תסגור|התקן|תתקין|הסר|תסיר|"
    "נעל|תנעל|שנה|תשנה|קבע|תקבע|הדלק|תדליק|נטרל|תנטרל|בטל|תבטל|"
    # ...and to nouns that start a new request: "...ומקלדת עברית".
    "מקלדת|אזור|שם|מצב|עדכונים|עדכוני|נעילת|נעילה|פורט"
)
_SPLIT = re.compile(
    rf"\s*(?:[,;\n]|\band then\b|\band\b|\bthen\b|\balso\b|וגם|ואז)\s*|\s+ו(?=(?:{_HE_VERBS})\b)",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    text = text.replace("״", '"').replace("׳", "'").replace("’", "'").replace("–", "-")
    return re.sub(r"\s+", " ", text.strip().casefold())


LANG_DIR = Path(__file__).parent / "lang"


def _packs() -> tuple[tuple[re.Pattern, str], ...]:
    """The keyword packs (lang/<xx>.json, docs/I18N.md §10), through the shared loader in dai_i18n."""
    return keywords.load(str(LANG_DIR))


def translate(text: str) -> str:
    """"заблокируй флешки" → "block usb"; Hebrew and English pass through unchanged."""
    return keywords.translate(text, LANG_DIR)


def split_clauses(text: str) -> list[str]:
    return [c.strip(" .!?") for c in _SPLIT.split(translate(_normalize(text))) if c and c.strip(" .!?")]


def _has(pattern: str, clause: str) -> bool:
    return re.search(pattern, clause, re.IGNORECASE) is not None


def _package_names(raw: str) -> list[str]:
    raw = re.sub(r"\b(?:the|app|apps|program|package|את|התוכנה|התוכנות|תוכנה|את התוכנה|האפליקציה)\b", " ", raw)
    parts = re.split(r"[\s,]+|\bו(?=[a-z0-9])", raw)
    return [p.strip("'\"") for p in parts if p.strip("'\"")]


# --------------------------------------------------------------------------
# Clause interpretation
# --------------------------------------------------------------------------


def parse_clause(clause: str) -> list[Request]:
    c = clause

    # Presets first: they are phrases, not verb + object.
    if _has(PUBLIC, c):
        return [Request("preset.public", {}, clause)]
    if _has(PRIVACY, c):
        return [Request("preset.privacy", {}, clause)]

    if m := re.search(RESTART_SERVICE, c, re.IGNORECASE):
        return [Request("service.restart", {"unit": m.group(1)}, clause)]

    # Before anything that mentions "updates" (automatic updates).
    if _has(UNDO_UPDATE, c):
        return [Request("snapshots.undo_update", {}, clause)]
    if _has(SNAPSHOTS_ON, c):
        return [Request("snapshots.enable", {}, clause)]

    # Maintenance and power (D.Ai Doctor suggests these sentences).
    if _has(CLEAN, c):
        return [Request("system.clean", {}, clause)]
    for profile, pattern in POWER.items():
        if _has(pattern, c):
            return [Request("power.profile", {"profile": profile}, clause)]

    # "Remove the block on the camera" is about devices, not packages.
    unblock_kinds = [kind for kind, pattern in DEVICES.items() if _has(pattern, c)]
    if unblock_kinds and _has(UNBLOCK, c):
        return [Request("device.allow", {"kind": kind}, clause) for kind in unblock_kinds]

    # Packages: everything after the verb is a list of names.
    if m := re.match(INSTALL, c, re.IGNORECASE):
        return [Request("packages.install", {"names": _package_names(m.group(1))}, clause)]
    if m := re.match(REMOVE, c, re.IGNORECASE):
        return [Request("packages.remove", {"names": _package_names(m.group(1))}, clause)]

    # Firewall ports.
    if m := re.search(PORT, c, re.IGNORECASE):
        port = int(m.group(1))
        proto = "udp" if _has(r"\budp\b", c) else "tcp"
        if _has(CLOSE_PORT, c):
            return [Request("firewall.close_port", {"port": port, "proto": proto}, clause)]
        if _has(OPEN_PORT, c):
            source = "any" if _has(ANYWHERE, c) else "lan"
            return [Request("firewall.open_port", {"port": port, "proto": proto, "source": source}, clause)]

    # SSH server.
    if _has(r"\bssh\b", c):
        if _has(OFF, c):
            return [Request("service.ssh", {"enabled": False}, clause)]
        if _has(ON, c):
            return [Request("service.ssh", {"enabled": True}, clause)]

    # Automatic updates.
    if _has(UPDATES, c):
        if _has(OFF, c):
            return [Request("updates.auto", {"enabled": False}, clause)]
        return [Request("updates.auto", {"enabled": True}, clause)]

    # Virtual machines: this user's access to KVM (D.Ai VM, docs/VM.md). The user is named here, as the person
    # running Tune, so the root helper adds exactly them and nobody else.
    if _has(VIRTUALIZATION, c):
        import getpass

        return [Request("vm.kvm_access", {"user": getpass.getuser(), "enabled": not _has(OFF, c)}, clause)]

    # D.Ai VM: the machines by sentence (not "allow virtual machines", which is KVM access above).
    if _has(WINDOWS_MACHINE, c) and not _has(VIRTUALIZATION, c):
        named = re.search(MACHINE_NAME, c, re.IGNORECASE)
        name = named.group(1) if named else ""
        if _has(SNAPSHOT, c):
            label = "before-update" if _has(BEFORE_UPDATE, c) else ""
            return [Request("vm.snapshot", {"name": name, "label": label}, clause)]
        if _has(SHUTDOWN, c):
            return [Request("vm.power", {"name": name, "action": "stop"}, clause)]
        if _has(START, c):
            return [Request("vm.power", {"name": name, "action": "start"}, clause)]

    # The screen's rotation on a tablet (docs/MOBILE.md A3): "rotate the screen", "auto-rotate", "lock rotation".
    if _has(ROTATE_WORD, c) and _has(SCREEN_WORD, c):
        chosen = next((mode for mode, pattern in ROTATION if _has(pattern, c)), "90")
        return [Request("display.rotation", {"mode": chosen}, clause)]
    # D.Ai TV: night mode and the children's profile (docs/TV.md §10).
    if _has(TV_NIGHT, c):
        return [Request("tv.night_mode", {"enabled": not _has(OFF, re.sub(r"בטלוויזיה", "", c))}, clause)]
    if _has(TV_CHANNELS, c):
        found = re.search(PLAYLIST_PATH, clause, re.IGNORECASE)
        if _has(OFF, re.sub(r"בטלוויזיה", "", c)) and not found:
            return [Request("tv.channels", {"playlist": ""}, clause)]
        return [Request("tv.channels", {"playlist": found.group(1) if found else ""}, clause)] if found else []
    if _has(TV_CHILDREN, c):
        pin = re.search(PIN, c, re.IGNORECASE)
        return [Request("tv.children_profile", {"enabled": not _has(OFF, re.sub(r"בטלוויזיה", "", c)),
                                                "pin": pin.group(1) if pin else ""}, clause)]
    # D.Ai TV: remote control from the phone.
    if _has(TV_REMOTE, c):
        # "בטלוויזיה" (in the TV) contains "בטל" (cancel): the word is set aside before looking for an "off".
        return [Request("tv.remote_control", {"enabled": not _has(OFF, re.sub(r"בטלוויזיה", "", c))}, clause)]

    # Screen lock.
    if _has(LOCK, c):
        if m := re.search(MINUTES, c, re.IGNORECASE):
            return [Request("session.lock", {"minutes": int(m.group(1))}, clause)]
        if _has(NEVER, c):
            return [Request("session.lock", {"minutes": 0}, clause)]

    # D.Ai's system sounds.
    for level, pattern in SOUNDS:
        if re.search(pattern, c, re.IGNORECASE):
            return [Request("system.sounds", {"mode": level}, clause)]

    # The D.Ai theme.
    for theme, pattern in THEMES:
        if re.search(pattern, c, re.IGNORECASE):
            return [Request("appearance.theme", {"theme": theme}, clause)]

    # The touch profile.
    for mode, pattern in TOUCH:
        if re.search(pattern, c, re.IGNORECASE):
            return [Request("appearance.touch", {"mode": mode}, clause)]

    # Keyboard layouts (in the order they were mentioned).
    if _has(KEYBOARD, c):
        found = sorted(
            ((m.start(), code) for code, pattern in LANGUAGES if (m := re.search(pattern, c))),
        )
        if found:
            return [Request("keyboard.layouts", {"layouts": [code for _, code in found]}, clause)]

    # The language of D.Ai: the locale for the computer (root) and the choice for this person (next login).
    if _has(UI_LANGUAGE, c):
        found = [code for code, pattern in UI_LANGUAGES if re.search(pattern, c)]
        if len(found) == 1:
            return [Request("system.locale", {"lang": found[0]}, clause),
                    Request("session.language", {"lang": found[0]}, clause)]

    # Time zone.
    if _has(TIMEZONE, c):
        for alias, tz in sorted(TIMEZONE_ALIASES.items(), key=lambda kv: -len(kv[0])):
            if alias in c:
                return [Request("system.timezone", {"timezone": tz}, clause)]
        if m := re.search(r"\b([a-z]+/[a-z_]+(?:/[a-z_]+)?|utc)\b", c):
            tz = "/".join(part[:1].upper() + part[1:] for part in m.group(1).split("/"))
            return [Request("system.timezone", {"timezone": "UTC" if tz.lower() == "utc" else tz}, clause)]

    # Computer name: the last token that looks like a host name.
    if _has(HOSTNAME, c):
        tokens = re.findall(r"[a-z0-9][a-z0-9-]*", c)
        stop = {"hostname", "host", "name", "computer", "device", "to", "set", "change", "rename", "the", "this", "pc", "machine"}
        candidates = [t for t in tokens if t not in stop]
        if candidates:
            return [Request("system.hostname", {"hostname": candidates[-1]}, clause)]

    # Devices: block / allow every device the clause mentions.
    kinds = [kind for kind, pattern in DEVICES.items() if _has(pattern, c)]
    if kinds:
        if _has(UNBLOCK, c) or (_has(ON, c) and not _has(OFF, c)):
            return [Request("device.allow", {"kind": kind}, clause) for kind in kinds]
        if _has(OFF, c):
            return [Request("device.block", {"kind": kind}, clause) for kind in kinds]

    return []


# Topics a clause can mention, and the actions that cover each topic. If a
# clause mentions a topic none of its requests cover, part of the sentence
# was not understood and the clause is rejected instead of half-applied.
_TOPICS = {
    "device": ("|".join(DEVICES.values()), ("device.",)),
    "updates": (UPDATES, ("updates.",)),
    "keyboard": (KEYBOARD, ("keyboard.",)),
    "language": (UI_LANGUAGE, ("session.language", "keyboard.", "system.locale")),
    "timezone": (TIMEZONE, ("system.timezone",)),
    "hostname": (HOSTNAME, ("system.hostname",)),
    "lock": (LOCK, ("session.lock",)),
    "port": (PORT, ("firewall.",)),
    "vm": (VIRTUALIZATION, ("vm.",)),
    "tv": (f"(?:{TV_REMOTE}|{TV_NIGHT}|{TV_CHILDREN}|{TV_CHANNELS})", ("tv.",)),
    "machine": (r"(?:ווינדוס|וינדוס|\bwindows\b)", ("vm.",)),
    "touch": (TOUCH_WORD, ("appearance.touch",)),
    "rotation": (ROTATE_WORD + r"(?=.*" + SCREEN_WORD + r")", ("display.rotation",)),
}


def _uncovered_topics(clause: str, requests: list[Request]) -> list[str]:
    if any(r.action.startswith(("preset.", "packages.")) for r in requests):
        return []  # presets and package lists legitimately contain other words
    missing = []
    for topic, (pattern, prefixes) in _TOPICS.items():
        if _has(pattern, clause) and not any(r.action.startswith(prefixes) for r in requests):
            missing.append(topic)
    # "open port 22 for ssh" is about the port; "enable ssh" brings the port itself.
    if "port" in missing and any(r.action == "service.ssh" for r in requests):
        missing.remove("port")
    # "lock the screen rotation" locks the rotation, not the session.
    if "lock" in missing and any(r.action == "display.rotation" for r in requests):
        missing.remove("lock")
    return missing


def _only_device(clause: str) -> str | None:
    """The device a verbless clause names ("the camera"), or None when it says more than that."""
    found = [kind for kind, pattern in DEVICES.items() if re.search(pattern, clause, re.IGNORECASE)]
    if len(found) != 1:
        return None
    rest = re.sub(DEVICES[found[0]], "", clause, flags=re.IGNORECASE)
    return found[0] if re.fullmatch(r"\s*(?:the|its|ה|את ה?)?\s*", rest) else None


def parse(text: str) -> ParseResult:
    result = ParseResult()
    for clause in split_clauses(text):
        requests = parse_clause(clause)
        previous = result.requests[-1] if result.requests else None
        if (
            not requests
            and previous is not None
            and previous.action in ("packages.install", "packages.remove")
            and re.fullmatch(r"[a-z0-9][a-z0-9+.\s-]*", clause)
        ):
            # "install vlc and gimp": the clause after "and" continues the list.
            names = previous.params["names"] + _package_names(clause)
            result.requests[-1] = Request(previous.action, {"names": names}, previous.source + ", " + clause)
        elif (
            not requests
            and previous is not None
            and previous.action in ("device.block", "device.allow")
            and (kind := _only_device(clause)) is not None
        ):
            # "turn off bluetooth and camera": the camera gets the same verb.
            result.requests.append(Request(previous.action, {"kind": kind}, clause))
        elif requests and not _uncovered_topics(clause, requests):
            result.requests.extend(requests)
        else:
            result.unknown.append(clause)
    return result


EXAMPLES = {
    "he": [
        "חסום דיסק און קי",
        "חסום מצלמה וכבה בלוטות'",
        "פתח פורט 8080",
        "סגור פורט 8080",
        "הפעל עדכונים אוטומטיים",
        "אפשר מכונות וירטואליות",
        "הפעל ssh",
        "התקן vlc gimp",
        "נעל מסך אחרי 5 דקות",
        "מקלדת עברית אנגלית רוסית",
        "שפה רוסית",
        "אזור זמן ירושלים",
        "שנה שם מחשב ל office-pc",
        "מצב ציבורי",
        "מצב פרטיות",
        "מצב מגע",
        "שלט מהטלפון",
        "מצב לילה",
        "פרופיל ילדים עם קוד 2468",
        "ערוצים מהרשימה שלי ~/channels.m3u",
        "סובב את המסך",
        "סיבוב מסך אוטומטי",
        "הפעל את ווינדוס",
        "צילום מצב של ווינדוס לפני העדכון",
        "פנה מקום בדיסק",
        "מצב חיסכון בסוללה",
        "הפעל צילום מצב לפני כל עדכון",
        "בטל את העדכון האחרון",
    ],
    "en": [
        "block usb storage",
        "block the camera and turn off bluetooth",
        "open port 8080",
        "close port 8080",
        "enable automatic updates",
        "allow virtual machines",
        "enable ssh",
        "install vlc gimp",
        "lock the screen after 5 minutes",
        "keyboard english hebrew",
        "language russian",
        "time zone london",
        "rename computer to office-pc",
        "public mode",
        "privacy mode",
        "touch mode",
        "remote control from the phone",
        "night mode",
        "children's profile with pin 2468",
        "live channels from ~/channels.m3u",
        "rotate the screen",
        "lock the screen rotation",
        "start windows",
        "snapshot windows before the update",
        "free up disk space",
        "battery saver mode",
        "snapshots before updates",
        "undo the last update",
    ],
}
