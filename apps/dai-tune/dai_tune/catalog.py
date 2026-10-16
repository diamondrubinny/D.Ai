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


def _t(lang: str, en: str, he: str) -> str:
    return he if lang == "he" else en


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
    summary=lambda p, lang: _t(lang, f"Block {DEVICE_NAMES[p['kind']][0]}", f"חסימת {DEVICE_NAMES[p['kind']][1]}"),
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
    summary=lambda p, lang: _t(lang, f"Allow {DEVICE_NAMES[p['kind']][0]}", f"אפשור {DEVICE_NAMES[p['kind']][1]}"),
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
        _t(lang, f"Open port {p['port']}/{p['proto']} to the local network only",
           f"פתיחת פורט {p['port']}/{p['proto']} לרשת המקומית בלבד")
        if p["source"] == "lan" else
        _t(lang, f"Open port {p['port']}/{p['proto']} to ANY network (internet)",
           f"פתיחת פורט {p['port']}/{p['proto']} לכל הרשתות (אינטרנט)")
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
    summary=lambda p, lang: _t(lang, f"Close port {p['port']}/{p['proto']}", f"סגירת פורט {p['port']}/{p['proto']}"),
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
    summary=lambda p, lang: _t(lang, f"Set time zone to {p['timezone']}", f"אזור זמן: {p['timezone']}"),
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
    summary=lambda p, lang: _t(lang, f"Rename this computer to {p['hostname']}", f"שינוי שם המחשב ל־{p['hostname']}"),
    files=lambda p, c: [c.path("/etc/hosts")],
    capture=lambda p, c: {"previous": read_text(c.path("/etc/hostname")).strip()},
    restore=_hostname_restore,
))


# --------------------------------------------------------------------------
# User session: screen lock and keyboard layouts
# --------------------------------------------------------------------------

SESSION_ENV = ".config/dai/session.env"
LABWC_ENV = ".config/labwc/environment"


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Set KEY=VALUE lines, keeping every other line as it was."""
    lines = read_text(path).splitlines()
    pending = dict(updates)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    write_file(path, "\n".join(lines) + "\n", mode=0o600)


def lock_timeout_seconds(ctx: Context) -> int:
    for line in read_text(ctx.user_path(SESSION_ENV)).splitlines():
        if line.startswith("DAI_LOCK_TIMEOUT_SECONDS="):
            value = line.split("=", 1)[1].strip()
            if value.isdigit():
                return int(value)
    return 600  # default in /etc/skel autostart


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
    validate=lambda p, c: (_only_keys(p, {"minutes"}), {"minutes": _int(p.get("minutes"), 0, 120, "minutes")})[1],
    apply=_lock_apply,
    risk=lambda p: "medium" if p["minutes"] == 0 else "low",
    effect=_lock_effect,
    summary=lambda p, lang: (
        _t(lang, "Never lock the screen automatically", "ביטול נעילת מסך אוטומטית") if p["minutes"] == 0 else
        _t(lang, f"Lock the screen after {p['minutes']} minutes of inactivity", f"נעילת מסך אחרי {p['minutes']} דקות ללא פעילות")
    ),
    files=lambda p, c: [c.user_path(SESSION_ENV)],
    restore=lambda p, c, e: _restart_idle(c, lock_timeout_seconds(c)),
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


def _layouts_apply(params: Params, ctx: Context) -> None:
    update_env_file(ctx.user_path(LABWC_ENV), {
        "XKB_DEFAULT_LAYOUT": ",".join(params["layouts"]),
        "XKB_DEFAULT_OPTIONS": "grp:alt_shift_toggle",
    })
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
    files=lambda p, c: [c.user_path(LABWC_ENV)],
    restore=lambda p, c, e: _reconfigure_labwc(c),
))
