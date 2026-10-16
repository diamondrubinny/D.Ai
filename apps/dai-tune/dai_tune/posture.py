# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Security posture score: read-only checks, each with a phrase that fixes it."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog import AUTO_UPGRADES, NFT_CONF, load_firewall_rules, lock_timeout_seconds
from .context import Context, read_text


@dataclass(frozen=True)
class Check:
    key: str
    ok: bool
    weight: int
    detail: str = ""
    fix: str = ""  # a phrase the user can type to dai-tune


TITLES = {
    "firewall": ("Firewall blocks unsolicited incoming traffic", "חומת האש חוסמת תעבורה נכנסת לא מבוקשת"),
    "exposed": ("No ports open to the whole internet", "אין פורטים פתוחים לכל האינטרנט"),
    "updates": ("Automatic security updates", "עדכוני אבטחה אוטומטיים"),
    "apparmor": ("AppArmor application confinement", "בידוד אפליקציות AppArmor"),
    "encryption": ("Disk encryption", "הצפנת דיסק"),
    "lock": ("Screen locks within 10 minutes", "המסך ננעל תוך 10 דקות"),
    "ssh": ("SSH off or limited to the local network", "SSH כבוי או מוגבל לרשת המקומית"),
}


def _firewall(ctx: Context) -> Check:
    conf = read_text(ctx.path(NFT_CONF))
    ok = re.search(r"hook\s+input[^;]*;\s*policy\s+drop", conf) is not None
    return Check("firewall", ok, 20, "", "" if ok else "reinstall the D.Ai firewall (nftables)")


def _exposed(ctx: Context, lang: str) -> Check:
    exposed = [r for r in load_firewall_rules(ctx) if r.get("source") == "any"]
    if not exposed:
        return Check("exposed", True, 15)
    first = exposed[0]
    ports = ", ".join(f"{r['port']}/{r['proto']}" for r in exposed)
    fix = f"סגור פורט {first['port']}" if lang == "he" else f"close port {first['port']}"
    return Check("exposed", False, 15, ports, fix)


def _updates(ctx: Context, lang: str) -> Check:
    ok = re.search(r'Unattended-Upgrade\s+"1"', read_text(ctx.path(AUTO_UPGRADES))) is not None
    fix = "" if ok else ("הפעל עדכונים אוטומטיים" if lang == "he" else "enable automatic updates")
    return Check("updates", ok, 15, "", fix)


def _apparmor(ctx: Context) -> Check:
    ok = read_text(ctx.path("/sys/module/apparmor/parameters/enabled")).strip() == "Y"
    return Check("apparmor", ok, 15)


def _encryption(ctx: Context, lang: str) -> Check:
    if ctx.path("/run/live/medium").exists():
        detail = "live session: choose encryption in the installer" if lang == "en" else "סשן חי: בחרו הצפנה בהתקנה"
        return Check("encryption", False, 15, detail)
    result = ctx.run(["lsblk", "-rno", "TYPE"], check=False)
    ok = "crypt" in result.stdout.split()
    return Check("encryption", ok, 15)


def _lock(ctx: Context, lang: str) -> Check:
    seconds = lock_timeout_seconds(ctx)
    ok = 0 < seconds <= 600
    detail = "off" if seconds == 0 else f"{seconds // 60} min"
    fix = "" if ok else ("נעל מסך אחרי 5 דקות" if lang == "he" else "lock the screen after 5 minutes")
    return Check("lock", ok, 10, detail, fix)


def _ssh(ctx: Context, lang: str) -> Check:
    active = ctx.run(["systemctl", "is-active", "ssh.service"], check=False).stdout.strip() == "active"
    if not active:
        return Check("ssh", True, 10)
    exposed = any(r.get("port") == 22 and r.get("source") == "any" for r in load_firewall_rules(ctx))
    fix = "" if not exposed else ("סגור פורט 22" if lang == "he" else "close port 22")
    return Check("ssh", not exposed, 10, "active", fix)


def assess(ctx: Context, lang: str = "en") -> tuple[int, list[Check]]:
    checks = [
        _firewall(ctx),
        _exposed(ctx, lang),
        _updates(ctx, lang),
        _apparmor(ctx),
        _encryption(ctx, lang),
        _lock(ctx, lang),
        _ssh(ctx, lang),
    ]
    score = sum(c.weight for c in checks if c.ok)
    return score, checks


def title(check: Check, lang: str) -> str:
    en, he = TITLES[check.key]
    return he if lang == "he" else en
