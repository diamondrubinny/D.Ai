# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Recipes: named, shareable D.Ai Tune plans that add a capability.

A recipe is data, never code: a list of catalog actions with parameters. It
is turned into requests for the D.Ai Tune planner, which validates every
step; system steps are validated again by the root helper. Recipes come from
three places, in this order of precedence:

  admin    /etc/dai/forge/recipes          (installed by an administrator)
  builtin  /usr/share/dai/forge/recipes    (shipped with D.Ai OS)
  user     ~/.local/share/dai/forge/recipes

A user recipe can never replace an admin or built-in recipe with the same id,
so software running as the user cannot swap, say, the antivirus recipe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dai_tune.catalog import CATALOG
from dai_tune.parser import Request

from . import paths

FORMAT = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_FILE = 64 * 1024
MAX_STEPS = 20
MAX_KEYWORDS = 20
SOURCES = ("admin", "builtin", "user")  # precedence order

REMOVE_WORDS = re.compile(
    r"(?:\b(?:remove|uninstall|delete|disable|get rid of)\b|הסר|תסיר|להסיר|הסרת|מחק|תמחק|למחוק|בטל|תבטל|לבטל|כבה|תכבה|לכבות)",
    re.IGNORECASE,
)


class RecipeError(ValueError):
    pass


@dataclass(frozen=True)
class Recipe:
    id: str
    name: dict[str, str]
    description: dict[str, str]
    match: dict[str, list[str]]
    steps: list[dict[str, Any]]
    source: str = "user"
    path: Path | None = None
    author: str = ""

    def title(self, lang: str) -> str:
        return self.name.get(lang) or self.name.get("en") or self.id

    def about(self, lang: str) -> str:
        return self.description.get(lang) or self.description.get("en", "")

    def keywords(self) -> list[str]:
        return [self.id, *self.name.values(), *(k for words in self.match.values() for k in words)]

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": FORMAT,
            "id": self.id,
            "name": self.name,
            "match": self.match,
            "steps": self.steps,
        }
        if self.description:
            data["description"] = self.description
        if self.author:
            data["author"] = self.author
        return data


def _text_map(value: Any, what: str, limit: int, required: bool = True) -> dict[str, str]:
    if not required and (value is None or value == {}):
        return {}
    if not isinstance(value, dict) or not value or set(value) - {"en", "he"}:
        raise RecipeError(f"{what}: expected {{\"en\": ..., \"he\": ...}}")
    out = {}
    for lang, text in value.items():
        if not isinstance(text, str) or not text.strip() or len(text) > limit or any(ord(ch) < 32 for ch in text):
            raise RecipeError(f"{what}.{lang}: 1-{limit} printable characters")
        out[lang] = text.strip()
    return out


def validate(data: Any, source: str = "user", path: Path | None = None) -> Recipe:
    """Check the recipe's shape. Step parameters are validated by the planner."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise RecipeError("not a D.Ai Forge recipe (format 1)")
    extra = set(data) - {"format", "id", "name", "description", "match", "steps", "author"}
    if extra:
        raise RecipeError(f"unexpected fields: {', '.join(sorted(extra))}")
    rid = data.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        raise RecipeError(f"invalid recipe id: {rid!r}")
    match = data.get("match", {})
    if not isinstance(match, dict) or set(match) - {"en", "he"}:
        raise RecipeError("match: expected {\"en\": [...], \"he\": [...]}")
    clean_match: dict[str, list[str]] = {}
    for lang, words in match.items():
        if not isinstance(words, list) or len(words) > MAX_KEYWORDS:
            raise RecipeError(f"match.{lang}: up to {MAX_KEYWORDS} phrases")
        for word in words:
            if not isinstance(word, str) or not 2 <= len(word.strip()) <= 40:
                raise RecipeError(f"match.{lang}: phrases are 2-40 characters")
        clean_match[lang] = [w.strip().casefold() for w in words]
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise RecipeError(f"steps: 1-{MAX_STEPS} catalog actions")
    clean_steps = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"action", "params"} or not isinstance(step["params"], dict):
            raise RecipeError("each step is {\"action\": ..., \"params\": {...}}")
        if step["action"] not in CATALOG:
            raise RecipeError(f"unknown action: {step['action']!r}")
        clean_steps.append({"action": step["action"], "params": dict(step["params"])})
    author = data.get("author", "")
    if not isinstance(author, str) or len(author) > 80:
        raise RecipeError("author: up to 80 characters")
    return Recipe(
        id=rid,
        name=_text_map(data.get("name"), "name", 80),
        description=_text_map(data.get("description"), "description", 400, required=False),
        match=clean_match,
        steps=clean_steps,
        source=source,
        path=path,
        author=author,
    )


def load_file(path: Path, source: str = "user") -> Recipe:
    if path.stat().st_size > MAX_FILE:
        raise RecipeError(f"{path.name}: larger than {MAX_FILE // 1024} KB")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecipeError(f"{path.name}: invalid JSON ({exc})") from exc
    recipe = validate(data, source, path)
    if path.stem != recipe.id:
        raise RecipeError(f"{path.name}: file name must be {recipe.id}.json")
    return recipe


@dataclass
class Library:
    recipes: dict[str, Recipe] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)  # invalid or shadowed files


def source_dirs() -> dict[str, Path]:
    return {"admin": paths.ADMIN_RECIPES, "builtin": paths.BUILTIN_RECIPES, "user": paths.user_recipes()}


def load_library(dirs: dict[str, Path] | None = None) -> Library:
    library = Library()
    for source in SOURCES:
        directory = (dirs or source_dirs()).get(source)
        if directory is None or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                recipe = load_file(path, source)
            except (OSError, RecipeError) as exc:
                library.problems.append(f"{path}: {exc}")
                continue
            if recipe.id in library.recipes:
                owner = library.recipes[recipe.id].source
                library.problems.append(f"{path}: ignored, the {owner} recipe '{recipe.id}' takes precedence")
                continue
            library.recipes[recipe.id] = recipe
    return library


# --------------------------------------------------------------------------
# Matching text to recipes
# --------------------------------------------------------------------------


def _normalize(text: str) -> str:
    text = text.replace("״", '"').replace("׳", "'").replace("’", "'").replace("-", " ")
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _contains(text: str, phrase: str) -> bool:
    phrase = _normalize(phrase)
    if re.search(r"[a-z0-9]", phrase):
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None
    # Hebrew attaches prefixes (ה, ל, ו, ש, את ה...): match inside words.
    return phrase in text


def find(text: str, library: Library) -> tuple[Recipe | None, bool]:
    """The best matching recipe and whether the text asks to remove it."""
    normalized = _normalize(text)
    best: tuple[int, Recipe] | None = None
    for recipe in library.recipes.values():
        for phrase in recipe.keywords():
            if len(phrase) >= 2 and _contains(normalized, phrase):
                score = len(_normalize(phrase))
                if best is None or score > best[0]:
                    best = (score, recipe)
    if best is None:
        return None, False
    return best[1], REMOVE_WORDS.search(normalized) is not None


# --------------------------------------------------------------------------
# Recipes -> D.Ai Tune requests
# --------------------------------------------------------------------------


def install_requests(recipe: Recipe) -> list[Request]:
    return [Request(step["action"], dict(step["params"]), recipe.id) for step in recipe.steps]


def _reverse(step: dict[str, Any]) -> dict[str, Any] | None:
    action, params = step["action"], step["params"]
    if action == "packages.install":
        return {"action": "packages.remove", "params": params}
    if action in ("service.unit", "service.user_unit") and params.get("enabled") is True:
        return {"action": action, "params": {**params, "enabled": False}}
    if action == "flatpak.install":
        return {"action": "flatpak.remove", "params": params}
    if action == "firewall.open_port":
        return {"action": "firewall.close_port", "params": {k: v for k, v in params.items() if k != "source"}}
    if action == "antivirus.schedule" and params.get("enabled", True) is True:
        return {"action": action, "params": {**params, "enabled": False}}
    if action == "device.block":
        return {"action": "device.allow", "params": params}
    # flatpak.remote and settings stay: other software may rely on them.
    return None


def remove_requests(recipe: Recipe) -> list[Request]:
    """Undo what a recipe sets up, in reverse order."""
    reversed_steps = [_reverse(step) for step in reversed(recipe.steps)]
    return [Request(s["action"], s["params"], recipe.id) for s in reversed_steps if s]


def save_user_recipe(recipe: Recipe) -> Path:
    directory = paths.user_recipes()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{recipe.id}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(recipe.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target
