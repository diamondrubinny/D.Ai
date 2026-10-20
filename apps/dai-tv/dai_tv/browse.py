# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Ruby in TV mode (docs/TV.md stage 3b): Firefox ESR in a kiosk window of its own, big enough for a sofa.

A separate profile (~/.config/dai/ruby-tv) keeps the TV's browsing apart from the desktop's: its own user.js
(scale 1.75, autoplay allowed so a player starts, nothing restored from a crash, everything cleared at exit),
Ruby's system policies still apply (no telemetry, tracking protection, HTTPS only). One instance at a time: its
PID is kept so "back to the TV" (`dai-tv browse --close`) can end it from a labwc key or from Kodi's remote.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Callable

FIREFOX = "/usr/lib/firefox-esr/firefox-esr"
PROFILE_DIR = ".config/dai/ruby-tv"
PID_FILE = "ruby-tv.pid"
USER_JS = """// D.Ai TV: Ruby on the sofa (docs/TV.md stage 3b). Firefox's system policies (Ruby) still apply.
user_pref("layout.css.devPixelsPerPx", "1.75");
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.page", 0);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("browser.link.open_newwindow", 1);
user_pref("privacy.sanitize.sanitizeOnShutdown", true);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", false);
"""
Spawn = Callable[[list[str]], int]


def profile_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / PROFILE_DIR


def prepare_profile(home: Path | None = None) -> Path:
    """The TV profile with D.Ai's prefs (rewritten every time, so a change in D.Ai takes at the next start)."""
    folder = profile_dir(home)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / "user.js").write_text(USER_JS, encoding="utf-8")
    return folder


def argv(url: str, home: Path | None = None, firefox: str = FIREFOX) -> list[str]:
    return [firefox, "--new-instance", "--kiosk", "--profile", str(profile_dir(home)), url]


def allowed(url: str) -> bool:
    """Only web addresses and D.Ai's own start page: never a command, never an arbitrary file."""
    return url.startswith(("https://", "http://")) or url == "file:///usr/share/dai/ruby/start.html"


def _pid_path(home: Path | None) -> Path:
    return profile_dir(home) / PID_FILE


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running(home: Path | None = None) -> int | None:
    try:
        pid = int(_pid_path(home).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 1 and _alive(pid) else None


def open_url(url: str, home: Path | None = None, spawn: Spawn | None = None, firefox: str = FIREFOX) -> int:
    """Start (or replace) the TV browser on the address; returns its PID."""
    if not allowed(url):
        raise ValueError("a web address (https://…) is needed")
    close(home)
    prepare_profile(home)

    def default_spawn(cmd: list[str]) -> int:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True).pid

    pid = (spawn or default_spawn)(argv(url, home, firefox))
    _pid_path(home).write_text(f"{pid}\n", encoding="utf-8")
    return pid


def close(home: Path | None = None, kill: Callable[[int, int], None] = os.kill) -> bool:
    """Back to the TV: end the browser instance this module started (nothing else is ever signalled)."""
    pid = running(home)
    _pid_path(home).unlink(missing_ok=True)
    if pid is None:
        return False
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True
