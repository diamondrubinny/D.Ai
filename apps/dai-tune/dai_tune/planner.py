"""Validate requests against the catalog and build a reviewable plan."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from .catalog import CATALOG, ValidationError, load_firewall_rules
from .context import Context
from .parser import Request, parse

MAX_STEPS = 20
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Step:
    action: str
    params: dict[str, Any]
    scope: str
    risk: str
    effect: str
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "params": self.params}


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Only a fully understood, fully valid plan may be applied."""
        return bool(self.steps) and not self.errors and not self.unknown

    @property
    def weakens(self) -> bool:
        return any(step.effect == "weakens" for step in self.steps)

    @property
    def risk(self) -> str:
        return max((s.risk for s in self.steps), key=RISK_ORDER.__getitem__, default="low")

    def scoped(self, scope: str) -> list[Step]:
        return [s for s in self.steps if s.scope == scope]

    @property
    def hash(self) -> str:
        return plan_hash(self.steps)

    def to_json(self) -> dict[str, Any]:
        return {"version": 1, "hash": self.hash, "steps": [s.as_dict() for s in self.steps]}


def plan_hash(steps: Iterable[Step]) -> str:
    canonical = json.dumps([s.as_dict() for s in steps], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _expand(request: Request, ctx: Context) -> list[Request]:
    """Presets become concrete actions; some actions pull in safe companions."""
    src = request.source
    if request.action == "preset.public":
        expanded = [
            Request("device.block", {"kind": "bluetooth"}, src),
            Request("session.lock", {"minutes": 3}, src),
        ]
        for rule in load_firewall_rules(ctx):
            if rule.get("source") == "any":
                expanded.append(Request("firewall.close_port", {"port": rule["port"], "proto": rule["proto"]}, src))
        return expanded
    if request.action == "preset.privacy":
        return [Request("device.block", {"kind": "camera"}, src), Request("device.block", {"kind": "bluetooth"}, src)]
    if request.action == "service.ssh":
        rules = {(r.get("port"), r.get("proto")) for r in load_firewall_rules(ctx)}
        if request.params.get("enabled") is True:
            expanded = []
            if not ctx.path("/usr/sbin/sshd").exists():
                expanded.append(Request("packages.install", {"names": ["openssh-server"]}, src))
            expanded.append(request)
            if (22, "tcp") not in rules:
                # Secure default: SSH reachable from the local network only.
                expanded.append(Request("firewall.open_port", {"port": 22, "proto": "tcp", "source": "lan"}, src))
            return expanded
        if request.params.get("enabled") is False and (22, "tcp") in rules:
            return [request, Request("firewall.close_port", {"port": 22, "proto": "tcp"}, src)]
    return [request]


def build_plan(requests: Iterable[Request], ctx: Context, unknown: Iterable[str] = ()) -> Plan:
    plan = Plan(unknown=list(unknown))
    seen: set[str] = set()
    for request in (r for original in requests for r in _expand(original, ctx)):
        spec = CATALOG.get(request.action)
        if spec is None:
            plan.errors.append(f"{request.source or request.action}: unknown action {request.action!r}")
            continue
        try:
            params = spec.validate(dict(request.params), ctx)
        except ValidationError as exc:
            plan.errors.append(f"{request.source or request.action}: {exc}")
            continue
        key = json.dumps([request.action, params], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        plan.steps.append(Step(
            action=request.action,
            params=params,
            scope=spec.scope,
            risk=spec.risk(params),
            effect=spec.effect(params),
            source=request.source,
        ))
    if len(plan.steps) > MAX_STEPS:
        plan.errors.append(f"too many changes at once ({len(plan.steps)} > {MAX_STEPS})")
    return plan


def plan_from_text(text: str, ctx: Context) -> Plan:
    parsed = parse(text)
    return build_plan(parsed.requests, ctx, parsed.unknown)


def steps_from_json(data: Any, ctx: Context, scope: str) -> list[Step]:
    """Strictly rebuild steps from untrusted JSON (used by the root helper).

    Every step must name a catalog action of the given scope, and its
    parameters are validated again from scratch. Presets are not accepted
    here: they are expanded by the planner before reaching the helper.
    """
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("steps"), list):
        raise ValidationError("malformed plan")
    raw_steps = data["steps"]
    if not 1 <= len(raw_steps) <= MAX_STEPS:
        raise ValidationError("plan must contain 1-20 steps")
    steps: list[Step] = []
    for raw in raw_steps:
        if not isinstance(raw, dict) or set(raw) != {"action", "params"} or not isinstance(raw["params"], dict):
            raise ValidationError("malformed step")
        spec = CATALOG.get(raw["action"])
        if spec is None:
            raise ValidationError(f"unknown action {raw['action']!r}")
        if spec.scope != scope:
            raise ValidationError(f"action {raw['action']} is not allowed in {scope} scope")
        params = spec.validate(dict(raw["params"]), ctx)
        steps.append(Step(raw["action"], params, spec.scope, spec.risk(params), spec.effect(params)))
    if data.get("hash") != plan_hash(steps):
        raise ValidationError("plan hash mismatch")
    return steps
