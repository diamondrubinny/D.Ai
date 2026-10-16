# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""First-run logic, without any GUI: when to show the wizard, which security
plan each level means, which models fit this computer, and the setup run.

Security changes go through the D.Ai Tune planner, root helper and journal
(undo with `dai-tune undo`); downloads go through the pinned model catalog.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from dai_tune import posture
from dai_tune.context import Context
from dai_tune.planner import Plan, plan_from_text

LEVELS = ("recommended", "strict", "keep")
STATE_VERSION = 1

# Plain sentences for D.Ai Tune (the same ones a user could type).
LOCK = "lock the screen after 5 minutes"
UPDATES = "enable automatic updates"
STRICT_EXTRA = ("block usb storage", "turn off bluetooth")

ASSISTANT_SMALL, CODER, VOICE = "qwen2.5-0.5b", "qwen2.5-coder-1.5b", "whisper-base"
MIN_AI_RAM_MB, CODER_RAM_MB = 4000, 8000


def state_path(home: Path) -> Path:
    return home / ".config" / "dai" / "welcome.json"


def is_live(root: Path = Path("/")) -> bool:
    return (root / "run" / "live" / "medium").exists()


def first_run_needed(home: Path, root: Path = Path("/")) -> bool:
    """The wizard opens by itself once, on an installed system only."""
    return not is_live(root) and not state_path(home).exists()


def mark_done(home: Path, summary: dict | None = None) -> Path:
    path = state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {"version": STATE_VERSION, "done": int(time.time()), **(summary or {})}
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)
    return path


def security_sentences(level: str, checks: list[posture.Check]) -> list[str]:
    if level not in LEVELS:
        raise ValueError(f"unknown level: {level}")
    if level == "keep":
        return []
    ok = {check.key: check.ok for check in checks}
    sentences = []
    if not ok.get("lock", False):
        sentences.append(LOCK)
    if not ok.get("updates", False):
        sentences.append(UPDATES)
    if level == "strict":
        sentences.extend(STRICT_EXTRA)
    return sentences


def security_plan(level: str, ctx: Context) -> Plan | None:
    """None when there is nothing to change; otherwise a fully valid plan."""
    _, checks = posture.assess(ctx, ctx.lang)
    sentences = security_sentences(level, checks)
    if not sentences:
        return None
    plan = plan_from_text(", ".join(sentences), ctx)
    if not plan.ok:
        raise ValueError("internal error: the security plan is not valid: " + "; ".join(plan.errors + plan.unknown))
    return plan


def ram_mb(meminfo: Path = Path("/proc/meminfo")) -> int:
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


@dataclass
class Option:
    key: str            # assistant | code | voice
    model_id: str
    checked: bool
    enabled: bool = True
    note: str = ""      # "included" | "low_ram" | ""


def ai_options(ram: int, installed: set[str] = frozenset()) -> list[Option]:
    """What to offer, pre-checked according to the memory of this computer."""
    big = ram >= CODER_RAM_MB
    assistant = Option("assistant", CODER if big else ASSISTANT_SMALL, ram >= MIN_AI_RAM_MB,
                       note="" if ram >= MIN_AI_RAM_MB else "low_ram")
    if big:  # the coding model also answers general questions
        code = Option("code", CODER, True, enabled=False, note="included")
    else:
        code = Option("code", CODER, False, note="" if ram >= MIN_AI_RAM_MB else "low_ram")
    voice = Option("voice", VOICE, True)
    options = [assistant, code, voice]
    for option in options:
        if option.model_id in installed:
            option.checked, option.enabled, option.note = True, False, "installed"
    return options


def chosen_models(options: list[Option]) -> list[str]:
    """Unique model ids to download, in order."""
    seen: list[str] = []
    for option in options:
        if option.checked and option.note != "installed" and option.model_id not in seen:
            seen.append(option.model_id)
    return seen


@dataclass
class Result:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class Setup:
    plan: Plan | None = None
    models: list[str] = field(default_factory=list)


def run_setup(setup: Setup, ctx: Context, progress: Callable[[str], None],
              apply=None, install=None, catalog=None, set_default=None) -> list[Result]:
    """Apply the security plan, then download the chosen models.

    One failed step does not undo the others; every result is reported.
    """
    if apply is None:
        from dai_tune.cli import apply_plan as apply
    if install is None or catalog is None or set_default is None:
        from dai_ai import models as _models
        install = install or _models.install
        catalog = catalog if catalog is not None else _models.load_catalog()
        set_default = set_default or _models.set_default
    results: list[Result] = []
    if setup.plan is not None:
        progress("security")
        outcome = apply(setup.plan, ctx, label="D.Ai Welcome")
        results.append(Result("security", outcome.ok, outcome.error))
    for model_id in setup.models:
        model = catalog[model_id]
        progress(f"model:{model_id}:0")
        try:
            install(model, progress=lambda done, total, m=model_id: progress(f"model:{m}:{done * 100 // max(total, 1)}"))
            if "speech" in model.tasks:
                set_default(model_id, "speech_model")
            results.append(Result(model_id, True))
        except Exception as exc:  # reported to the user; other steps continue
            results.append(Result(model_id, False, str(exc) or exc.__class__.__name__))
    # Chat uses the fast assistant when there is one; "code" picks the coder by itself.
    installed_ok = {r.label for r in results if r.ok}
    for chat_model in (ASSISTANT_SMALL, CODER):
        if chat_model in installed_ok:
            set_default(chat_model)
            break
    return results
