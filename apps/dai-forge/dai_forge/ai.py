# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Local-AI generation for D.Ai Forge: app code and new recipes.

Everything is requested through daid (local, AF_UNIX only) with a JSON schema,
then validated here and again downstream:
  * app code must parse and pass the size limit; it runs only in the sandbox
  * recipe steps must be catalog actions; the D.Ai Tune planner and the root
    helper validate every parameter, and AI recipes always need manual review
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable

from dai_tune.ai import action_ids
from dai_tune.ai import system_prompt as tune_prompt

from .apps import MAX_CODE, AppError
from .recipes import ID_RE, MAX_STEPS, Recipe, RecipeError, validate


class AIError(RuntimeError):
    """The local AI is unavailable or replied with something unusable."""


ChatFn = Callable[..., Iterable[str]]


def _default_chat() -> ChatFn:
    try:
        from dai_ai.client import AIUnavailable, chat
    except ImportError as exc:
        raise AIError("the local AI is not installed") from exc

    def run(*args: Any, **kwargs: Any) -> Iterable[str]:
        try:
            yield from chat(*args, **kwargs)
        except AIUnavailable as exc:
            raise AIError(f"{exc} — install a model: dai-models install qwen2.5-coder-1.5b") from exc

    return run


def _collect(chat: ChatFn, messages: list[dict[str, str]], schema: dict, max_tokens: int, task: str,
             progress: Callable[[str], None] | None) -> dict[str, Any]:
    """Run the chat; progress() receives the reply received so far."""
    parts: list[str] = []
    for piece in chat(messages, schema=schema, max_tokens=max_tokens, task=task):
        parts.append(piece)
        if progress:
            progress("".join(parts))
    reply = "".join(parts)
    try:
        data = json.loads(reply)
    except json.JSONDecodeError as exc:
        raise AIError("the AI reply was incomplete (too long for the model?). "
                      "Try a simpler request or a larger model.") from exc
    if not isinstance(data, dict):
        raise AIError("unexpected AI reply")
    return data


# --------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------

APP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,30}$"},
        "title": {"type": "string", "maxLength": 60},
        "network": {"type": "boolean"},
        "documents": {"type": "boolean"},
        "downloads": {"type": "boolean"},
        "code": {"type": "string", "maxLength": MAX_CODE},
    },
    "required": ["name", "title", "network", "documents", "code"],
}

COMMON_RULES = (
    "The app runs in a sandbox: its home directory (os.path.expanduser('~')) is its own private folder - "
    "store all data there. It has no network unless you set network=true, and sees ~/Documents only with "
    "documents=true; ask for these only if the request really needs them. "
    "Never use subprocess, os.system, eval, exec, ctypes or pickle. Write clean, commented, working code. "
    "Use the language of the request (Hebrew or English) for all text the user sees. "
)
KIND_RULES = {
    "gui": (
        "Write ONE complete Python 3 file for a desktop app using PyQt6 and the standard library only. "
        "Start with '#!/usr/bin/env python3', create QApplication(sys.argv), show a window, end with "
        "sys.exit(app.exec()). If the text is Hebrew call app.setLayoutDirection(Qt.LayoutDirection.RightToLeft). "
        "Accessibility: every control has setAccessibleName, buttons have clear labels, the app is fully usable "
        "with the keyboard, fonts are at least 11pt. "
    ),
    "cli": (
        "Write ONE complete Python 3 command-line program using the standard library only "
        "(input/print, argparse when useful). Start with '#!/usr/bin/env python3' and a main() function. "
    ),
    "automation": (
        "Write ONE complete Python 3 script using the standard library only. It runs UNATTENDED on a schedule: "
        "never call input(), finish within a few minutes, and make it safe to run again (idempotent). "
        "To tell the user something, print a line that starts with 'NOTIFY: ' followed by a short message in "
        "the user's language; it becomes a desktop notification (at most 3 per run). Other output goes to a log. "
        "Its ~/Downloads is visible only with downloads=true and ~/Documents only with documents=true. "
        "Never delete anything outside those folders, and prefer moving files to a subfolder over deleting them. "
        "Start with '#!/usr/bin/env python3' and a main() function. "
    ),
    "web": (
        "Write ONE complete HTML5 document with inline CSS and JavaScript, no external files, fonts or CDNs. "
        "Use <html lang=\"he\" dir=\"rtl\"> for Hebrew. Store data in localStorage. Accessibility: semantic "
        "elements, <label> for inputs, visible focus, good contrast, keyboard usable. "
    ),
}


def app_messages(request: str, kind: str, current: str | None = None) -> list[dict[str, str]]:
    system = (
        "You are D.Ai Forge, the app builder of D.Ai OS. " + KIND_RULES[kind] + COMMON_RULES +
        "Reply only with JSON: name (short id, a-z 0-9 -), title (short, in the user's language), "
        "network (bool), documents (bool), downloads (bool), code (the complete file)."
    )
    if current is None:
        user = f"Build this: {request}"
    else:
        user = (
            f"Here is the current code of the app:\n```\n{current}\n```\n"
            f"Change it as follows: {request}\nReturn the complete updated file in 'code'."
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def partial_code(reply: str) -> str:
    """The "code" string of a JSON reply that is still being streamed (for live display)."""
    match = re.search(r'"code"\s*:\s*"', reply)
    if not match:
        return ""
    body, out, i = reply[match.end():], [], 0
    escapes = {"n": "\n", "t": "\t", "r": "", '"': '"', "\\": "\\", "/": "/", "b": "", "f": ""}
    while i < len(body):
        char = body[i]
        if char == "\\":
            if i + 1 >= len(body):
                break
            nxt = body[i + 1]
            if nxt == "u":
                if i + 6 > len(body):
                    break
                try:
                    out.append(chr(int(body[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(escapes.get(nxt, nxt))
            i += 2
            continue
        if char == '"':
            break
        out.append(char)
        i += 1
    return "".join(out)


def generate_app(request: str, kind: str, current: str | None = None, chat: ChatFn | None = None,
                 progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    chat = chat or _default_chat()
    data = _collect(chat, app_messages(request, kind, current), APP_SCHEMA, 4096, "code", progress)
    code = data.get("code")
    if not isinstance(code, str) or not code.strip():
        raise AIError("the AI did not return any code")
    code = re.sub(r"^```[a-z]*\n|\n```\s*$", "", code.strip()) + "\n"
    name = data.get("name") if isinstance(data.get("name"), str) else "app"
    return {
        "name": name,
        "title": str(data.get("title") or name)[:60],
        "network": data.get("network") is True,
        "documents": data.get("documents") is True,
        "downloads": data.get("downloads") is True,
        "code": code,
    }


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------


def recipe_schema() -> dict[str, Any]:
    actions = [a for a in action_ids() if not a.startswith("preset.")]
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "pattern": ID_RE.pattern},
            "name_en": {"type": "string", "maxLength": 80},
            "name_he": {"type": "string", "maxLength": 80},
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_STEPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": actions},
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            },
        },
        "required": ["id", "name_en", "name_he", "steps"],
    }


def recipe_messages(request: str) -> list[dict[str, str]]:
    system = (
        "You are D.Ai Forge. Turn the administrator's request into a recipe: a short list of steps that set up "
        "the requested capability on Debian 13, using ONLY the actions below. Prefer Debian packages; use "
        "Flathub only for desktop apps that are not in Debian. Open firewall ports to the local network only. "
        "If the request cannot be done with these actions, return steps that do as much as is safe, or a single "
        "packages.install step with the right Debian package.\n\n" + tune_prompt()
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": request}]


def author_recipe(request: str, chat: ChatFn | None = None) -> Recipe:
    chat = chat or _default_chat()
    data = _collect(chat, recipe_messages(request), recipe_schema(), 800, "general", None)
    steps = data.get("steps")
    if isinstance(steps, list):
        steps = [s for s in steps if isinstance(s, dict) and not str(s.get("action", "")).startswith("preset.")]
    raw = {
        "format": 1,
        "id": data.get("id"),
        "name": {"en": str(data.get("name_en") or data.get("id") or "recipe"),
                 "he": str(data.get("name_he") or data.get("name_en") or data.get("id") or "מתכון")},
        "description": {"en": f"Written by the local AI for: {request}"[:400],
                        "he": f"נכתב ע\"י ה־AI המקומי עבור: {request}"[:400]},
        "match": {},
        "steps": steps,
        "author": "D.Ai Forge AI",
    }
    try:
        return validate(raw, source="ai")
    except RecipeError as exc:
        raise AIError(f"the AI recipe is not valid: {exc}") from exc


__all__ = ["AIError", "AppError", "author_recipe", "generate_app", "app_messages", "recipe_schema"]
