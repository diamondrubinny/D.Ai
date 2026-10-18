# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Facts → findings in plain Hebrew or English, each with a safe fix.

Fixes are never applied here. They are either a sentence for D.Ai Tune
(planned, shown, authorized and undoable there), a user-level cleanup that
dai-doctor performs after confirmation, or advice.
"""

from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass, field

from dai_i18n import text

from .facts import Facts

# Processes that are part of the desktop itself: never suggested for closing.
SESSION = {"labwc", "lxqt-panel", "lxqt-session", "pcmanfm-qt", "Xwayland", "pipewire", "wireplumber",
           "systemd", "sddm", "dbus-daemon", "kworker", "dai-doctor"}


@dataclass
class Fix:
    kind: str      # tune | clean | advice
    label: str
    payload: str = ""   # tune sentence, or cleanup name


@dataclass
class Finding:
    key: str
    level: str     # ok | warn | bad
    title: str
    detail: str = ""
    fixes: list[Fix] = field(default_factory=list)


def size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _t(lang: str, en: str, he: str, **kwargs: object) -> str:
    return text(lang, en, he, **kwargs)


def _apps(facts: Facts, key: str, limit: int = 3) -> list:
    procs = [p for p in facts.processes if p.name not in SESSION and not p.name.startswith("kworker")]
    return sorted(procs, key=lambda p: getattr(p, key), reverse=True)[:limit]


def slow(facts: Facts, lang: str) -> list[Finding]:
    findings = []
    # Memory: the most common reason a desktop feels slow.
    if facts.mem_total:
        free = facts.mem_available / facts.mem_total
        hogs = [p for p in _apps(facts, "rss") if p.rss > 200 * 2**20]
        names = ", ".join(f"{p.name} ({size(p.rss)})" for p in hogs)
        if free < 0.20:
            level = "bad" if free < 0.10 else "warn"
            detail = _t(lang, "Only {mem_available} of {mem_total} is free.",
                        "רק {mem_available} מתוך {mem_total} פנויים.",
                        mem_available=size(facts.mem_available), mem_total=size(facts.mem_total))
            if names:
                detail += " " + _t(lang, "Using the most: {names}.", "הכי הרבה משתמשים: {names}.", names=names)
            fixes = [Fix("advice", _t(lang, "Close apps or browser tabs you are not using",
                                      "סגרו אפליקציות או לשוניות דפדפן שלא בשימוש"))]
            findings.append(Finding("memory", level, _t(lang, "Memory is almost full", "הזיכרון כמעט מלא"), detail, fixes))
        else:
            findings.append(Finding("memory", "ok", _t(lang, "Enough free memory", "יש מספיק זיכרון פנוי"),
                                    _t(lang, "{mem_available} free", "{mem_available} פנויים",
                                       mem_available=size(facts.mem_available))))
    if facts.swap_total and facts.mem_total and facts.mem_available / facts.mem_total < 0.2:
        used = facts.swap_total - facts.swap_free
        if used > facts.swap_total * 0.5:
            findings.append(Finding("swap", "warn", _t(lang, "The computer is using swap heavily",
                                                      "המחשב משתמש הרבה בזיכרון החלפה (swap)"),
                                    _t(lang, "{used} in swap: things slow down when it is used.",
                                       "{used} ב־swap: כשמשתמשים בו הכל מאט.", used=size(used))))
    # Processor.
    busy = [p for p in _apps(facts, "cpu") if p.cpu >= 25]
    pressure = facts.load1 / max(facts.cores, 1)
    if busy or pressure > 1.0:
        names = ", ".join(f"{p.name} ({p.cpu:.0f}%)" for p in busy) or "—"
        level = "bad" if pressure > 1.5 else "warn"
        findings.append(Finding("cpu", level, _t(lang, "The processor is busy", "המעבד עמוס"),
                                _t(lang, "Load {load1:.1f} on {cores} cores. Busiest: {names}.",
                                   "עומס {load1:.1f} על {cores} ליבות. הכי עמוסים: {names}.",
                                   load1=facts.load1, cores=facts.cores, names=names),
                                [Fix("advice", _t(lang, "Close or wait for the busiest app", "סגרו את האפליקציה העמוסה או חכו שתסיים"))]))
    else:
        findings.append(Finding("cpu", "ok", _t(lang, "The processor is not overloaded", "המעבד לא עמוס"),
                                _t(lang, "Load {load1:.1f} on {cores} cores",
                                   "עומס {load1:.1f} על {cores} ליבות",
                                   load1=facts.load1, cores=facts.cores)))
    if facts.failed_units:
        units = ", ".join(facts.failed_units[:5])
        findings.append(Finding("services", "warn", _t(lang, "Some system services failed", "שירותי מערכת נכשלו"),
                                units, [Fix("advice", _t(lang, "Details: journalctl -u {failed_units}",
                                                         "פרטים: journalctl -u {failed_units}",
                                                         failed_units=facts.failed_units[0]))]))
    if facts.uptime_days >= 14:
        findings.append(Finding("uptime", "warn", _t(lang, "Not restarted for a long time", "המחשב לא הופעל מחדש הרבה זמן"),
                                _t(lang, "{uptime_days:.0f} days. A restart applies installed updates and frees memory.",
                                   "{uptime_days:.0f} ימים. הפעלה מחדש מחילה עדכונים שהותקנו ומפנה זיכרון.",
                                   uptime_days=facts.uptime_days),
                                [Fix("advice", _t(lang, "Restart when convenient", "הפעילו מחדש כשנוח"))]))
    return findings


def disk(facts: Facts, lang: str) -> list[Finding]:
    findings = []
    for mount, (total, free) in facts.disks.items():
        if not total:
            continue
        ratio = free / total
        # A big disk with 11% free still has plenty of room: look at both.
        if ratio < 0.08 or free < 5 * 2**30:
            level = "bad" if ratio < 0.03 or free < 2 * 2**30 else "warn"
            findings.append(Finding(f"disk:{mount}", level, _t(lang, "Little free space on {mount}", "מעט מקום פנוי ב־{mount}",
                                                               mount=mount),
                                    _t(lang, "{free} free of {total}.", "{free} פנויים מתוך {total}.",
                                       free=size(free), total=size(total))))
        else:
            findings.append(Finding(f"disk:{mount}", "ok", _t(lang, "Enough free space on {mount}", "יש מספיק מקום ב־{mount}",
                                                              mount=mount),
                                    _t(lang, "{free} free of {total}", "{free} פנויים מתוך {total}",
                                       free=size(free), total=size(total))))
    system_caches = facts.caches.get("apt", 0) + max(0, facts.caches.get("journal", 0) - 200 * 2**20)
    if system_caches > 100 * 2**20:
        findings.append(Finding("system-caches", "warn",
                                _t(lang, "{system_caches} can be freed in the system", "אפשר לפנות {system_caches} במערכת",
                                   system_caches=size(system_caches)),
                                _t(lang, "Downloaded package files and old system logs.", "קבצי התקנה שהורדו ויומני מערכת ישנים."),
                                [Fix("tune", _t(lang, "Free this space (administrator)", "לפנות את המקום (מנהל)"),
                                     "free up disk space")]))
    user_caches = facts.caches.get("trash", 0) + facts.caches.get("thumbnails", 0)
    if user_caches > 50 * 2**20:
        findings.append(Finding("user-caches", "warn",
                                _t(lang, "{user_caches} in the trash and picture previews",
                                   "{user_caches} בסל המחזור ובתצוגות מקדימות של תמונות",
                                   user_caches=size(user_caches)),
                                _t(lang, "Trash {trash}, previews {previews}.",
                                   "סל מחזור {trash}, תצוגות מקדימות {previews}.",
                                   trash=size(facts.caches.get("trash", 0)), previews=size(facts.caches.get("thumbnails", 0))),
                                [Fix("clean", _t(lang, "Empty the trash and clear previews", "לרוקן את סל המחזור ולנקות תצוגות מקדימות"),
                                     "user")]))
    if facts.folders:
        listing = ", ".join(f"{name} {size(n)}" for name, n in facts.folders[:5])
        findings.append(Finding("folders", "ok", _t(lang, "Biggest folders in your home", "התיקיות הגדולות בבית שלכם"), listing))
    return findings


def power(facts: Facts, lang: str) -> list[Finding]:
    bat = facts.battery
    if bat is None:
        return []
    findings = []
    if bat.health is not None and bat.health < 70:
        findings.append(Finding("battery-health", "warn", _t(lang, "The battery is worn", "הסוללה שחוקה"),
                                _t(lang, "It holds {health}% of its original capacity.",
                                   "היא מחזיקה {health}% מהקיבולת המקורית שלה.", health=bat.health),
                                [Fix("advice", _t(lang, "Consider replacing the battery", "שקלו להחליף סוללה"))]))
    if bat.status == "Discharging" and bat.capacity <= 30 and facts.power_profile != "power-saver":
        findings.append(Finding("battery-low", "warn", _t(lang, "Battery at {capacity}%", "הסוללה ב־{capacity}%",
                                                          capacity=bat.capacity),
                                _t(lang, "Battery saver mode makes it last longer.", "מצב חיסכון בסוללה יאריך אותה."),
                                [Fix("tune", _t(lang, "Turn on battery saver", "להפעיל חיסכון בסוללה"), "battery saver mode")]))
    if not findings:
        health = _t(lang, ", {health}% health", ", בריאות {health}%", health=bat.health) if bat.health is not None else ""
        findings.append(Finding("battery", "ok", _t(lang, "Battery is fine", "הסוללה תקינה"),
                                _t(lang, "{capacity}% charged{health}", "{capacity}% טעונה{health}",
                                   capacity=bat.capacity, health=health)))
    return findings


KIND_NAMES = {
    "wifi": ("Wi-Fi", "Wi-Fi"), "ethernet": ("Wired network", "רשת קווית"), "graphics": ("Graphics", "גרפיקה"),
    "audio": ("Sound", "קול"), "camera": ("Camera", "מצלמה"), "bluetooth": ("Bluetooth", "Bluetooth"),
    "printer": ("Printer", "מדפסת"),
}


def hardware(facts: Facts, lang: str) -> list[Finding]:
    findings = []
    for device in facts.devices:
        label = _t(lang, *KIND_NAMES[device.kind])
        if device.kind == "printer" and not facts.printing:
            findings.append(Finding(f"hw:{device.kind}", "warn", f"{label}: {device.name}",
                                    _t(lang, "Connected, but printing is not installed yet.", "מחוברת, אבל שירות ההדפסה עוד לא מותקן."),
                                    [Fix("forge", _t(lang, "Install printing (D.Ai Forge)", "התקנת הדפסה (D.Ai Forge)"), "install printer")]))
        elif device.driver:
            findings.append(Finding(f"hw:{device.kind}", "ok", f"{label}: {_t(lang, 'works', 'במצב תקין')}",
                                    f"{device.name} ({device.driver})"))
        else:
            findings.append(Finding(f"hw:{device.kind}", "bad", f"{label}: {_t(lang, 'no driver', 'אין דרייבר')}",
                                    _t(lang, "{name} has no driver loaded, so it will probably not work.",
                                       "ל־{name} לא נטען דרייבר, ולכן כנראה לא יעבוד.", name=device.name),
                                    [Fix("advice", _t(lang, "Search: linux driver {name}",
                                                      "חפשו: linux driver {name}", name=device.name))]))
    has_wifi_chip = any(d.kind == "wifi" and d.driver for d in facts.devices)
    if facts.wifi_blocked:
        findings.append(Finding("hw:wifi-off", "warn", _t(lang, "Wi-Fi is switched off", "ה־Wi-Fi כבוי"),
                                _t(lang, "Airplane mode or a Wi-Fi key/switch is on.", "מצב טיסה, או מקש/מתג Wi-Fi כבוי."),
                                [Fix("advice", _t(lang, "Turn Wi-Fi on in the network menu or with the Wi-Fi key",
                                                  "הפעילו Wi-Fi מתפריט הרשת או עם מקש ה־Wi-Fi"))]))
    elif has_wifi_chip and not facts.wifi_interfaces:
        findings.append(Finding("hw:wifi-firmware", "warn", _t(lang, "Wi-Fi chip found but not ready", "נמצא כרטיס Wi-Fi אבל הוא לא מוכן"),
                                _t(lang, "Usually missing firmware for this chip.", "בדרך כלל חסר firmware לשבב הזה.")))
    if not facts.devices:
        findings.append(Finding("hw:none", "ok", _t(lang, "No hardware details available here", "אין כאן פרטי חומרה")))
    return findings


def update(facts: Facts, lang: str) -> list[Finding]:
    """"It broke after the update": what changed, and the way back when there is one."""
    when = ""
    if facts.last_update:
        date, count = facts.last_update
        when = _t(lang, "The last update ({date}) changed {count} package(s). ",
                  "העדכון האחרון ({date}) שינה {count} חבילות. ", date=date, count=count)
    if facts.snapshots:
        return [Finding("update", "warn", _t(lang, "You can undo the last update", "אפשר לבטל את העדכון האחרון"),
                        when + _t(lang, "A snapshot of the system was taken before it. Your personal files are not touched.",
                                  "לפניו נשמרה תמונת מצב של המערכת. הקבצים האישיים לא משתנים."),
                        [Fix("tune", _t(lang, "Undo the last update", "לבטל את העדכון האחרון"), "undo the last update")])]
    if facts.root_fs == "btrfs":
        return [Finding("update", "warn", _t(lang, "Snapshots before updates are off", "צילום מצב לפני עדכונים כבוי"),
                        when + _t(lang, "This update cannot be undone automatically, but the next ones can.",
                                  "את העדכון הזה אי אפשר לבטל אוטומטית, אבל את הבאים כן."),
                        [Fix("tune", _t(lang, "Take snapshots before updates", "להפעיל צילום מצב לפני עדכונים"),
                             "snapshots before updates"),
                         Fix("advice", _t(lang, "See what changed: /var/log/apt/history.log",
                                          "מה השתנה: /var/log/apt/history.log"))])]
    return [Finding("update", "warn", _t(lang, "Updates cannot be undone on this disk", "על הדיסק הזה אי אפשר לבטל עדכונים"),
                    when + _t(lang, "Snapshots need a Btrfs system disk; this one is {unknown}.",
                              "תמונות מצב דורשות דיסק מערכת מסוג Btrfs, וזה {root_fs}.",
                              unknown=facts.root_fs or 'unknown', root_fs=facts.root_fs or 'לא ידוע'),
                    [Fix("advice", _t(lang, "See what changed: /var/log/apt/history.log, and report it on GitHub",
                                      "מה השתנה: /var/log/apt/history.log, ודווחו ב־GitHub"))])]


TOPICS = {"slow": slow, "disk": disk, "battery": power, "hardware": hardware, "update": update}

QUESTIONS = {
    # First: "the printer doesn't work since the update" is about the update.
    "update": (r"(?:(?:since|after) (?:the |an |last |latest )?update|update (?:broke|ruined)|broke after|"
               r"(?:מאז|אחרי|לאחר) (?:ה)?עדכון|העדכון (?:שבר|הרס|קלקל|דפק))"),
    "slow": r"(?:\bslow\b|\bsluggish\b|\blag(?:gy|ging)?\b|\bfreez(?:e|es|ing)\b|\bhang(?:s|ing)?\b|"
            r"איטי|איטית|נתקע|תקוע|מאט|כבד|לאט)",
    "disk": r"(?:disk space|storage|\bdisk\b.*\bfull\b|running out of space|what(?:'s| is) taking|free space|"
            r"מקום (?:ב)?דיסק|הדיסק מלא|מקום פנוי|מה תופס|נגמר (?:לי )?המקום|אחסון)",
    "battery": r"(?:\bbattery\b|סוללה|הסוללה)",
    "hardware": (r"(?:hardware|\bdrivers?\b|wi-?fi|wireless|printer|bluetooth|\bsound\b|\baudio\b|webcam|camera|"
                 r"will (?:my|the|this) \w+ work|חומרה|דרייבר|מדפסת|וויי ?פיי|wifi|אלחוטי|בלוטות|רמקול|מצלמה|"
                 r"(?:יעבוד|תעבוד|יעבדו|לא עובד|לא עובדת))"),
}


# A question or a complaint about the computer, not just a word like "slow".
CUES = (r"(?:\bwhy\b|\bwhat\b|\bhow\b|\bcomputer\b|\bpc\b|\blaptop\b|\bsystem\b|\bmy\b|\?|"
        r"למה|מדוע|מה |איך|המחשב|מחשב|המערכת|הלפטופ|שלי|עדכון|\bupdate\b)")


LANG_DIR = Path(__file__).parent / "lang"  # keyword packs for the six other languages (docs/I18N.md §10)


def _topic(lowered: str) -> str | None:
    if not re.search(CUES, lowered):
        return None
    for topic, pattern in QUESTIONS.items():
        if re.search(pattern, lowered):
            return topic
    return None


def topic_for(text: str) -> str | None:
    """The question a sentence asks, if it is one D.Ai Doctor answers ("почему компьютер тормозит?" too)."""
    from dai_i18n import keywords

    return _topic(text.casefold()) or _topic(keywords.translate(keywords.normalize(text), LANG_DIR))


def diagnose(facts: Facts, topics: tuple[str, ...], lang: str = "en") -> list[Finding]:
    findings = [f for topic in topics for f in TOPICS[topic](facts, lang)]
    order = {"bad": 0, "warn": 1, "ok": 2}
    return sorted(findings, key=lambda f: order[f.level])
