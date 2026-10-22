# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""This computer as a .dway file (docs/WAY.md §3): the settings D.Ai Settings reads, as exact actions, and
the recipes whose packages and apps are all present. No secrets: no passwords, no Wi-Fi, no keys."""

from __future__ import annotations

import subprocess
from datetime import date
from typing import Callable

from dai_forge.recipes import Library, load_library
from dai_i18n import pick
from dai_settings.model import SETTINGS
from dai_tune.context import Context

from .language import format_exact

Run = Callable[..., subprocess.CompletedProcess]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def installed_packages(run: Run = _run) -> set[str]:
    try:
        result = run(["dpkg-query", "-W", "-f", "${Package} ${db:Status-Status}\n"])
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.split()[0] for line in (result.stdout or "").splitlines() if line.endswith(" installed")}


def installed_flatpaks(run: Run = _run) -> set[str]:
    try:
        result = run(["flatpak", "list", "--app", "--columns=application"])
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def installed_recipes(library: Library, packages: set[str], flatpaks: set[str]) -> list[str]:
    """Recipes whose every package and Flathub app is on this computer (a recipe with neither is skipped)."""
    found = []
    for recipe in sorted(library.recipes.values(), key=lambda r: r.id):
        wanted_packages, wanted_apps = [], []
        for step in recipe.steps:
            params = step.get("params", {})
            if step.get("action") == "packages.install":
                wanted_packages += params.get("names", [])
            if step.get("action") == "flatpak.install":
                wanted_apps += params.get("apps", [])
        if not (wanted_packages or wanted_apps):
            continue
        if all(p in packages for p in wanted_packages) and all(a in flatpaks for a in wanted_apps):
            found.append(recipe.id)
    return found


def export_text(ctx: Context, lang: str, library: Library | None = None, run: Run = _run,
                hostname: str = "this computer", today: date | None = None) -> str:
    library = library or load_library()
    lines = [
        "# " + pick(lang, "Diamond's Way: ", "דרך היהלום: ") + f"{hostname}, {(today or date.today()).isoformat()}",
        "# " + pick(lang, "Written by dai-way export. No passwords, no Wi-Fi, no keys.",
                    "נכתב על ידי dai-way export. בלי סיסמאות, בלי Wi-Fi, בלי מפתחות."),
        f"diamond: {hostname}",
        "",
        pick(lang, "apps:", "אפליקציות:"),
    ]
    recipes = installed_recipes(library, installed_packages(run), installed_flatpaks(run))
    lines += [f"  {recipe}" for recipe in recipes] or ["  # " + pick(lang, "no recipes installed", "אין מתכונים מותקנים")]
    lines += ["", pick(lang, "exact:", "מדויק:")]
    for setting in SETTINGS:
        if setting.kind == "button":
            continue
        try:
            value = setting.read(ctx)
        except Exception:  # noqa: BLE001 - one unreadable setting must not stop the export
            value = None
        if value is None or value == "":
            continue
        requests = setting.request(value)
        if not requests:
            continue
        lines.append(f"  # {setting.label(lang)}")
        lines += [f"  {format_exact(request.action, request.params)}" for request in requests]
    return "\n".join(lines) + "\n"
