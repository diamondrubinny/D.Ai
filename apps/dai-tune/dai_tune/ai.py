# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Local-AI interpretation for sentences the rule parser does not understand.

The model never acts. It is constrained by a JSON schema to the catalog's
action ids, and whatever it returns is validated by the planner exactly like
rule-parsed requests, shown as an "AI interpretation" and always needs manual
confirmation.
"""

from __future__ import annotations

import json
from typing import Any

from .catalog import CATALOG
from .parser import EXAMPLES, Request, parse

PRESETS = ("preset.public", "preset.privacy")
MAX_REQUESTS = 10


def action_ids() -> list[str]:
    return sorted(CATALOG) + list(PRESETS)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "requests": {
                "type": "array",
                "maxItems": MAX_REQUESTS,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": action_ids()},
                        "params": {"type": "object"},
                    },
                    "required": ["action", "params"],
                },
            }
        },
        "required": ["requests"],
    }


def _examples() -> list[str]:
    lines = []
    for lang in ("en", "he"):
        for text in EXAMPLES[lang]:
            requests = [{"action": r.action, "params": r.params} for r in parse(text).requests]
            lines.append(f"{text} => {json.dumps({'requests': requests}, ensure_ascii=False)}")
    return lines


def system_prompt() -> str:
    return (
        "You convert a user's request about configuring their computer into JSON for D.Ai Tune.\n"
        "Use ONLY these actions: " + ", ".join(action_ids()) + ".\n"
        "Parameters: device.* {kind: usb_storage|camera|bluetooth}; firewall.open_port {port, proto: tcp|udp, "
        "source: lan|any (lan unless the user explicitly wants the internet)}; firewall.close_port {port, proto}; "
        "updates.auto {enabled}; service.ssh {enabled}; packages.install/remove {names: [debian package names]}; "
        "system.timezone {timezone: Area/City}; system.hostname {hostname}; session.lock {minutes, 0 = never}; "
        "keyboard.layouts {layouts: us|il|ru|ar|fr|de|es|it|ua}; "
        "service.unit / service.user_unit {unit: name.service, enabled}; flatpak.remote {name: flathub}; "
        "flatpak.install/remove {apps: [reverse-DNS Flathub ids]}; antivirus.schedule {enabled, frequency: daily|weekly}; "
        "presets take {}.\n"
        "If the request does not match any action, return {\"requests\": []}. Never invent actions.\n"
        "Examples:\n" + "\n".join(_examples())
    )


def model_installed() -> bool:
    """True when at least one local model file exists (no daemon is started)."""
    try:
        from dai_ai.paths import models_dir
    except ImportError:
        return False
    try:
        return any(models_dir().glob("*.gguf"))
    except OSError:
        return False


def interpret(text: str) -> list[Request] | None:
    """Ask the local AI; None when the AI is not available."""
    try:
        from dai_ai.client import AIUnavailable, chat
    except ImportError:
        return None
    try:
        reply = "".join(chat(
            [{"role": "system", "content": system_prompt()}, {"role": "user", "content": text}],
            schema=schema(),
            max_tokens=400,
        ))
    except AIUnavailable:
        return None
    return requests_from_reply(reply, text)


def requests_from_reply(reply: str, text: str) -> list[Request]:
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        return []
    raw = data.get("requests") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    requests = []
    for item in raw[:MAX_REQUESTS]:
        if isinstance(item, dict) and isinstance(item.get("action"), str) and isinstance(item.get("params"), dict):
            requests.append(Request(item["action"], item["params"], f"AI: {text}"))
    return requests
