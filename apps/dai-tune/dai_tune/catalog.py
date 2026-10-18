# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The closed catalog of actions D.Ai Tune can perform.

Every action declares:
  * scope   — "user" (runs as the user) or "system" (runs in the root helper)
  * risk    — low / medium / high
  * effect  — hardens / weakens / neutral, possibly depending on parameters
  * validate(params, ctx) -> normalized params, raising ValidationError
  * files(params, ctx)    -> files it may change (snapshotted for undo)
  * capture(params, ctx)  -> extra state needed to undo (service states, ...)
  * apply(params, ctx)
  * restore(params, ctx, extra) -> undo work beyond restoring files

Commands are always argv lists built from validated values; nothing here ever
goes through a shell.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dai_i18n import text

from .context import ActionError, Context, read_text, write_file

Params = dict[str, Any]


class ValidationError(ValueError):
    """Parameters are not acceptable for the action."""


# --------------------------------------------------------------------------
# Validators
# --------------------------------------------------------------------------

PACKAGE_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]{0,62}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
TIMEZONE_RE = re.compile(r"^(?:UTC|[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z0-9_+-]+){1,2})$")
MAX_PACKAGES = 10

# Removing these would break the system or D.Ai itself.
PROTECTED_PACKAGES = re.compile(
    r"^(?:linux-image.*|linux-headers.*|systemd.*|sudo|nftables|apparmor.*|dbus.*|polkitd|pkexec|apt|dpkg|"
    r"libc6|base-files|bash|coreutils|login|passwd|python3|python3-minimal|python3-pyqt6|labwc|lxqt-.*|sddm|"
    r"network-manager|cryptsetup.*|live-.*|user-setup|grub.*|shim.*|unattended-upgrades|openssh-client)$"
)

DEVICE_MODULES = {
    "usb_storage": ("usb_storage", "uas"),
    "camera": ("uvcvideo",),
    "bluetooth": ("btusb",),
}
KEYBOARD_LAYOUTS = ("us", "il", "ru", "ar", "fr", "de", "es", "it", "ua")
LAN_V4 = "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16"
LAN_V6 = "fc00::/7, fe80::/10"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValidationError("expected true/false")


def _int(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{what}: expected a number")
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or not low <= value <= high:
        raise ValidationError(f"{what}: must be {low}-{high}")
    return value


def _choice(value: Any, choices: tuple[str, ...] | dict, what: str) -> str:
    if value not in choices:
        raise ValidationError(f"{what}: must be one of {', '.join(choices)}")
    return value


def _only_keys(params: Params, allowed: set[str]) -> None:
    extra = set(params) - allowed
    if extra:
        raise ValidationError(f"unexpected parameters: {', '.join(sorted(extra))}")


def _packages(value: Any, removing: bool) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PACKAGES:
        raise ValidationError(f"packages: 1-{MAX_PACKAGES} names")
    names: list[str] = []
    for name in value:
        if not isinstance(name, str) or not PACKAGE_RE.match(name):
            raise ValidationError(f"invalid package name: {name!r}")
        if removing and PROTECTED_PACKAGES.match(name):
            raise ValidationError(f"refusing to remove protected package: {name}")
        if name not in names:
            names.append(name)
    return names


# --------------------------------------------------------------------------
# Action specification
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    id: str
    scope: str  # user | system
    validate: Callable[[Params, Context], Params]
    apply: Callable[[Params, Context], None]
    risk: Callable[[Params], str]
    effect: Callable[[Params], str]
    summary: Callable[[Params, str], str]
    files: Callable[[Params, Context], list[Path]] = lambda p, c: []
    capture: Callable[[Params, Context], dict] = lambda p, c: {}
    restore: Callable[[Params, Context, dict], None] = lambda p, c, e: None
    note: Callable[[Params, str], str] = lambda p, lang: ""


CATALOG: dict[str, ActionSpec] = {}


def register(spec: ActionSpec) -> ActionSpec:
    CATALOG[spec.id] = spec
    return spec


def _t(lang: str, en: str, he: str, **kwargs: object) -> str:
    return text(lang, en, he, **kwargs)


# --------------------------------------------------------------------------
# Devices: USB storage, camera, Bluetooth (kernel module blacklists)
# --------------------------------------------------------------------------

DEVICE_NAMES = {
    "usb_storage": ("USB storage devices", "התקני אחסון USB"),
    "camera": ("the camera", "המצלמה"),
    "bluetooth": ("Bluetooth", "Bluetooth"),
}


def _device_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"kind"})
    return {"kind": _choice(params.get("kind"), DEVICE_MODULES, "kind")}


def _device_file(params: Params, ctx: Context) -> list[Path]:
    return [ctx.path(f"/etc/modprobe.d/dai-tune-{params['kind']}.conf")]


def _service_enabled(ctx: Context, unit: str) -> bool:
    return ctx.run(["systemctl", "is-enabled", unit], check=False).stdout.strip() == "enabled"


def _bluetooth_capture(params: Params, ctx: Context) -> dict:
    if params["kind"] != "bluetooth":
        return {}
    return {"bluetooth_enabled": _service_enabled(ctx, "bluetooth.service")}


def _set_bluetooth(ctx: Context, on: bool) -> None:
    if on:
        ctx.run(["rfkill", "unblock", "bluetooth"], check=False)
        ctx.run(["systemctl", "enable", "--now", "bluetooth.service"], check=False)
    else:
        ctx.run(["systemctl", "disable", "--now", "bluetooth.service"], check=False)
        ctx.run(["rfkill", "block", "bluetooth"], check=False)


def _device_block_apply(params: Params, ctx: Context) -> None:
    modules = DEVICE_MODULES[params["kind"]]
    lines = ["# Managed by dai-tune. Undo with: dai-tune undo"]
    for module in modules:
        lines += [f"install {module} /bin/false", f"blacklist {module}"]
    write_file(_device_file(params, ctx)[0], "\n".join(lines) + "\n")
    if params["kind"] == "bluetooth":
        _set_bluetooth(ctx, on=False)
    for module in modules:
        ctx.run(["modprobe", "-r", module], check=False)  # may be in use; blacklist still applies


def _device_allow_apply(params: Params, ctx: Context) -> None:
    path = _device_file(params, ctx)[0]
    if path.exists():
        path.unlink()
    if params["kind"] == "bluetooth":
        _set_bluetooth(ctx, on=True)


def _device_restore(params: Params, ctx: Context, extra: dict) -> None:
    if params["kind"] == "bluetooth" and "bluetooth_enabled" in extra:
        _set_bluetooth(ctx, on=extra["bluetooth_enabled"])


def _usb_note(params: Params, lang: str) -> str:
    if params["kind"] == "usb_storage":
        return _t(lang, "Applies to newly connected drives. Do not use if the system itself runs from a USB drive.",
                  "חל על התקנים שיחוברו מעכשיו. אין להפעיל אם המערכת עצמה רצה מכונן USB.")
    return ""


register(ActionSpec(
    id="device.block",
    scope="system",
    validate=_device_validate,
    apply=_device_block_apply,
    risk=lambda p: "low",
    effect=lambda p: "hardens",
    summary=lambda p, lang: _t(lang, "Block {kind}", "חסימת {kind}", kind=_t(lang, *DEVICE_NAMES[p["kind"]])),
    files=_device_file,
    capture=_bluetooth_capture,
    restore=_device_restore,
    note=_usb_note,
))

register(ActionSpec(
    id="device.allow",
    scope="system",
    validate=_device_validate,
    apply=_device_allow_apply,
    risk=lambda p: "medium",
    effect=lambda p: "weakens",
    summary=lambda p, lang: _t(lang, "Allow {kind}", "אפשור {kind}", kind=_t(lang, *DEVICE_NAMES[p["kind"]])),
    files=_device_file,
    capture=_bluetooth_capture,
    restore=_device_restore,
))


# --------------------------------------------------------------------------
# Firewall: managed allow rules included into the default-deny input chain
# --------------------------------------------------------------------------

FW_STATE = "/etc/dai/firewall-allow.json"
FW_RULES = "/etc/dai/firewall-allow.nft"
NFT_CONF = "/etc/nftables.conf"


def load_firewall_rules(ctx: Context) -> list[dict]:
    try:
        rules = json.loads(read_text(ctx.path(FW_STATE), "[]"))
    except json.JSONDecodeError:
        return []
    return [r for r in rules if isinstance(r, dict)]


def render_firewall(rules: list[dict]) -> str:
    lines = ['# Managed by dai-tune. Do not edit; use: dai-tune "close port N"']
    for rule in sorted(rules, key=lambda r: (r["port"], r["proto"], r["source"])):
        port, proto = int(rule["port"]), rule["proto"]
        if rule["source"] == "lan":
            lines.append(f'ip saddr {{ {LAN_V4} }} {proto} dport {port} accept comment "dai-tune lan"')
            lines.append(f'ip6 saddr {{ {LAN_V6} }} {proto} dport {port} accept comment "dai-tune lan"')
        else:
            lines.append(f'{proto} dport {port} accept comment "dai-tune any"')
    return "\n".join(lines) + "\n"


def _fw_validate(params: Params, ctx: Context, closing: bool = False) -> Params:
    _only_keys(params, {"port", "proto", "source"})
    out: Params = {
        "port": _int(params.get("port"), 1, 65535, "port"),
        "proto": _choice(params.get("proto", "tcp"), ("tcp", "udp"), "proto"),
    }
    if not closing:
        out["source"] = _choice(params.get("source", "lan"), ("lan", "any"), "source")
    return out


def _fw_files(params: Params, ctx: Context) -> list[Path]:
    return [ctx.path(FW_STATE), ctx.path(FW_RULES)]


def _fw_write_and_reload(rules: list[dict], ctx: Context) -> None:
    write_file(ctx.path(FW_STATE), json.dumps(rules, indent=2) + "\n")
    write_file(ctx.path(FW_RULES), render_firewall(rules))
    # Validate the complete ruleset before loading it; the executor restores
    # the previous files if either step fails.
    ctx.run(["nft", "-c", "-f", NFT_CONF])
    ctx.run(["nft", "-f", NFT_CONF])


def _fw_open_apply(params: Params, ctx: Context) -> None:
    rules = [r for r in load_firewall_rules(ctx) if (r["port"], r["proto"]) != (params["port"], params["proto"])]
    rules.append(dict(params))
    _fw_write_and_reload(rules, ctx)


def _fw_close_apply(params: Params, ctx: Context) -> None:
    rules = [r for r in load_firewall_rules(ctx) if (r["port"], r["proto"]) != (params["port"], params["proto"])]
    _fw_write_and_reload(rules, ctx)


def _fw_reload(params: Params, ctx: Context, extra: dict) -> None:
    ctx.run(["nft", "-f", NFT_CONF], check=False)


register(ActionSpec(
    id="firewall.open_port",
    scope="system",
    validate=_fw_validate,
    apply=_fw_open_apply,
    risk=lambda p: "high" if p["source"] == "any" else "medium",
    effect=lambda p: "weakens",
    summary=lambda p, lang: (
        _t(lang, "Open port {port}/{proto} to the local network only",
           "פתיחת פורט {port}/{proto} לרשת המקומית בלבד", port=p['port'], proto=p['proto'])
        if p["source"] == "lan" else
        _t(lang, "Open port {port}/{proto} to ANY network (internet)",
           "פתיחת פורט {port}/{proto} לכל הרשתות (אינטרנט)", port=p['port'], proto=p['proto'])
    ),
    files=_fw_files,
    restore=_fw_reload,
    note=lambda p, lang: _t(lang, "Exposes a service on this computer to other machines.",
                            "חושף שירות במחשב הזה למחשבים אחרים.") if p["source"] == "any" else "",
))

register(ActionSpec(
    id="firewall.close_port",
    scope="system",
    validate=lambda p, c: _fw_validate(p, c, closing=True),
    apply=_fw_close_apply,
    risk=lambda p: "low",
    effect=lambda p: "hardens",
    summary=lambda p, lang: _t(lang, "Close port {port}/{proto}", "סגירת פורט {port}/{proto}",
                               port=p['port'], proto=p['proto']),
    files=_fw_files,
    restore=_fw_reload,
))


# --------------------------------------------------------------------------
# Automatic security updates
# --------------------------------------------------------------------------

AUTO_UPGRADES = "/etc/apt/apt.conf.d/20auto-upgrades"


def _updates_apply(params: Params, ctx: Context) -> None:
    flag = "1" if params["enabled"] else "0"
    write_file(ctx.path(AUTO_UPGRADES), (
        "// Managed by dai-tune.\n"
        f'APT::Periodic::Update-Package-Lists "{flag}";\n'
        f'APT::Periodic::Unattended-Upgrade "{flag}";\n'
    ))


register(ActionSpec(
    id="updates.auto",
    scope="system",
    validate=lambda p, c: (_only_keys(p, {"enabled"}), {"enabled": _bool(p.get("enabled"))})[1],
    apply=_updates_apply,
    risk=lambda p: "low" if p["enabled"] else "high",
    effect=lambda p: "hardens" if p["enabled"] else "weakens",
    summary=lambda p, lang: _t(lang, "Turn automatic security updates " + ("on" if p["enabled"] else "off"),
                               "עדכוני אבטחה אוטומטיים: " + ("הפעלה" if p["enabled"] else "כיבוי")),
    files=lambda p, c: [c.path(AUTO_UPGRADES)],
))


# --------------------------------------------------------------------------
# SSH server
# --------------------------------------------------------------------------


def _ssh_apply(params: Params, ctx: Context) -> None:
    if not ctx.path("/usr/sbin/sshd").exists():
        if params["enabled"]:
            raise ActionError("openssh-server is not installed")
        return
    verb = "enable" if params["enabled"] else "disable"
    ctx.run(["systemctl", verb, "--now", "ssh.service"])


def _ssh_capture(params: Params, ctx: Context) -> dict:
    return {"ssh_enabled": _service_enabled(ctx, "ssh.service")}


def _ssh_restore(params: Params, ctx: Context, extra: dict) -> None:
    if ctx.path("/usr/sbin/sshd").exists() and "ssh_enabled" in extra:
        verb = "enable" if extra["ssh_enabled"] else "disable"
        ctx.run(["systemctl", verb, "--now", "ssh.service"], check=False)


register(ActionSpec(
    id="service.ssh",
    scope="system",
    validate=lambda p, c: (_only_keys(p, {"enabled"}), {"enabled": _bool(p.get("enabled"))})[1],
    apply=_ssh_apply,
    risk=lambda p: "medium" if p["enabled"] else "low",
    effect=lambda p: "weakens" if p["enabled"] else "hardens",
    summary=lambda p, lang: _t(lang, "SSH server " + ("on" if p["enabled"] else "off"),
                               "שרת SSH: " + ("הפעלה" if p["enabled"] else "כיבוי")),
    capture=_ssh_capture,
    restore=_ssh_restore,
))


# --------------------------------------------------------------------------
# Packages
# --------------------------------------------------------------------------


def installed_packages(ctx: Context, names: list[str]) -> list[str]:
    found = []
    for name in names:
        out = ctx.run(["dpkg-query", "-W", "-f=${Status}", name], check=False).stdout
        if out.strip().endswith("installed") and "not-installed" not in out:
            found.append(name)
    return found


def _apt(ctx: Context, verb: str, names: list[str]) -> None:
    argv = ["apt-get", verb, "-y", "--no-install-recommends", *names]
    if ctx.run(argv, check=False).returncode != 0:
        ctx.run(["apt-get", "update"])
        ctx.run(argv)


def _install_restore(params: Params, ctx: Context, extra: dict) -> None:
    added = [n for n in params["names"] if n not in extra.get("preinstalled", [])]
    if added:
        ctx.run(["apt-get", "remove", "-y", *added], check=False)


def _remove_apply(params: Params, ctx: Context) -> None:
    ctx.run(["apt-get", "remove", "-y", *params["names"]])


def _remove_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("preinstalled"):
        _apt(ctx, "install", extra["preinstalled"])


register(ActionSpec(
    id="packages.install",
    scope="system",
    validate=lambda p, c: (_only_keys(p, {"names"}), {"names": _packages(p.get("names"), removing=False)})[1],
    apply=lambda p, c: _apt(c, "install", p["names"]),
    risk=lambda p: "medium",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Install: ", "התקנת: ") + ", ".join(p["names"]),
    capture=lambda p, c: {"preinstalled": installed_packages(c, p["names"])},
    restore=_install_restore,
    note=lambda p, lang: _t(lang, "Packages come only from the signed Debian/D.Ai repositories.",
                            "החבילות מגיעות רק ממאגרי Debian/D.Ai החתומים."),
))

register(ActionSpec(
    id="packages.remove",
    scope="system",
    validate=lambda p, c: (_only_keys(p, {"names"}), {"names": _packages(p.get("names"), removing=True)})[1],
    apply=_remove_apply,
    risk=lambda p: "medium",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Remove: ", "הסרת: ") + ", ".join(p["names"]),
    capture=lambda p, c: {"preinstalled": installed_packages(c, p["names"])},
    restore=_remove_restore,
))


# --------------------------------------------------------------------------
# Time zone and host name
# --------------------------------------------------------------------------


def _tz_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"timezone"})
    tz = params.get("timezone")
    if not isinstance(tz, str) or not TIMEZONE_RE.match(tz) or ".." in tz:
        raise ValidationError(f"invalid time zone: {tz!r}")
    if not ctx.path(f"/usr/share/zoneinfo/{tz}").is_file():
        raise ValidationError(f"unknown time zone: {tz}")
    return {"timezone": tz}


def current_timezone(ctx: Context) -> str:
    tz = read_text(ctx.path("/etc/timezone")).strip()
    if tz:
        return tz
    try:
        target = str(ctx.path("/etc/localtime").readlink())
    except OSError:
        return ""
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else ""


def _tz_apply(params: Params, ctx: Context) -> None:
    ctx.run(["timedatectl", "set-timezone", params["timezone"]])


def _tz_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("previous"):
        ctx.run(["timedatectl", "set-timezone", extra["previous"]], check=False)


register(ActionSpec(
    id="system.timezone",
    scope="system",
    validate=_tz_validate,
    apply=_tz_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Set time zone to {timezone}", "אזור זמן: {timezone}",
                               timezone=p['timezone']),
    capture=lambda p, c: {"previous": current_timezone(c)},
    restore=_tz_restore,
))


def _hostname_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"hostname"})
    name = params.get("hostname")
    if not isinstance(name, str) or not HOSTNAME_RE.match(name):
        raise ValidationError(f"invalid computer name: {name!r} (use a-z, 0-9 and -)")
    return {"hostname": name}


def _hostname_apply(params: Params, ctx: Context) -> None:
    ctx.run(["hostnamectl", "set-hostname", params["hostname"]])
    hosts = ctx.path("/etc/hosts")
    lines = [line for line in read_text(hosts).splitlines() if not line.startswith("127.0.1.1")]
    lines.append(f"127.0.1.1\t{params['hostname']}")
    write_file(hosts, "\n".join(lines) + "\n")


def _hostname_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("previous"):
        ctx.run(["hostnamectl", "set-hostname", extra["previous"]], check=False)


register(ActionSpec(
    id="system.hostname",
    scope="system",
    validate=_hostname_validate,
    apply=_hostname_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Rename this computer to {hostname}", "שינוי שם המחשב ל־{hostname}",
                               hostname=p['hostname']),
    files=lambda p, c: [c.path("/etc/hosts")],
    capture=lambda p, c: {"previous": read_text(c.path("/etc/hostname")).strip()},
    restore=_hostname_restore,
))


# --------------------------------------------------------------------------
# User session: screen lock and keyboard layouts
# --------------------------------------------------------------------------

SESSION_ENV = ".config/dai/session.env"
LABWC_ENV = ".config/labwc/environment"


def update_env_file(path: Path, updates: dict[str, str], mode: int = 0o600) -> None:
    """Set KEY=VALUE lines, keeping every other line as it was."""
    lines = read_text(path).splitlines()
    pending = dict(updates)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    write_file(path, "\n".join(lines) + "\n", mode=mode)


def _env_seconds(path: Path, key: str) -> int | None:
    for line in read_text(path).splitlines():
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip()
            if value.isdigit():
                return int(value)
    return None


# Set by an organization policy for every user (docs/EDU.md §2); read by the labwc autostart.
POLICY_SESSION_ENV = "/etc/dai/policy-session.env"


def policy_lock_max_seconds(ctx: Context) -> int:
    """The longest screen-lock delay a policy allows (0: no policy)."""
    return _env_seconds(ctx.path(POLICY_SESSION_ENV), "DAI_LOCK_MAX_SECONDS") or 0


def lock_timeout_seconds(ctx: Context) -> int:
    """The delay the session really uses: the user's choice, capped by a policy (as in the autostart)."""
    seconds = _env_seconds(ctx.user_path(SESSION_ENV), "DAI_LOCK_TIMEOUT_SECONDS")
    seconds = 600 if seconds is None else seconds  # default in /etc/skel autostart
    limit = policy_lock_max_seconds(ctx)
    if limit and (seconds == 0 or seconds > limit):
        return limit
    return seconds


def _lock_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"minutes"})
    minutes = _int(params.get("minutes"), 0, 120, "minutes")
    limit = policy_lock_max_seconds(ctx)
    if limit and (minutes == 0 or minutes * 60 > limit):
        raise ValidationError(f"your organization's policy locks the screen after at most {limit // 60} minutes")
    return {"minutes": minutes}


def _lock_apply(params: Params, ctx: Context) -> None:
    seconds = params["minutes"] * 60
    update_env_file(ctx.user_path(SESSION_ENV), {"DAI_LOCK_TIMEOUT_SECONDS": str(seconds)})
    _restart_idle(ctx, seconds)


def _restart_idle(ctx: Context, seconds: int) -> None:
    ctx.run(["pkill", "-u", str(_uid(ctx)), "-x", "swayidle"], check=False)
    if seconds > 0:
        ctx.spawner(["swayidle", "-w", "timeout", str(seconds), "swaylock -f", "before-sleep", "swaylock -f"])


def _uid(ctx: Context) -> int:
    try:
        return ctx.home.stat().st_uid
    except OSError:
        return 0


def _lock_effect(params: Params) -> str:
    minutes = params["minutes"]
    if minutes == 0 or minutes > 15:
        return "weakens"
    return "hardens" if minutes <= 10 else "neutral"


register(ActionSpec(
    id="session.lock",
    scope="user",
    validate=_lock_validate,
    apply=_lock_apply,
    risk=lambda p: "medium" if p["minutes"] == 0 else "low",
    effect=_lock_effect,
    summary=lambda p, lang: (
        _t(lang, "Never lock the screen automatically", "ביטול נעילת מסך אוטומטית") if p["minutes"] == 0 else
        _t(lang, "Lock the screen after {minutes} minutes of inactivity", "נעילת מסך אחרי {minutes} דקות ללא פעילות",
           minutes=p['minutes'])
    ),
    files=lambda p, c: [c.user_path(SESSION_ENV)],
    restore=lambda p, c, e: _restart_idle(c, lock_timeout_seconds(c)),
))


def _lock_max_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"minutes"})
    minutes = _int(params.get("minutes"), 0, 120, "minutes")
    if minutes == 0:
        raise ValidationError("a policy can require a screen lock, not turn it off")
    return {"minutes": minutes}


def _lock_max_apply(params: Params, ctx: Context) -> None:
    # Readable by every user's session (0644); only root can change it.
    update_env_file(ctx.path(POLICY_SESSION_ENV), {"DAI_LOCK_MAX_SECONDS": str(params["minutes"] * 60)}, mode=0o644)


# Not parsed from text: an organization policy turns "lock the screen after N minutes" into this.
register(ActionSpec(
    id="session.lock_max",
    scope="system",
    validate=_lock_max_validate,
    apply=_lock_max_apply,
    risk=lambda p: "low",
    effect=lambda p: "hardens" if p["minutes"] <= 10 else "neutral",
    summary=lambda p, lang: _t(lang, "Every user: the screen locks after at most {minutes} minutes",
                               "לכל המשתמשים: המסך ננעל אחרי {minutes} דקות לכל היותר", minutes=p['minutes']),
    files=lambda p, c: [c.path(POLICY_SESSION_ENV)],
    note=lambda p, lang: _t(lang, "Takes effect at each user's next login. Users can choose a shorter time, not a longer one.",
                            "חל מהכניסה הבאה של כל משתמש. משתמשים יכולים לבחור זמן קצר יותר, לא ארוך יותר."),
))


def _layouts_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"layouts"})
    layouts = params.get("layouts")
    if not isinstance(layouts, list) or not 1 <= len(layouts) <= 4:
        raise ValidationError("layouts: 1-4 keyboard layouts")
    clean: list[str] = []
    for layout in layouts:
        _choice(layout, KEYBOARD_LAYOUTS, "layout")
        if layout not in clean:
            clean.append(layout)
    return {"layouts": clean}


LANG_STATE = ".config/labwc/environment.d/50-dai-lang.env"


def _layouts_apply(params: Params, ctx: Context) -> None:
    # dai-lang switches between DAI_LAYOUTS with Alt+Shift; start on the first.
    first = params["layouts"][0]
    update_env_file(ctx.user_path(LABWC_ENV), {
        "DAI_LAYOUTS": ",".join(params["layouts"]),
        "XKB_DEFAULT_LAYOUT": first,
    })
    write_file(ctx.user_path(LANG_STATE), f"XKB_DEFAULT_LAYOUT={first}\n", mode=0o600)
    _reconfigure_labwc(ctx)


def _reconfigure_labwc(ctx: Context) -> None:
    ctx.run(["labwc", "--reconfigure"], check=False)


register(ActionSpec(
    id="keyboard.layouts",
    scope="user",
    validate=_layouts_validate,
    apply=_layouts_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Keyboard layouts: ", "שפות מקלדת: ") + ", ".join(p["layouts"]) + " (Alt+Shift)",
    files=lambda p, c: [c.user_path(LABWC_ENV), c.user_path(LANG_STATE)],
    restore=lambda p, c, e: _reconfigure_labwc(c),
))


# --------------------------------------------------------------------------
# Services (used by D.Ai Forge recipes)
# --------------------------------------------------------------------------

UNIT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}(?:@[a-z0-9._-]{1,40})?\.(?:service|timer|socket|path)$")
# Core units a recipe may never switch: the firewall, confinement, the
# session, authentication and the network. SSH has its own action.
PROTECTED_UNITS = re.compile(
    r"^(?:nftables|apparmor|systemd-.*|sddm|display-manager|dbus.*|polkit.*|NetworkManager.*|networkmanager.*|"
    r"ssh|sshd|ssh@.*|getty@.*|serial-getty@.*|user@.*|unattended-upgrades|apt-daily.*|dai-.*|cron|rsyslog|"
    r"auditd|zramswap|udisks2|accounts-daemon|rtkit-daemon)\.(?:service|timer|socket|path)$"
)
SYSTEM_UNIT_DIRS = ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")
USER_UNIT_DIRS = ("/usr/lib/systemd/user", "/lib/systemd/user")


def _unit_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"unit", "enabled"})
    unit = params.get("unit")
    if not isinstance(unit, str) or not UNIT_RE.match(unit):
        raise ValidationError(f"invalid unit name: {unit!r}")
    if PROTECTED_UNITS.match(unit):
        raise ValidationError(f"refusing to change protected unit: {unit}")
    # Existence is checked when applying: the unit usually comes from a
    # package installed by an earlier step of the same plan.
    return {"unit": unit, "enabled": _bool(params.get("enabled"))}


def _unit_installed(ctx: Context, unit: str, dirs: tuple[str, ...]) -> bool:
    template = re.sub(r"@[^.]+\.", "@.", unit)
    return any(ctx.path(f"{d}/{name}").exists() for d in dirs for name in {unit, template})


def _systemctl(user: bool) -> list[str]:
    return ["systemctl", "--user"] if user else ["systemctl"]


def _unit_state(ctx: Context, unit: str, user: bool) -> dict:
    out = ctx.run([*_systemctl(user), "is-enabled", unit], check=False).stdout.strip()
    return {"was_enabled": out in ("enabled", "enabled-runtime", "static", "alias")}


def _unit_apply(params: Params, ctx: Context, user: bool) -> None:
    dirs = USER_UNIT_DIRS if user else SYSTEM_UNIT_DIRS
    if not _unit_installed(ctx, params["unit"], dirs):
        raise ActionError(f"{params['unit']} is not installed")
    verb = "enable" if params["enabled"] else "disable"
    ctx.run([*_systemctl(user), verb, "--now", params["unit"]])


def _unit_restore(params: Params, ctx: Context, extra: dict, user: bool) -> None:
    if "was_enabled" not in extra:
        return
    verb = "enable" if extra["was_enabled"] else "disable"
    ctx.run([*_systemctl(user), verb, "--now", params["unit"]], check=False)


def _unit_summary(params: Params, lang: str, user: bool) -> str:
    where = _t(lang, " (your session)", " (בסשן שלך)") if user else ""
    if params["enabled"]:
        return _t(lang, "Start and enable {unit}", "הפעלת השירות {unit}", unit=params['unit']) + where
    return _t(lang, "Stop and disable {unit}", "כיבוי השירות {unit}", unit=params['unit']) + where


# Restarting these would end the desktop session or the system bus: never offered.
NO_RESTART = re.compile(r"^(?:sddm|display-manager|dbus.*|systemd-logind|user@.*|getty@.*|serial-getty@.*|"
                        r"systemd-journald|polkit)\.service$")


def _restart_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"unit"})
    unit = params.get("unit")
    if isinstance(unit, str) and "." not in unit:
        unit += ".service"
    if not isinstance(unit, str) or not UNIT_RE.match(unit) or not unit.endswith(".service"):
        raise ValidationError(f"invalid service name: {unit!r}")
    if NO_RESTART.match(unit):
        raise ValidationError(f"restarting {unit} would end the session; restart the computer instead")
    return {"unit": unit}


def _restart_apply(params: Params, ctx: Context) -> None:
    if not _unit_installed(ctx, params["unit"], SYSTEM_UNIT_DIRS):
        raise ActionError(f"{params['unit']} is not installed")
    ctx.run(["systemctl", "reset-failed", params["unit"]], check=False)
    ctx.run(["systemctl", "restart", params["unit"]])


# D.Ai Heal offers this for a failed service (docs/EVOLVE.md §4). Nothing to undo.
register(ActionSpec(
    id="service.restart",
    scope="system",
    validate=_restart_validate,
    apply=_restart_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Restart the service {unit}", "הפעלה מחדש של השירות {unit}",
                               unit=p['unit']),
))


register(ActionSpec(
    id="service.unit",
    scope="system",
    validate=_unit_validate,
    apply=lambda p, c: _unit_apply(p, c, user=False),
    risk=lambda p: "medium",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _unit_summary(p, lang, user=False),
    capture=lambda p, c: _unit_state(c, p["unit"], user=False),
    restore=lambda p, c, e: _unit_restore(p, c, e, user=False),
))

register(ActionSpec(
    id="service.user_unit",
    scope="user",
    validate=_unit_validate,
    apply=lambda p, c: _unit_apply(p, c, user=True),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _unit_summary(p, lang, user=True),
    capture=lambda p, c: _unit_state(c, p["unit"], user=True),
    restore=lambda p, c, e: _unit_restore(p, c, e, user=True),
))


# --------------------------------------------------------------------------
# Flatpak (Flathub only; the remote URL is fixed here, never taken from input)
# --------------------------------------------------------------------------

FLATPAK_REMOTES = {"flathub": "https://dl.flathub.org/repo/flathub.flatpakrepo"}
FLATPAK_APP_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+){2,6}$")
MAX_FLATPAKS = 5


def _flatpak_remotes(ctx: Context) -> list[str]:
    out = ctx.run(["flatpak", "remotes", "--system", "--columns=name"], check=False).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _flatpak_apps_installed(ctx: Context, apps: list[str]) -> list[str]:
    out = ctx.run(["flatpak", "list", "--system", "--app", "--columns=application"], check=False).stdout
    present = {line.strip() for line in out.splitlines()}
    return [app for app in apps if app in present]


def _remote_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name"})
    return {"name": _choice(params.get("name", "flathub"), tuple(FLATPAK_REMOTES), "remote")}


def _remote_apply(params: Params, ctx: Context) -> None:
    name = params["name"]
    ctx.run(["flatpak", "remote-add", "--system", "--if-not-exists", name, FLATPAK_REMOTES[name]])


def _remote_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("existed") is False:
        ctx.run(["flatpak", "remote-delete", "--system", "--force", params["name"]], check=False)


register(ActionSpec(
    id="flatpak.remote",
    scope="system",
    validate=_remote_validate,
    apply=_remote_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Add the Flathub app store", "הוספת חנות האפליקציות Flathub"),
    capture=lambda p, c: {"existed": p["name"] in _flatpak_remotes(c)},
    restore=_remote_restore,
    note=lambda p, lang: _t(lang, "Flathub apps run sandboxed and update through Flatpak.",
                            "אפליקציות Flathub רצות בארגז חול ומתעדכנות דרך Flatpak."),
))


def _flatpak_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"apps", "remote"})
    apps = params.get("apps")
    if not isinstance(apps, list) or not 1 <= len(apps) <= MAX_FLATPAKS:
        raise ValidationError(f"apps: 1-{MAX_FLATPAKS} Flatpak application ids")
    clean: list[str] = []
    for app in apps:
        if not isinstance(app, str) or not FLATPAK_APP_RE.match(app):
            raise ValidationError(f"invalid Flatpak id: {app!r}")
        if app not in clean:
            clean.append(app)
    return {"apps": clean, "remote": _choice(params.get("remote", "flathub"), tuple(FLATPAK_REMOTES), "remote")}


def _flatpak_install_restore(params: Params, ctx: Context, extra: dict) -> None:
    added = [a for a in params["apps"] if a not in extra.get("preinstalled", [])]
    if added:
        ctx.run(["flatpak", "uninstall", "--system", "-y", "--noninteractive", *added], check=False)


def _flatpak_remove_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("preinstalled"):
        ctx.run(["flatpak", "install", "--system", "-y", "--noninteractive", params["remote"], *extra["preinstalled"]],
                check=False)


register(ActionSpec(
    id="flatpak.install",
    scope="system",
    validate=_flatpak_validate,
    apply=lambda p, c: c.run(["flatpak", "install", "--system", "-y", "--noninteractive", p["remote"], *p["apps"]]),
    risk=lambda p: "medium",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Install from Flathub: ", "התקנה מ־Flathub: ") + ", ".join(p["apps"]),
    capture=lambda p, c: {"preinstalled": _flatpak_apps_installed(c, p["apps"])},
    restore=_flatpak_install_restore,
))

register(ActionSpec(
    id="flatpak.remove",
    scope="system",
    validate=_flatpak_validate,
    apply=lambda p, c: c.run(["flatpak", "uninstall", "--system", "-y", "--noninteractive", *p["apps"]]),
    risk=lambda p: "medium",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Remove Flatpak apps: ", "הסרת אפליקציות Flatpak: ") + ", ".join(p["apps"]),
    capture=lambda p, c: {"preinstalled": _flatpak_apps_installed(c, p["apps"])},
    restore=_flatpak_remove_restore,
))


# --------------------------------------------------------------------------
# Antivirus: scheduled ClamAV scan of /home with quarantine
# --------------------------------------------------------------------------

AV_SERVICE = "/etc/systemd/system/dai-av-scan.service"
AV_TIMER = "/etc/systemd/system/dai-av-scan.timer"
AV_QUARANTINE = "/var/lib/dai/quarantine"
AV_LOG = "/var/log/dai-av-scan.log"


def render_av_service() -> str:
    return (
        "# Managed by dai-tune (D.Ai Forge antivirus recipe). Undo with: dai-tune undo\n"
        "[Unit]\n"
        "Description=D.Ai antivirus scan of /home (ClamAV)\n"
        "Documentation=https://github.com/diamondrubinny/D.Ai/blob/main/docs/FORGE.md\n"
        "After=clamav-freshclam.service\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart=/usr/bin/clamscan --recursive --infected --move={AV_QUARANTINE} "
        f"--exclude-dir=^{AV_QUARANTINE} --log={AV_LOG} /home\n"
        "# clamscan exits 1 when it found (and quarantined) infected files.\n"
        "SuccessExitStatus=1\n"
        "Nice=19\n"
        "IOSchedulingClass=idle\n"
        "CPUSchedulingPolicy=idle\n"
        "NoNewPrivileges=yes\n"
        "PrivateNetwork=yes\n"
        "PrivateTmp=yes\n"
        "PrivateDevices=yes\n"
        "ProtectSystem=strict\n"
        f"ReadWritePaths=/home {AV_QUARANTINE} /var/log\n"
        "ProtectKernelTunables=yes\n"
        "ProtectKernelModules=yes\n"
        "ProtectControlGroups=yes\n"
        "RestrictRealtime=yes\n"
        "LockPersonality=yes\n"
    )


def render_av_timer(frequency: str) -> str:
    return (
        "# Managed by dai-tune (D.Ai Forge antivirus recipe). Undo with: dai-tune undo\n"
        "[Unit]\n"
        "Description=Scheduled D.Ai antivirus scan\n\n"
        "[Timer]\n"
        f"OnCalendar={frequency}\n"
        "Persistent=true\n"
        "RandomizedDelaySec=30min\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _av_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"enabled", "frequency"})
    return {
        "enabled": _bool(params.get("enabled", True)),
        "frequency": _choice(params.get("frequency", "daily"), ("daily", "weekly"), "frequency"),
    }


def _av_apply(params: Params, ctx: Context) -> None:
    if params["enabled"]:
        if not ctx.path("/usr/bin/clamscan").exists():
            raise ActionError("ClamAV is not installed (clamscan missing)")
        quarantine = ctx.path(AV_QUARANTINE)
        quarantine.mkdir(parents=True, exist_ok=True)
        quarantine.chmod(0o700)
        write_file(ctx.path(AV_SERVICE), render_av_service())
        write_file(ctx.path(AV_TIMER), render_av_timer(params["frequency"]))
        ctx.run(["systemctl", "daemon-reload"])
        ctx.run(["systemctl", "enable", "--now", "dai-av-scan.timer"])
    else:
        ctx.run(["systemctl", "disable", "--now", "dai-av-scan.timer"], check=False)
        for name in (AV_TIMER, AV_SERVICE):
            path = ctx.path(name)
            if path.exists():
                path.unlink()
        ctx.run(["systemctl", "daemon-reload"], check=False)


def _av_restore(params: Params, ctx: Context, extra: dict) -> None:
    # Unit files were already restored from the snapshot.
    ctx.run(["systemctl", "daemon-reload"], check=False)
    verb = "enable" if extra.get("was_enabled") else "disable"
    if extra.get("was_enabled") or params["enabled"]:
        ctx.run(["systemctl", verb, "--now", "dai-av-scan.timer"], check=False)


register(ActionSpec(
    id="antivirus.schedule",
    scope="system",
    validate=_av_validate,
    apply=_av_apply,
    risk=lambda p: "low" if p["enabled"] else "medium",
    effect=lambda p: "hardens" if p["enabled"] else "weakens",
    summary=lambda p, lang: (
        _t(lang, "Scan /home for viruses ({frequency}) and quarantine infected files",
           "סריקת וירוסים ל־/home ({daily}) והעברת קבצים נגועים להסגר",
           frequency=p['frequency'], daily='יומית' if p['frequency'] == 'daily' else 'שבועית')
        if p["enabled"] else
        _t(lang, "Stop scheduled virus scans", "הפסקת סריקות וירוסים מתוזמנות")
    ),
    files=lambda p, c: [c.path(AV_SERVICE), c.path(AV_TIMER)],
    capture=lambda p, c: _unit_state(c, "dai-av-scan.timer", user=False),
    restore=_av_restore,
    note=lambda p, lang: _t(lang, "Quarantine: {AV_QUARANTINE} (root only). Log: {AV_LOG}",
                            "הסגר: {AV_QUARANTINE} (root בלבד). יומן: {AV_LOG}",
                            AV_QUARANTINE=AV_QUARANTINE, AV_LOG=AV_LOG) if p["enabled"] else "",
))


# --------------------------------------------------------------------------
# Maintenance: free disk space taken by caches (D.Ai Doctor)
# --------------------------------------------------------------------------

JOURNAL_KEEP = "200M"


def _clean_apply(params: Params, ctx: Context) -> None:
    ctx.run(["apt-get", "clean"])
    if ctx.path("/var/log/journal").is_dir():
        ctx.run(["journalctl", f"--vacuum-size={JOURNAL_KEEP}"])


register(ActionSpec(
    id="system.clean",
    scope="system",
    validate=lambda p, c: (_only_keys(p, set()), {})[1],
    apply=_clean_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Free disk space: downloaded package files and old system logs",
                               "פינוי מקום: קבצי התקנה שהורדו ויומני מערכת ישנים"),
    # Only caches are removed: packages stay installed and recent logs are kept.
    note=lambda p, lang: _t(lang, "Cannot be undone, but nothing you use is lost (logs over {JOURNAL_KEEP} only).",
                            "אי אפשר לבטל, אבל שום דבר שאתם משתמשים בו לא נמחק (רק יומנים מעבר ל־{JOURNAL_KEEP}).",
                            JOURNAL_KEEP=JOURNAL_KEEP),
))


# --------------------------------------------------------------------------
# Power profile (power-profiles-daemon): battery saver / balanced / performance
# --------------------------------------------------------------------------

POWER_PROFILES = ("power-saver", "balanced", "performance")


def current_power_profile(ctx: Context) -> str:
    result = ctx.run(["powerprofilesctl", "get"], check=False)
    value = result.stdout.strip()
    return value if value in POWER_PROFILES else ""


def _power_apply(params: Params, ctx: Context) -> None:
    if not ctx.path("/usr/bin/powerprofilesctl").exists():
        raise ActionError("power-profiles-daemon is not installed")
    ctx.run(["powerprofilesctl", "set", params["profile"]])


def _power_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("profile") in POWER_PROFILES:
        ctx.run(["powerprofilesctl", "set", extra["profile"]])


register(ActionSpec(
    id="power.profile",
    scope="user",  # power-profiles-daemon lets the active local user switch profiles
    validate=lambda p, c: (_only_keys(p, {"profile"}),
                           {"profile": _choice(p.get("profile"), POWER_PROFILES, "profile")})[1],
    apply=_power_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: {
        "power-saver": _t(lang, "Battery saver mode (longer battery life, a bit slower)",
                          "מצב חיסכון בסוללה (סוללה ארוכה יותר, קצת יותר איטי)"),
        "balanced": _t(lang, "Balanced power mode", "מצב צריכת חשמל מאוזן"),
        "performance": _t(lang, "Performance mode (faster, uses more power)", "מצב ביצועים (מהיר יותר, צורך יותר חשמל)"),
    }[p["profile"]],
    capture=lambda p, c: {"profile": current_power_profile(c)},
    restore=_power_restore,
))


# --------------------------------------------------------------------------
# Snapshots before updates (docs/SNAPSHOTS.md): snapper on a Btrfs system disk
# --------------------------------------------------------------------------


def _snap_enable_restore(params: Params, ctx: Context, extra: dict) -> None:
    from . import snapshots

    if not extra.get("existed"):
        snapshots.disable(ctx)


register(ActionSpec(
    id="snapshots.enable",
    scope="system",
    validate=lambda p, c: (_only_keys(p, set()), {})[1],
    apply=lambda p, c: __import__("dai_tune.snapshots", fromlist=["enable"]).enable(c),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Take a snapshot of the system before every software update",
                               "צילום מצב של המערכת לפני כל עדכון תוכנה"),
    capture=lambda p, c: {"existed": __import__("dai_tune.snapshots", fromlist=["enabled"]).enabled(c)},
    restore=_snap_enable_restore,
    note=lambda p, lang: _t(lang, "Needs a Btrfs system disk. Your personal files (/home) are not part of it. "
                                  "Up to 10 snapshots are kept.",
                            "דורש דיסק מערכת מסוג Btrfs. הקבצים האישיים (/home) לא חלק מזה. נשמרות עד 10 תמונות מצב."),
))


def _undo_update_capture(params: Params, ctx: Context) -> dict:
    from . import snapshots

    # Taken before anything changes, so this undo can itself be undone.
    return {"safety": snapshots.create_safety(ctx)}


def _undo_update_restore(params: Params, ctx: Context, extra: dict) -> None:
    from . import snapshots

    if isinstance(extra.get("safety"), int):
        snapshots.back_to(ctx, extra["safety"])


register(ActionSpec(
    id="snapshots.undo_update",
    scope="system",
    validate=lambda p, c: (_only_keys(p, set()), {})[1],
    apply=lambda p, c: __import__("dai_tune.snapshots", fromlist=["undo_update"]).undo_update(c),
    risk=lambda p: "high",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Undo the last software update (system files go back to before it)",
                               "ביטול העדכון האחרון (קבצי המערכת חוזרים למצב שלפניו)"),
    capture=_undo_update_capture,
    restore=_undo_update_restore,
    note=lambda p, lang: _t(lang, "Restart afterwards. Personal files are not touched. "
                                  "A snapshot of now is taken first, so this can be undone too.",
                            "אחר כך מפעילים מחדש. הקבצים האישיים לא משתנים. "
                            "לפני כן נשמרת תמונת מצב של עכשיו, כך שאפשר לבטל גם את זה."),
))
