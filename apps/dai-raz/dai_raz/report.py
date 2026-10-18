# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Raz stage 4 (docs/RAZ.md §4, §5, §14): trends, the weekly report, improvement items and "report the problem".

Everything here reads what Raz already keeps (run-*.json, 90 days, 0600) and
writes only improve.json next to it. Nothing is sent anywhere: the problem
report is text the person reads, and copies only if they want to.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from dai_i18n import pick, text

DAY = 86400.0
WEEK = 7 * DAY
REPEATS = 3            # a check that failed in 3 runs within 14 days becomes an improvement item
CONFIRM = 3            # and the item "worked" after 3 passing runs in a row
BOOT = re.compile(r"=\s*(?:(\d+)min\s*)?([\d.]+)s\s*$", re.M)


# Metrics: measured on each check, kept with the run

def boot_seconds(run: Callable = subprocess.run) -> float | None:
    """How long the last start took (systemd-analyze), or None when it cannot be measured."""
    try:
        result = run(["systemd-analyze", "time"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    match = BOOT.search(result.stdout) if result.returncode == 0 else None
    if not match:
        return None
    return round(int(match.group(1) or 0) * 60 + float(match.group(2)), 1)


def crashes_this_week(run: Callable = subprocess.run, now: float | None = None) -> int | None:
    """Programs that crashed in the last 7 days (systemd-coredump, the same source D.Ai Heal reads)."""
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((now or time.time()) - WEEK))
    try:
        result = run(["coredumpctl", "list", "--no-pager", "--no-legend", "--since", since], capture_output=True,
                     text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):  # 1: nothing found
        return None
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def metrics(run: Callable = subprocess.run) -> dict:
    return {"boot_seconds": boot_seconds(run), "crashes_week": crashes_this_week(run)}


# Reading the kept runs

def load_runs(directory: Path, since: float = 0.0) -> list[dict]:
    runs = []
    for path in sorted(directory.glob("run-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("time", 0) >= since:
            runs.append(data)
    return sorted(runs, key=lambda r: r.get("time", 0))


def _failed(run: dict) -> set[str]:
    return {r["id"] for r in run.get("results", []) if r.get("status") == "failed"}


def _average(values: list) -> float | None:
    numbers = [v for v in values if isinstance(v, (int, float))]
    return round(sum(numbers) / len(numbers), 1) if numbers else None


# The weekly report

@dataclass
class Week:
    runs: int = 0
    failures: dict[str, int] = field(default_factory=dict)   # check id → runs it failed in
    boot: float | None = None
    boot_before: float | None = None
    crashes: int | None = None


def week(runs: list[dict], now: float) -> Week:
    this = [r for r in runs if r.get("time", 0) >= now - WEEK]
    before = [r for r in runs if now - 2 * WEEK <= r.get("time", 0) < now - WEEK]
    report = Week(runs=len(this))
    for run in this:
        for check in _failed(run):
            report.failures[check] = report.failures.get(check, 0) + 1
    report.boot = _average([r.get("metrics", {}).get("boot_seconds") for r in this])
    report.boot_before = _average([r.get("metrics", {}).get("boot_seconds") for r in before])
    crashes = [r.get("metrics", {}).get("crashes_week") for r in this]
    report.crashes = next((c for c in reversed(crashes) if isinstance(c, int)), None)
    return report


def week_text(report: Week, lang: str, titles: dict[str, tuple[str, str]]) -> str:
    """In plain words: "This week everything worked. Starting is 2 seconds faster than last week." """
    if report.runs == 0:
        return pick(lang, "Raz did not check this week yet.", "‏Raz עוד לא בדק השבוע.")
    lines = []
    if not report.failures:
        lines.append(pick(lang, "This week everything worked.", "השבוע הכל עבד."))
    else:
        for check, times in sorted(report.failures.items(), key=lambda item: -item[1]):
            title = pick(lang, *titles[check]) if check in titles else check
            lines.append(text(lang, "Not working {times} of {runs} times: {title}.",
                              "לא עבד {times} מתוך {runs} פעמים: {title}.", times=times, runs=report.runs,
                              title=title))
    if report.boot is not None and report.boot_before is not None:
        change = round(report.boot_before - report.boot, 1)
        if change >= 0.5:
            lines.append(text(lang, "Starting is {seconds} seconds faster than last week.",
                              "האתחול מהיר ב־{seconds} שניות מאשר בשבוע שעבר.", seconds=change))
        elif change <= -0.5:
            lines.append(text(lang, "Starting is {seconds} seconds slower than last week.",
                              "האתחול איטי ב־{seconds} שניות מאשר בשבוע שעבר.", seconds=-change))
        else:
            lines.append(text(lang, "Starting takes about {seconds} seconds, as last week.",
                              "האתחול לוקח בערך {seconds} שניות, כמו בשבוע שעבר.", seconds=report.boot))
    elif report.boot is not None:
        lines.append(text(lang, "Starting takes about {seconds} seconds.", "האתחול לוקח בערך {seconds} שניות.",
                          seconds=report.boot))
    if report.crashes:
        lines.append(text(lang, "Programs crashed {count} times; D.Ai Heal has the details (Super+F1).",
                          "תוכנות קרסו {count} פעמים. הפרטים ב־D.Ai Heal (‏Super+F1).", count=report.crashes))
    return " ".join(lines)


# Improvement items (PDCA)

# Plan: a likely cause and a fix from a closed list, per check. Never run by Raz itself.
FIXES = {   # Tune sentences must parse in D.Ai Tune (a test checks it); "heal" opens D.Ai Heal
    "commands": ("tune", "undo the last update"),
    "panel": ("advice", ""),
    "services": ("heal", ""),
    "files": ("heal", ""),
    "packages": ("tune", "undo the last update"),
    "firewall": ("heal", ""),
    "updates": ("tune", "enable automatic updates"),
    "posture": ("heal", ""),
    "languages": ("tune", "undo the last update"),
}


@dataclass
class Item:
    check: str
    opened: float
    failures: int
    fix_kind: str
    fix: str
    state: str = "open"       # open → worked, or open → stale (it stopped failing before anything was done)
    passes: int = 0           # passing runs in a row since the item was opened
    closed: float = 0.0


def improve(runs: list[dict], items: list[Item], now: float) -> list[Item]:
    """Plan (a repeated failure becomes an item), check (passing runs in a row), act (worked)."""
    by_check = {item.check: item for item in items if item.state == "open"}
    settled = {}  # a check whose item worked counts only failures after that
    for item in items:
        if item.state != "open":
            settled[item.check] = max(settled.get(item.check, 0.0), item.closed)
    recent = [r for r in runs if r.get("time", 0) >= now - 2 * WEEK]
    counts: dict[str, int] = {}
    for run in recent:
        for check in _failed(run):
            if run.get("time", 0) > settled.get(check, 0.0):
                counts[check] = counts.get(check, 0) + 1
    for check, count in counts.items():
        if count >= REPEATS and check not in by_check:
            kind, fix = FIXES.get(check, ("heal", ""))
            item = Item(check, now, count, kind, fix)
            items.append(item)
            by_check[check] = item
    for item in by_check.values():
        after = [r for r in runs if r.get("time", 0) > item.opened]
        streak = 0
        for run in after:
            streak = 0 if item.check in _failed(run) else streak + 1
        item.passes = streak
        if streak >= CONFIRM:
            item.state, item.closed = "worked", now
    return items


def load_items(directory: Path) -> list[Item]:
    try:
        return [Item(**raw) for raw in json.loads((directory / "improve.json").read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return []


def save_items(directory: Path, items: list[Item]) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "improve.json"
    fd = os.open(path.with_suffix(".tmp"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump([asdict(i) for i in items], handle, ensure_ascii=False, indent=1)
    os.replace(path.with_suffix(".tmp"), path)


def items_text(items: list[Item], lang: str, titles: dict[str, tuple[str, str]]) -> str:
    if not items:
        return pick(lang, "Nothing to improve: no check failed again and again.",
                    "אין מה לשפר: שום בדיקה לא נכשלה שוב ושוב.")
    lines = []
    for item in items:
        title = pick(lang, *titles[item.check]) if item.check in titles else item.check
        if item.state == "worked":
            lines.append(text(lang, "✓ Worked: {title} (passed {passes} times in a row).",
                              "✓ עבד: {title} (עבר {passes} פעמים ברצף).", title=title, passes=item.passes))
            continue
        if item.fix_kind == "tune":
            how = text(lang, "Try in D.Ai Command: !{fix}", "נסו בשורת הפקודה: !{fix}", fix=item.fix)
        elif item.fix_kind == "heal":
            how = pick(lang, "Open D.Ai Heal (Super+F1).", "פתחו את D.Ai Heal (‏Super+F1).")
        else:
            how = pick(lang, "Log out and in again.", "צאו מהחשבון והיכנסו שוב.")
        lines.append(text(lang, "• Failed {failures} times: {title}. {how}", "• נכשל {failures} פעמים: {title}. {how}",
                          failures=item.failures, title=title, how=how))
    return "\n".join(lines)


# "Report the problem": text the person reads and copies, filtered first

def _ipv6(match: re.Match) -> str:
    word = match.group(0)
    return "<ip>" if "::" in word or word.count(":") >= 5 else word  # not a time like 10:00:00


def _redactions() -> list[tuple[re.Pattern, object]]:
    # Addresses first, then names: "dana@example.org" is an email, not a user name.
    found: list[tuple[re.Pattern, object]] = [
        (re.compile(r"\b[^@\s<>]+@[^@\s<>]+\.[a-z]{2,}\b", re.I), "<email>"),
        (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
        (re.compile(r"(?<![\w:])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])", re.I), _ipv6),
        # a token: long, letters and digits, no spaces (Clip's detection adds the known formats when installed)
        (re.compile(r"(?<![\w/~.-])(?=[A-Za-z0-9_+=-]*\d)(?=[A-Za-z0-9_+=-]*[A-Za-z])[A-Za-z0-9_+=-]{24,}(?![\w/.])"),
         "<hidden>"),  # not a file name or a path part: those are kept
    ]
    home = str(Path.home())
    if home not in ("", "/"):
        found.append((re.compile(re.escape(home)), "~"))
    found.append((re.compile(r"(?<![\w~<])/(?:home|root|media|mnt|run/media)/[^\s,:;'\"]+"), "<path>"))
    # Whole words only: the live user is "dai", and "dai-raz" or "dai.service" must stay readable.
    alone = r"(?<![\w.-]){}(?![\w.-])"
    for name in {os.environ.get("USER", ""), os.environ.get("LOGNAME", "")}:
        if len(name) >= 2:
            found.append((re.compile(alone.format(re.escape(name))), "<user>"))
    host = socket.gethostname()
    if len(host) >= 2:
        found.append((re.compile(alone.format(re.escape(host))), "<computer>"))
    return found


def scrub(line: str) -> str:
    for pattern, replacement in _redactions():
        line = pattern.sub(replacement, line)
    try:
        from dai_clip.secrets import classify
    except ImportError:  # Clip is not installed: the rules above still apply
        return line

    def hidden(word: str) -> bool:
        verdict = classify(word)
        return verdict is not None and verdict.kind != "one-time-code"
    return " ".join("<hidden>" if hidden(word) else word for word in line.split(" "))


def _os_release(path: Path = Path("/etc/os-release")) -> str:
    try:
        values = dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    except OSError:
        return "unknown"
    return values.get("PRETTY_NAME", "unknown").strip('"')


def problem_report(results: list[dict], version: str, titles: dict[str, tuple[str, str]]) -> str:
    """English, so anyone can read the issue; only what failed, filtered for names, places and secrets."""
    lines = ["D.Ai OS problem report (made by Raz; nothing was sent)",
             f"- D.Ai Raz: {version}", f"- System: {scrub(_os_release())}",
             f"- Kernel: {platform.release()}", ""]
    failed = [r for r in results if r.get("status") == "failed"]
    if not failed:
        lines.append("All checks passed.")
    for result in failed:
        title = titles.get(result["id"], (result["id"], ""))[0]
        lines.append(f"✗ {title} [{result['id']}]: {scrub(str(result.get('detail', '')))}")
        lines += [f"    · {scrub(str(item))}" for item in result.get("items", [])[:10]]
    return "\n".join(lines)
