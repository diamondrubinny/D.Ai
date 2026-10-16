# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Organization policies: the same D.Ai Tune sentences, for a whole fleet.

An administrator (school, office) drops JSON files into /etc/dai/policy.d/
by any means (USB stick, Ansible, a package). At boot, and whenever that
folder changes, the root helper applies each policy whose plan changed:

  {"format": 1, "name": "School computers", "apply": ["block usb storage", "turn off bluetooth"]}

A policy file is ignored unless it is owned by root, not writable by group
or others, not a symlink and at most 64 KB. Only system-scope steps are
allowed, every step goes through the closed catalog, and everything is
journaled like any other change (dai-tune undo works).
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .context import Context, write_file
from .planner import Plan, plan_from_text

POLICY_DIR = "/etc/dai/policy.d"
STATE_FILE = "/var/lib/dai/policy-state.json"  # hashes only, readable for `dai-tune policy`
MAX_SIZE = 64 * 1024
MAX_SENTENCES = 50


@dataclass
class Policy:
    path: Path
    name: str = ""
    plan: Plan | None = None
    problems: list[str] = field(default_factory=list)


def _trusted(path: Path, ctx: Context) -> str:
    """Why this file cannot be trusted, or "" when it can."""
    if path.is_symlink():
        return "is a symlink"
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        return "is not a regular file"
    if info.st_size > MAX_SIZE:
        return "is larger than 64 KB"
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return "is writable by group or others"
    if ctx.root == Path("/") and info.st_uid != 0:
        return "is not owned by root"
    return ""


def load(ctx: Context) -> list[Policy]:
    directory = ctx.path(POLICY_DIR)
    if not directory.is_dir():
        return []
    policies = []
    for path in sorted(directory.glob("*.json")):
        policy = Policy(path)
        policies.append(policy)
        reason = _trusted(path, ctx)
        if reason:
            policy.problems.append(f"ignored: the file {reason}")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            policy.problems.append(f"not valid JSON: {exc}")
            continue
        sentences = data.get("apply") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(sentences, list) \
                or not 1 <= len(sentences) <= MAX_SENTENCES \
                or not all(isinstance(s, str) and 0 < len(s) <= 200 for s in sentences):
            policy.problems.append('expected {"format": 1, "name": "...", "apply": ["sentence", ...]}')
            continue
        policy.name = str(data.get("name", path.stem))[:80]
        plan = plan_from_text(", ".join(sentences), ctx)
        if not plan.ok:
            policy.problems += plan.errors + [f"not understood: {u}" for u in plan.unknown]
            continue
        user_steps = [s.action for s in plan.steps if s.scope != "system"]
        if user_steps:
            policy.problems.append(f"only system settings can be set by a policy, not: {', '.join(user_steps)}")
            continue
        policy.plan = plan
    return policies


def _state(ctx: Context) -> dict[str, str]:
    try:
        data = json.loads(ctx.path(STATE_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def status(ctx: Context) -> list[dict]:
    applied = _state(ctx)
    rows = []
    for policy in load(ctx):
        current = policy.plan.hash if policy.plan else None
        state = "rejected" if policy.problems else "applied" if applied.get(policy.path.name) == current else "pending"
        rows.append({"file": policy.path.name, "name": policy.name, "state": state, "problems": policy.problems,
                     "steps": [s.action for s in policy.plan.steps] if policy.plan else []})
    return rows


def apply_all(ctx: Context, journal, actor: str = "policy") -> list[dict]:
    """Apply every valid policy whose plan changed since it was last applied."""
    from .executor import ApplyError, apply_steps

    applied = _state(ctx)
    results = []
    for policy in load(ctx):
        if policy.problems or policy.plan is None:
            results.append({"file": policy.path.name, "ok": False, "detail": "; ".join(policy.problems)})
            continue
        if applied.get(policy.path.name) == policy.plan.hash:
            results.append({"file": policy.path.name, "ok": True, "detail": "unchanged"})
            continue
        try:
            entry = apply_steps(policy.plan.steps, ctx, journal, actor=actor, scope="system",
                                extra={"summary": [f"policy: {policy.name}"]})
        except ApplyError as exc:
            results.append({"file": policy.path.name, "ok": False, "detail": str(exc)})
            continue
        applied[policy.path.name] = policy.plan.hash
        results.append({"file": policy.path.name, "ok": True, "detail": f"applied {entry['id']}"})
    state_path = ctx.path(STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_file(state_path, json.dumps(applied, indent=1), mode=0o644)
    return results
