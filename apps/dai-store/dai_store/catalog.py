# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What D.Ai Store offers (docs/BEYOND.md §9): D.Ai Forge's recipes by category, and Flathub's apps.

A recipe is a tested list of D.Ai Tune actions (packages, a service, a port, a Flathub app); a Flathub app
becomes two actions (the remote, then the app). Nothing here installs anything: the Store builds the plan with
dai_tune.planner and applies it through dai_tune.cli.apply_plan, like D.Ai Forge and D.Ai Settings.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Iterable

from dai_i18n import pick
from dai_forge.recipes import Library, Recipe, install_requests, load_library
from dai_tune.catalog import CATALOG
from dai_tune.parser import Request

CATEGORIES = {
    "talk": ("Talk and meet", "לדבר ולהיפגש"),
    "work": ("Work and documents", "עבודה ומסמכים"),
    "media": ("Music, video and pictures", "מוזיקה, וידאו ותמונות"),
    "games": ("Games and Windows programs", "משחקים ותוכנות Windows"),
    "safety": ("Safety and network", "בטיחות ורשת"),
    "devices": ("Printers and devices", "מדפסות והתקנים"),
    "languages": ("Languages", "שפות"),
    "more": ("More", "עוד"),
}
RECIPE_CATEGORY = {
    "signal": "talk", "telegram": "talk", "discord": "talk", "zoom": "talk", "thunderbird": "talk",
    "onlyoffice": "work", "vscode": "work", "nextcloud": "work", "syncthing": "work", "archives": "work",
    "ebook-reader": "work",
    "spotify": "media", "video-player": "media", "image-editor": "media",
    "steam": "games", "windows-apps": "games",
    "antivirus": "safety", "openvpn": "safety", "cisco-vpn": "safety", "wireguard": "safety", "containers": "safety",
    "printer": "devices", "scanner": "devices",
    "flathub": "more",
}
APP_ID = re.compile(r"^[A-Za-z][\w-]*(\.[A-Za-z][\w-]*)+$")
Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Item:
    id: str
    source: str                       # "recipe" | "flathub"
    category: str
    title: dict[str, str]
    description: dict[str, str]
    requests: tuple[Request, ...]
    keywords: tuple[str, ...] = ()
    recipe: Recipe | None = field(default=None, compare=False)

    def name(self, lang: str) -> str:
        return self.title.get(lang) or self.title.get("en") or self.id

    def about(self, lang: str) -> str:
        return self.description.get(lang) or self.description.get("en") or ""

    def category_name(self, lang: str) -> str:
        return pick(lang, *CATEGORIES[self.category])

    def sets_up(self, lang: str) -> list[str]:
        """What the plan would do, in the catalog's own words, one line per action."""
        lines = []
        for request in self.requests:
            spec = CATALOG.get(request.action)
            try:
                lines.append(spec.summary(request.params, lang) if spec else request.action)
            except Exception:  # noqa: BLE001 - a recipe's raw params may lack what the summary formats
                lines.append(request.action)
        return lines


def category_of(recipe_id: str) -> str:
    if recipe_id.startswith("language-"):
        return "languages"
    return RECIPE_CATEGORY.get(recipe_id, "more")


def recipe_items(library: Library | None = None) -> list[Item]:
    library = library or load_library()
    items = []
    for recipe in sorted(library.recipes.values(), key=lambda r: r.id):
        words = tuple(w for lang_words in recipe.match.values() for w in lang_words)
        items.append(Item(recipe.id, "recipe", category_of(recipe.id), dict(recipe.name), dict(recipe.description),
                          tuple(install_requests(recipe)), words, recipe))
    return items


def flathub_item(app_id: str, name: str, description: str) -> Item:
    requests = (Request("flatpak.remote", {"name": "flathub"}, "D.Ai Store"),
                Request("flatpak.install", {"apps": [app_id], "remote": "flathub"}, "D.Ai Store"))
    return Item(app_id, "flathub", "more", {"en": name}, {"en": description}, requests, (app_id.lower(),))


def flathub_search(term: str, run: Run = subprocess.run) -> list[Item]:
    """flatpak's own search over the app index it already has (flatpak refreshes that index itself, from
    Flathub, when it is a day old); empty when flatpak or the remote is not there."""
    term = term.strip()
    if len(term) < 2:
        return []
    try:
        result = run(["flatpak", "search", "--columns=application,name,description", term],
                     capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    items = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2 or not APP_ID.match(parts[0]):
            continue
        items.append(flathub_item(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return items


def installed_flatpaks(run: Run = subprocess.run) -> set[str]:
    try:
        result = run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True,
                     timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in (result.stdout or "").splitlines() if APP_ID.match(line.strip())}


def search(items: Iterable[Item], query: str, lang: str) -> list[Item]:
    needle = query.strip().casefold()
    if not needle:
        return list(items)
    found = []
    for item in items:
        haystack = " ".join([item.id, *item.title.values(), *item.description.values(), *item.keywords,
                             item.category_name(lang)]).casefold()
        if needle in haystack:
            found.append(item)
    return found
