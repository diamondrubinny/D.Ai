# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The organization's say on agents (docs/AGENTS.md §6ג): /etc/dai/policy-agent.env, written by D.Ai Tune's
agent.policy (also from /etc/dai/policy.d). DAI_AGENT_ROLES=none turns agents off; a comma list allows those
roles only; no file (or "all") allows every role."""
from __future__ import annotations

from pathlib import Path

from dai_i18n import pick

from .roles import ROLES

POLICY_AGENT_ENV = "/etc/dai/policy-agent.env"


def allowed_roles(root: Path | None = None) -> tuple[str, ...]:
    """The role names a person may use here; () when agents are off."""
    path = (root or Path("/")) / POLICY_AGENT_ENV.lstrip("/")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return tuple(ROLES)
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "DAI_AGENT_ROLES":
            value = value.strip().strip('"')
            if value == "none":
                return ()
            if value in ("", "all"):
                return tuple(ROLES)
            return tuple(name for name in ROLES if name in {v.strip() for v in value.split(",")})
    return tuple(ROLES)


def refusal(role: str, lang: str, root: Path | None = None) -> str:
    """"" when the role is allowed; else one clear line for the person."""
    allowed = allowed_roles(root)
    if role in allowed:
        return ""
    if not allowed:
        return pick(lang, "Agents are turned off on this computer by the organization's policy.",
                    "סוכנים כבויים במחשב הזה לפי מדיניות הארגון.")
    return pick(lang, "The organization's policy allows only these roles here: {roles}.",
                "מדיניות הארגון מתירה כאן רק את התפקידים: {roles}.").format(roles=", ".join(allowed))
