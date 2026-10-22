# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""A Program as one D.Ai Tune plan (docs/WAY.md §2): sentences, recipes and exact actions together.

A sentence not understood, an app no recipe matches, an exact line the catalog refuses: each is a problem
with its line number, and a Program with problems has no plan. Nothing is applied in part.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dai_forge.recipes import Library, find, install_requests, load_library
from dai_tune.catalog import CATALOG
from dai_tune.context import Context
from dai_tune.parser import Request, parse as parse_sentence
from dai_tune.planner import Plan, build_plan

from .language import APP_ID, Line, Program, WayError, parse_exact


@dataclass
class Compiled:
    requests: list[Request] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)      # "file:line: what"
    plan: Plan | None = None

    @property
    def ok(self) -> bool:
        return not self.problems and self.plan is not None and self.plan.ok


def _where(line: Line) -> str:
    return f"{line.file}:{line.number}"


def compile_program(program: Program, ctx: Context, library: Library | None = None) -> Compiled:
    out = Compiled()
    library = library or load_library()
    for line in program.setup:
        parsed = parse_sentence(line.text)
        for unknown in parsed.unknown:
            out.problems.append(f"{_where(line)}: not understood: {unknown}")
        for request in parsed.requests:
            out.requests.append(Request(request.action, request.params, f"{_where(line)}: {line.text}"))
    for line in program.apps:
        text = line.text.strip()
        if APP_ID.match(text) and text not in library.recipes:
            out.requests.append(Request("flatpak.remote", {"name": "flathub"}, f"{_where(line)}: {text}"))
            out.requests.append(Request("flatpak.install", {"apps": [text], "remote": "flathub"}, f"{_where(line)}: {text}"))
            continue
        recipe = library.recipes.get(text)
        if recipe is None:
            recipe, ambiguous = find(text, library)
            if ambiguous:
                out.problems.append(f"{_where(line)}: more than one recipe matches: {text}")
                continue
        if recipe is None:
            out.problems.append(f"{_where(line)}: no recipe called {text} (dai-forge recipe list)")
            continue
        for request in install_requests(recipe):
            out.requests.append(Request(request.action, request.params, f"{_where(line)}: {recipe.id}"))
    for line in program.exact:
        try:
            action, params = parse_exact(line.text)
        except WayError as exc:
            out.problems.append(f"{_where(line)}: {exc.message}")
            continue
        if action not in CATALOG:
            out.problems.append(f"{_where(line)}: no such action: {action}")
            continue
        out.requests.append(Request(action, params, f"{_where(line)}: {line.text}"))
    if out.problems:
        return out
    if not out.requests:
        out.problems.append("the file asks for nothing")
        return out
    out.plan = build_plan(out.requests, ctx)
    for error in out.plan.errors:
        out.problems.append(error)
    for unknown in out.plan.unknown:
        out.problems.append(f"not understood: {unknown}")
    return out
