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

from dai_i18n import pick, text

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
# xkb layout names (/usr/share/X11/xkb/symbols): Arabic is "ara"; "ar" is accepted and means "ara".
KEYBOARD_LAYOUTS = ("us", "il", "ru", "ara", "fr", "de", "es", "it", "ua", "pt", "br")
LAYOUT_ALIASES = {"ar": "ara"}
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
# Virtual machines: this user's access to /dev/kvm (D.Ai VM, docs/VM.md)
# --------------------------------------------------------------------------

USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def _kvm_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"user", "enabled"})
    user = str(params.get("user") or "")
    if not USER_RE.match(user) or user == "root":
        raise ValidationError("a user name is needed")
    return {"user": user, "enabled": _bool(params.get("enabled", True))}


def _kvm_groups(ctx: Context, user: str) -> list[str]:
    result = ctx.run(["id", "-nG", user], check=False)
    return (result.stdout or "").split()


def _kvm_capture(params: Params, ctx: Context) -> dict:
    return {"was_in_kvm": "kvm" in _kvm_groups(ctx, params["user"])}


def _kvm_apply(params: Params, ctx: Context) -> None:
    if params["enabled"]:
        ctx.run(["usermod", "-aG", "kvm", params["user"]])
    else:
        ctx.run(["gpasswd", "-d", params["user"], "kvm"], check=False)


def _kvm_restore(params: Params, ctx: Context, extra: dict) -> None:
    if extra.get("was_in_kvm"):
        ctx.run(["usermod", "-aG", "kvm", params["user"]], check=False)
    else:
        ctx.run(["gpasswd", "-d", params["user"], "kvm"], check=False)


register(ActionSpec(
    id="vm.kvm_access",
    scope="system",
    validate=_kvm_validate,
    apply=_kvm_apply,
    risk=lambda p: "medium" if p["enabled"] else "low",
    effect=lambda p: "weakens" if p["enabled"] else "hardens",
    summary=lambda p, lang: (_t(lang, "Let {user} run virtual machines (KVM)", "לאפשר ל-{user} להריץ מכונות וירטואליות (KVM)", user=p["user"])
                             if p["enabled"] else
                             _t(lang, "Take KVM access from {user}", "להסיר מ-{user} את הגישה ל-KVM", user=p["user"])),
    capture=_kvm_capture,
    restore=_kvm_restore,
    note=lambda p, lang: _t(lang, "Takes effect at the next login.", "נכנס לתוקף בכניסה הבאה.") if p["enabled"] else "",
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


def port_span(value: Any) -> tuple[int, int]:
    """A port (8080) or a range ("1714-1764") as (low, high); ValidationError otherwise."""
    if isinstance(value, str) and "-" in value:
        low, _, high = value.partition("-")
        lo, hi = _int(low.strip(), 1, 65535, "port"), _int(high.strip(), 1, 65535, "port")
        if hi <= lo:
            raise ValidationError("port: a range goes from the lower port to the higher one")
        return lo, hi
    one = _int(value, 1, 65535, "port")
    return one, one


def port_text(value: Any) -> str:
    lo, hi = port_span(value)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def render_firewall(rules: list[dict]) -> str:
    lines = ['# Managed by dai-tune. Do not edit; use: dai-tune "close port N"']
    for rule in sorted(rules, key=lambda r: (port_span(r["port"]), r["proto"], r["source"])):
        port, proto = port_text(rule["port"]), rule["proto"]
        if rule["source"] == "lan":
            lines.append(f'ip saddr {{ {LAN_V4} }} {proto} dport {port} accept comment "dai-tune lan"')
            lines.append(f'ip6 saddr {{ {LAN_V6} }} {proto} dport {port} accept comment "dai-tune lan"')
        else:
            lines.append(f'{proto} dport {port} accept comment "dai-tune any"')
    return "\n".join(lines) + "\n"


def _fw_validate(params: Params, ctx: Context, closing: bool = False) -> Params:
    _only_keys(params, {"port", "proto", "source"})
    out: Params = {
        "port": _port_param(params.get("port")),
        "proto": _choice(params.get("proto", "tcp"), ("tcp", "udp"), "proto"),
    }
    if not closing:
        out["source"] = _choice(params.get("source", "lan"), ("lan", "any"), "source")
    return out


def _port_param(value: Any) -> int | str:
    """A single port stays an int (older journals and recipes), a range becomes "low-high"."""
    lo, hi = port_span(value)
    return lo if lo == hi else f"{lo}-{hi}"


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
# Set by an organization policy (docs/PROVIDERS.md §4c): external AI providers forbidden for every user.
POLICY_AI_ENV = "/etc/dai/policy-ai.env"


def policy_forbids_providers(ctx: Context) -> bool:
    for line in read_text(ctx.path(POLICY_AI_ENV)).splitlines():
        if line.strip() == "DAI_AI_PROVIDERS=forbidden":
            return True
    return False


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
        layout = LAYOUT_ALIASES.get(layout, layout)
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
# Appearance: the D.Ai theme (docs/V2.md D1b), read by dai_style in every D.Ai window
# --------------------------------------------------------------------------

THEME_FILE = ".config/dai/theme"
THEME_NAMES = {"night": ("dark (D.Ai Night)", "כהה (D.Ai Night)"), "day": ("light (D.Ai Day)", "בהירה (D.Ai Day)"),
               "contrast": ("high contrast", "ניגודיות גבוהה")}


def _theme_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"theme"})
    return {"theme": _choice(params.get("theme"), tuple(THEME_NAMES), "theme")}


register(ActionSpec(
    id="appearance.theme",
    scope="user",
    validate=_theme_validate,
    apply=lambda p, c: write_file(c.user_path(THEME_FILE), p["theme"] + "\n", mode=0o600),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "D.Ai theme: {name}", "ערכת הנושא של D.Ai: {name}",
                               name=pick(lang, *THEME_NAMES[p["theme"]])),
    files=lambda p, c: [c.user_path(THEME_FILE)],
    note=lambda p, lang: _t(lang, "Each D.Ai window takes it the next time it opens.",
                            "כל חלון של D.Ai יקבל אותה בפעם הבאה שייפתח."),
))


# The touch profile (docs/MOBILE.md A1), read by dai_style.touch(): on, off, or auto (a touch screen decides).
TOUCH_FILE = ".config/dai/touch"
TOUCH_NAMES = {"on": ("on", "פועל"), "off": ("off", "כבוי"), "auto": ("automatic: on when a touch screen is attached",
                                                                      "אוטומטי: פועל כשמחובר מסך מגע")}


def _touch_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"mode"})
    return {"mode": _choice(params.get("mode"), tuple(TOUCH_NAMES), "mode")}


register(ActionSpec(
    id="appearance.touch",
    scope="user",
    validate=_touch_validate,
    apply=lambda p, c: write_file(c.user_path(TOUCH_FILE), p["mode"] + "\n", mode=0o600),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Touch mode (big targets, on-screen keyboard): {name}",
                               "מצב מגע (יעדים גדולים, מקלדת על המסך): {name}", name=pick(lang, *TOUCH_NAMES[p["mode"]])),
    files=lambda p, c: [c.user_path(TOUCH_FILE)],
    note=lambda p, lang: _t(lang, "Each D.Ai window takes it the next time it opens; the keyboard at the next login.",
                            "כל חלון של D.Ai יקבל אותו בפעם הבאה שייפתח; המקלדת בכניסה הבאה."),
))


# --------------------------------------------------------------------------
# D.Ai VM (docs/VM.md stage 3): the machines by sentence, through dai-vm as the person
# --------------------------------------------------------------------------

MACHINES_DIR = ".local/share/dai/vm/machines"
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")


def _machines(ctx: Context) -> list[str]:
    folder = ctx.user_path(MACHINES_DIR)
    try:
        return sorted(p.name for p in folder.iterdir() if (p / "machine.json").is_file())
    except OSError:
        return []


def _machine_name(params: Params, ctx: Context) -> str:
    """The machine the sentence meant: the one named, or the only one there is."""
    name = str(params.get("name") or "")
    known = _machines(ctx)
    if name:
        if not LABEL_RE.match(name):
            raise ValidationError("a machine name is letters, digits, dots, dashes and underscores")
        if name not in known:
            raise ValidationError(f"no machine called {name} (dai-vm list)")
        return name
    if len(known) == 1:
        return known[0]
    if not known:
        raise ValidationError("there is no machine yet: make one in D.Ai VM")
    raise ValidationError("say which machine: " + ", ".join(known))


def _vm_power_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name", "action"})
    return {"name": _machine_name(params, ctx), "action": _choice(params.get("action"), ("start", "stop"), "action")}


def _vm_power_restore(params: Params, ctx: Context, extra: dict) -> None:
    ctx.run(["dai-vm", "stop" if params["action"] == "start" else "start", params["name"]], check=False)


register(ActionSpec(
    id="vm.power",
    scope="user",
    validate=_vm_power_validate,
    apply=lambda p, c: c.run(["dai-vm", p["action"], p["name"]]),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Start the machine {name} (its screen opens in a window)", "הפעלת המכונה {name} (המסך שלה נפתח בחלון)", name=p["name"])
                             if p["action"] == "start" else
                             _t(lang, "Ask the machine {name} to shut down", "בקשה מהמכונה {name} להיכבות", name=p["name"])),
    restore=_vm_power_restore,
))


def _vm_snapshot_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name", "label"})
    label = str(params.get("label") or "")
    if not label:
        import datetime
        label = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
    if not LABEL_RE.match(label):
        raise ValidationError("a snapshot name is letters, digits, dots, dashes and underscores")
    return {"name": _machine_name(params, ctx), "label": label}


register(ActionSpec(
    id="vm.snapshot",
    scope="user",
    validate=_vm_snapshot_validate,
    apply=lambda p, c: c.run(["dai-vm", "snapshot", p["name"], "take", p["label"], "--note", "D.Ai Tune"]),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "A snapshot of the machine {name}, called {label} (go back to it in D.Ai VM)",
                               "תמונת מצב של המכונה {name}, בשם {label} (חזרה אליה ב-D.Ai VM)", name=p["name"], label=p["label"]),
    restore=lambda p, c, e: c.run(["dai-vm", "snapshot", p["name"], "delete", p["label"]], check=False),
    note=lambda p, lang: _t(lang, "Undo deletes the snapshot again.", "ביטול מוחק את תמונת המצב."),
))


# --------------------------------------------------------------------------
# D.Ai TV (docs/TV.md stage 2): Kodi's remote-control services, off by default
# --------------------------------------------------------------------------

KODI_SETTINGS = ".kodi/userdata/guisettings.xml"
# What the phone needs (Kore and the like): the web server with a password, JSON-RPC over TCP, the event server.
KODI_REMOTE_PORTS = ((8080, "tcp"), (9090, "tcp"), (9777, "udp"))


def _kodi_settings_set(path: Path, values: dict[str, str]) -> None:
    """Set settings in Kodi's guisettings.xml, keeping everything else; the file is made when missing."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(read_text(path))
        if root.tag != "settings":
            raise ValueError("not a settings file")
    except (ET.ParseError, ValueError):
        root = ET.Element("settings", version="2")
    for key, value in values.items():
        element = next((e for e in root.iter("setting") if e.get("id") == key), None)
        if element is None:
            element = ET.SubElement(root, "setting", id=key)
        element.text = value
        element.attrib.pop("default", None)  # Kodi marks untouched settings as default; this one is chosen
    ET.indent(root)
    write_file(path, ET.tostring(root, encoding="unicode") + "\n", mode=0o600)


def _tv_remote_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"enabled", "password"})
    enabled = _bool(params.get("enabled"))
    password = str(params.get("password") or "")
    if enabled and not password:
        import secrets
        password = secrets.token_urlsafe(9)  # the phone app asks for it once; it is in Kodi's settings afterwards
    if not re.fullmatch(r"[A-Za-z0-9_-]{0,64}", password):
        raise ValidationError("the password is letters, digits, dashes and underscores")
    return {"enabled": enabled, "password": password}


def _tv_remote_apply(params: Params, ctx: Context) -> None:
    on = params["enabled"]
    values = {"services.webserver": "true" if on else "false", "services.webserverport": "8080",
              "services.webserverauthentication": "true", "services.webserverusername": "kodi",
              # the service itself stays on for this computer (dai-tv talks to Kodi through it); "off" closes it to the network
              "services.esenabled": "true", "services.esallinterfaces": "true" if on else "false"}
    if on:
        values["services.webserverpassword"] = params["password"]
    _kodi_settings_set(ctx.user_path(KODI_SETTINGS), values)


register(ActionSpec(
    id="tv.remote_control",
    scope="user",
    validate=_tv_remote_validate,
    apply=_tv_remote_apply,
    risk=lambda p: "medium" if p["enabled"] else "low",
    effect=lambda p: "weakens" if p["enabled"] else "hardens",
    summary=lambda p, lang: (_t(lang, "Let the phone control the TV (Kodi's web server and remote-control service; user kodi, password {pw})",
                                "לאפשר לטלפון לשלוט בטלוויזיה (שרת האינטרנט ושירות השלט של Kodi; משתמש kodi, סיסמה {pw})", pw=p["password"])
                             if p["enabled"] else
                             _t(lang, "Stop remote control of the TV (Kodi's web server and remote-control service off)",
                                "ביטול השליטה מרחוק בטלוויזיה (שרת האינטרנט ושירות השלט של Kodi כבויים)")),
    files=lambda p, c: [c.user_path(KODI_SETTINGS)],
    note=lambda p, lang: _t(lang, "Takes effect when Kodi starts again. The ports open to the local network only.",
                            "נכנס לתוקף כש-Kodi יופעל מחדש. הפורטים נפתחים לרשת המקומית בלבד.") if p["enabled"] else "",
))


KODI_PROFILES = ".kodi/userdata/profiles.xml"
KODI_NIGHT = {"screensaver.mode": "screensaver.xbmc.builtin.dim", "screensaver.time": "5"}
CHILDREN_PROFILE = "Children"


def _tv_night_apply(params: Params, ctx: Context) -> None:
    """The file for the next start; the running Kodi is told directly through dai-tv (best effort)."""
    on = params["enabled"]
    _kodi_settings_set(ctx.user_path(KODI_SETTINGS), KODI_NIGHT if on else {"screensaver.time": "10"})
    ctx.run(["dai-tv", "night", "on" if on else "off"], check=False)


register(ActionSpec(
    id="tv.night_mode",
    scope="user",
    validate=lambda p, c: (_only_keys(p, {"enabled"}), {"enabled": _bool(p.get("enabled"))})[1],
    apply=_tv_night_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Night mode on the TV: the screen dims after 5 minutes, the volume goes down",
                                "מצב לילה בטלוויזיה: המסך מתעמעם אחרי 5 דקות, העוצמה יורדת") if p["enabled"] else
                             _t(lang, "Night mode on the TV off", "מצב לילה בטלוויזיה כבוי")),
    files=lambda p, c: [c.user_path(KODI_SETTINGS)],
    restore=lambda p, c, e: c.run(["dai-tv", "night", "off" if p["enabled"] else "on"], check=False),
))


def _kodi_profiles_set(path: Path, enabled: bool, pin: str) -> None:
    """Kodi's profiles.xml (xbmc/profiles/Profile.cpp, ProfileManager.cpp): the master profile gets a numeric lock
    (its code is the MD5 of the PIN, as CGUIPassword compares it), a "Children" profile without a lock becomes the
    one Kodi logs into on its own, with its own sources it cannot change and no settings or add-on manager. Off:
    the master lock and the automatic login go; the children's profile and its library stay."""
    import hashlib
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(read_text(path))
        if root.tag != "profiles":
            raise ValueError("not a profiles file")
    except (ET.ParseError, ValueError):
        root = ET.Element("profiles")
    profiles = root.findall("profile")

    def field(profile, tag: str, value: str) -> None:
        element = profile.find(tag)
        if element is None:
            element = ET.SubElement(profile, tag)
        element.text = value

    master = next((p for p in profiles if (p.findtext("id") or "").strip() == "0"), None)
    if master is None:
        master = ET.SubElement(root, "profile")
        for tag, value in (("id", "0"), ("name", "Master user"), ("directory", "special://masterprofile/")):
            field(master, tag, value)
    children = next((p for p in profiles if (p.findtext("name") or "").strip() == CHILDREN_PROFILE), None)
    if children is None:
        used = {int(p.findtext("id") or 0) for p in root.findall("profile")}
        new_id = next(i for i in range(1, 100) if i not in used)
        children = ET.SubElement(root, "profile")
        for tag, value in (("id", str(new_id)), ("name", CHILDREN_PROFILE), ("directory", f"profiles/{CHILDREN_PROFILE}/"),
                           ("hasdatabases", "true"), ("canwritedatabases", "true"), ("hassources", "true"),
                           ("canwritesources", "false"), ("lockaddonmanager", "true"), ("locksettings", "1"),
                           ("lockfiles", "true"), ("lockprograms", "true"), ("lockmode", "0"), ("lockcode", "-")):
            field(children, tag, value)
    if enabled:
        field(master, "lockmode", "1")
        field(master, "lockcode", hashlib.md5(pin.encode("utf-8")).hexdigest())  # noqa: S324 - Kodi's own scheme
        field(root, "useloginscreen", "true")
        field(root, "autologin", (children.findtext("id") or "1").strip())
    else:
        field(master, "lockmode", "0")
        field(master, "lockcode", "-")
        field(root, "autologin", "-1")
    used = {int(p.findtext("id") or 0) for p in root.findall("profile")}
    field(root, "nextIdProfile", str(max(used) + 1))
    field(root, "lastloaded", "0")
    ET.indent(root)
    write_file(path, ET.tostring(root, encoding="unicode") + "\n", mode=0o600)


def _tv_children_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"enabled", "pin"})
    enabled = _bool(params.get("enabled"))
    pin = str(params.get("pin") or "")
    if enabled and not pin:
        import secrets
        pin = "".join(secrets.choice("0123456789") for _ in range(4))  # shown in the plan: the parents' code
    if pin and not re.fullmatch(r"[0-9]{4,8}", pin):
        raise ValidationError("the PIN is 4 to 8 digits")
    return {"enabled": enabled, "pin": pin}


register(ActionSpec(
    id="tv.children_profile",
    scope="user",
    validate=_tv_children_validate,
    apply=lambda p, c: _kodi_profiles_set(c.user_path(KODI_PROFILES), p["enabled"], p["pin"]),
    risk=lambda p: "low",
    effect=lambda p: "hardens" if p["enabled"] else "weakens",
    summary=lambda p, lang: (_t(lang, "A children's profile on the TV: Kodi starts in it, with its own sources; leaving it asks the PIN {pin}",
                                "פרופיל ילדים בטלוויזיה: Kodi מתחיל בו, עם מקורות משלו; יציאה ממנו מבקשת את הקוד {pin}", pin=p["pin"])
                             if p["enabled"] else
                             _t(lang, "The children's profile no longer starts on its own; the parents' PIN is removed",
                                "פרופיל הילדים כבר לא מופעל מעצמו; קוד ההורים מוסר")),
    files=lambda p, c: [c.user_path(KODI_PROFILES)],
    note=lambda p, lang: _t(lang, "Takes effect when Kodi starts again. Write the PIN down: it is what lets a grown-up out.",
                            "נכנס לתוקף כש-Kodi יופעל מחדש. רשמו את הקוד: הוא מה שמוציא מבוגר מהפרופיל.") if p["enabled"] else "",
))


# The screen's rotation on a tablet (docs/MOBILE.md A3), read by dai-rotate.
ROTATE_FILE = ".config/dai/rotate"
ROTATE_NAMES = {"auto": ("follows the tablet", "עוקב אחרי הטאבלט"), "off": ("locked as it is", "נעול כמו שהוא"),
                "normal": ("upright", "ישר"), "90": ("turned 90°", "מסובב 90°"), "180": ("upside down", "הפוך"),
                "270": ("turned 270°", "מסובב 270°")}


def _rotation_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"mode"})
    return {"mode": _choice(params.get("mode"), tuple(ROTATE_NAMES), "mode")}


def _rotation_apply(params: Params, ctx: Context) -> None:
    write_file(ctx.user_path(ROTATE_FILE), params["mode"] + "\n", mode=0o600)
    ctx.run(["dai-rotate", "apply"], check=False)  # a fixed orientation turns the screen now; auto and off wait for the sensor


register(ActionSpec(
    id="display.rotation",
    scope="user",
    validate=_rotation_validate,
    apply=_rotation_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "The screen's rotation: {name}", "סיבוב המסך: {name}", name=pick(lang, *ROTATE_NAMES[p["mode"]])),
    files=lambda p, c: [c.user_path(ROTATE_FILE)],
    restore=lambda p, c, e: c.run(["dai-rotate", "apply"], check=False),
))


KODI_CHANNELS = ".kodi/userdata/addon_data/pvr.iptvsimple/instance-settings-1.xml"


def _tv_channels_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"playlist"})
    playlist = str(params.get("playlist") or "").strip()
    if not playlist:
        return {"playlist": ""}
    path = Path(playlist).expanduser()
    if not path.is_absolute():
        path = ctx.home / path
    if path.suffix.lower() not in (".m3u", ".m3u8"):
        raise ValidationError("a playlist is a .m3u or .m3u8 file")
    if not path.is_file():
        raise ValidationError(f"no such playlist: {path}")
    return {"playlist": str(path)}


register(ActionSpec(
    id="tv.channels",
    scope="user",
    validate=_tv_channels_validate,
    apply=lambda p, c: c.run(["dai-tv", "channels", p["playlist"]] if p["playlist"] else ["dai-tv", "channels", "--off"]),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Live channels on the TV from your playlist {file}", "ערוצים חיים בטלוויזיה מהרשימה שלכם {file}",
                                file=Path(p["playlist"]).name) if p["playlist"] else
                             _t(lang, "Live channels off", "ערוצים חיים כבויים")),
    files=lambda p, c: [c.user_path(KODI_CHANNELS)],
    note=lambda p, lang: _t(lang, "Kodi shows the channels when it starts again. The playlist stays where it is; only its path is kept.",
                            "Kodi יציג את הערוצים כשיופעל מחדש. הרשימה נשארת במקומה; רק הנתיב שלה נשמר.") if p["playlist"] else "",
))


# --------------------------------------------------------------------------
# D.Ai's system sounds (docs/SOUNDS.md), read by dai-sound
# --------------------------------------------------------------------------

SOUNDS_FILE = ".config/dai/sounds"
SOUND_NAMES = {"on": ("on", "פועלים"), "quiet": ("quiet", "שקטים"), "off": ("off", "כבויים")}


def _sounds_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"mode"})
    return {"mode": _choice(params.get("mode"), tuple(SOUND_NAMES), "mode")}


register(ActionSpec(
    id="system.sounds",
    scope="user",
    validate=_sounds_validate,
    apply=lambda p, c: write_file(c.user_path(SOUNDS_FILE), p["mode"] + "\n", mode=0o600),
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "D.Ai's system sounds: {mode}", "צלילי המערכת של D.Ai: {mode}",
                               mode=pick(lang, *SOUND_NAMES[p["mode"]])),
    files=lambda p, c: [c.user_path(SOUNDS_FILE)],
))


# --------------------------------------------------------------------------
# Language of the system and of the session (docs/I18N.md §9)
# --------------------------------------------------------------------------

# The eight languages of D.Ai OS and the locale each one uses.
UI_LOCALES = {"he": "he_IL.UTF-8", "en": "en_US.UTF-8", "ar": "ar_EG.UTF-8", "ru": "ru_RU.UTF-8",
              "es": "es_ES.UTF-8", "fr": "fr_FR.UTF-8", "de": "de_DE.UTF-8", "pt": "pt_BR.UTF-8"}
LOCALE_GEN = "/etc/locale.gen"
LANGUAGE_ENV = ".config/dai/language.env"
LANGUAGE_NAMES = {"he": ("Hebrew", "עברית"), "en": ("English", "אנגלית"), "ar": ("Arabic", "ערבית"),
                  "ru": ("Russian", "רוסית"), "es": ("Spanish", "ספרדית"), "fr": ("French", "צרפתית"),
                  "de": ("German", "גרמנית"), "pt": ("Portuguese", "פורטוגזית")}


def _lang_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"lang"})
    return {"lang": _choice(params.get("lang"), UI_LOCALES, "language")}


def _language_name(code: str, lang: str) -> str:
    return pick(lang, *LANGUAGE_NAMES[code])  # translated for the other six languages too


def _locale_apply(params: Params, ctx: Context) -> None:
    """Make the locale available: its line in /etc/locale.gen, then locale-gen (Debian's own tools)."""
    wanted = f"{UI_LOCALES[params['lang']]} UTF-8"
    path = ctx.path(LOCALE_GEN)
    lines = read_text(path).splitlines()
    found = False
    for index, line in enumerate(lines):
        if line.lstrip("# ").strip() == wanted:
            lines[index] = wanted
            found = True
    if not found:
        lines.append(wanted)
    write_file(path, "\n".join(lines) + "\n", mode=0o644)
    ctx.run(["locale-gen"])


register(ActionSpec(
    id="system.locale",
    scope="system",
    validate=_lang_validate,
    apply=_locale_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Make {name} available on this computer ({locale})",
                               "הוספת {name} למחשב ({locale})", name=_language_name(p["lang"], lang),
                               locale=UI_LOCALES[p["lang"]]),
    files=lambda p, c: [c.path(LOCALE_GEN)],
    restore=lambda p, c, e: c.run(["locale-gen"], check=False),
))


def _session_language_apply(params: Params, ctx: Context) -> None:
    code = params["lang"]
    # startdai-wayland reads this file at login (only these two keys, only values from UI_LOCALES).
    write_file(ctx.user_path(LANGUAGE_ENV), f"LANG={UI_LOCALES[code]}\nLANGUAGE={code}:en\n", mode=0o600)


register(ActionSpec(
    id="session.language",
    scope="user",
    validate=_lang_validate,
    apply=_session_language_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Show D.Ai in {name} from the next login", "‏D.Ai ב{name} מהכניסה הבאה",
                               name=_language_name(p["lang"], lang)),
    files=lambda p, c: [c.user_path(LANGUAGE_ENV)],
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
    # Unit files were already restored from the snapshot (gone again after an install's undo). Stop the timer
    # before systemd re-reads the units: a running timer whose file vanished is left "failed" otherwise, and
    # D.Ai Heal would report a failure that was only this undo (seen in CI). reset-failed clears any remains.
    if extra.get("was_enabled") or params["enabled"]:
        ctx.run(["systemctl", "disable", "--now", "dai-av-scan.timer"], check=False)
    ctx.run(["systemctl", "daemon-reload"], check=False)
    ctx.run(["systemctl", "reset-failed", "dai-av-scan.timer"], check=False)
    if extra.get("was_enabled"):
        ctx.run(["systemctl", "enable", "--now", "dai-av-scan.timer"], check=False)


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


# --------------------------------------------------------------------------
# "This app does not go online" (docs/BEYOND.md §12): the app's launcher starts
# it in a bubblewrap network namespace (no root, nothing at boot to go wrong)
# --------------------------------------------------------------------------

APP_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,63}$")
USER_APPS = ".local/share/applications"
SYSTEM_APPS = ("/usr/local/share/applications", "/usr/share/applications")
FLATPAK_OVERRIDES = ".local/share/flatpak/overrides"
FLATPAK_APPS = (".local/share/flatpak/app", "/var/lib/flatpak/app")
OFFLINE_MARK = "X-DAi-Offline=true"
# Hebrew and generic names for the apps people say most (any .desktop id or name works too).
APP_ALIASES = {
    "פיירפוקס": "firefox", "דפדפן": "firefox", "browser": "firefox", "כרום": "chromium", "chrome": "chromium",
    "google-chrome": "google-chrome", "גוגל-כרום": "google-chrome",
    "טלגרם": "telegram", "סיגנל": "signal", "דיסקורד": "discord", "זום": "zoom", "ספוטיפיי": "spotify",
    "סטים": "steam", "קודי": "kodi", "ליברה": "libreoffice", "אופיס": "libreoffice", "office": "libreoffice",
    "vlc": "vlc", "וי אל סי": "vlc", "thunderbird": "thunderbird", "ת'אנדרבירד": "thunderbird",
}


def _app_param(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("app: expected a name")
    app = re.sub(r"\s+", "-", value.strip().lower())
    app = APP_ALIASES.get(app, app)
    if not APP_RE.match(app):
        raise ValidationError("app: letters, digits, dots and dashes only")
    return app


def _flatpak_id(app: str, ctx: Context) -> str | None:
    """The Flatpak app id when the name is one (org.x.Y, installed for the user or the system)."""
    if app.count(".") < 2:
        return None
    for base in FLATPAK_APPS:
        root = ctx.user_path(base) if base.startswith(".") else ctx.path(base)
        for found in root.glob("*") if root.is_dir() else []:
            if found.name.lower() == app:
                return found.name
    return None


def find_desktop_file(app: str, ctx: Context) -> Path | None:
    """The system .desktop file for a name: exact id, then an id starting with it, then its Name."""
    candidates: list[Path] = []
    for base in SYSTEM_APPS:
        folder = ctx.path(base)
        if folder.is_dir():
            candidates.extend(sorted(folder.glob("*.desktop")))
    for path in candidates:
        if path.stem.lower() == app:
            return path
    for path in candidates:
        if path.stem.lower().startswith(app) or path.stem.lower().split(".")[-1] == app:
            return path
    for path in candidates:
        try:
            names = re.findall(r"^Name(?:\[[^\]]*\])?=(.*)$", path.read_text(encoding="utf-8", errors="replace"), re.M)
        except OSError:
            continue
        if any(name.strip().lower() == app for name in names):
            return path
    return None


def offline_desktop_text(original: str, app: str) -> str:
    """The override: every Exec= starts the program in the offline slice, and the file says why."""
    lines = []
    for line in original.splitlines():
        if line.startswith("Exec="):
            command = line[len("Exec="):].strip()
            if not command.startswith("dai-offline-run "):
                line = f"Exec=dai-offline-run {app} -- {command}"
        if line.startswith("X-DAi-Offline="):
            continue
        lines.append(line)
        if line.strip() == "[Desktop Entry]":
            lines.append(OFFLINE_MARK)
    return "\n".join(lines) + "\n"


def _app_offline_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"app"})
    app = _app_param(params.get("app"))
    if _flatpak_id(app, ctx) is None and find_desktop_file(app, ctx) is None:
        raise ValidationError(f"app: no application called {app} is installed")
    return {"app": app}


def _app_offline_files(params: Params, ctx: Context) -> list[Path]:
    app = params["app"]
    flatpak = _flatpak_id(app, ctx)
    if flatpak:
        return [ctx.user_path(f"{FLATPAK_OVERRIDES}/{flatpak}")]
    source = find_desktop_file(app, ctx)
    return [ctx.user_path(f"{USER_APPS}/{source.name}")] if source else []


def _app_offline_apply(params: Params, ctx: Context) -> None:
    app = params["app"]
    flatpak = _flatpak_id(app, ctx)
    if flatpak:
        path = ctx.user_path(f"{FLATPAK_OVERRIDES}/{flatpak}")
        current = read_text(path, "")
        if "shared=" in current:
            current = re.sub(r"^shared=.*$", "shared=!network;", current, flags=re.M)
        elif "[Context]" in current:
            current = current.replace("[Context]", "[Context]\nshared=!network;", 1)
        else:
            current = current.rstrip("\n") + ("\n" if current.strip() else "") + "[Context]\nshared=!network;\n"
        write_file(path, current, mode=0o600)
        return
    source = find_desktop_file(app, ctx)
    if source is None:
        raise ActionError(f"no application called {app}")
    write_file(ctx.user_path(f"{USER_APPS}/{source.name}"), offline_desktop_text(source.read_text(encoding="utf-8"), app))


def _app_online_apply(params: Params, ctx: Context) -> None:
    app = params["app"]
    flatpak = _flatpak_id(app, ctx)
    if flatpak:
        path = ctx.user_path(f"{FLATPAK_OVERRIDES}/{flatpak}")
        current = read_text(path, "")
        if current:
            write_file(path, re.sub(r"^shared=!network;\n?", "", current, flags=re.M), mode=0o600)
        return
    source = find_desktop_file(app, ctx)
    if source is None:
        return
    override = ctx.user_path(f"{USER_APPS}/{source.name}")
    if override.is_file() and OFFLINE_MARK in read_text(override, ""):
        override.unlink()


register(ActionSpec(
    id="app.offline",
    scope="user",
    validate=_app_offline_validate,
    apply=_app_offline_apply,
    risk=lambda p: "low",
    effect=lambda p: "hardens",
    summary=lambda p, lang: _t(lang, "{app} opens without network access from now on",
                               "{app} נפתח בלי גישה לרשת מעכשיו", app=p["app"]),
    files=_app_offline_files,
    note=lambda p, lang: _t(lang, "The menu, the command bar and the taskbar all start it that way; connections fail at once "
                                  "and local services (sound, display) still work. A copy already running stays connected until "
                                  "it is opened again.",
                            "התפריט, שורת הפקודה וסרגל המשימות פותחים אותו כך; חיבורים נכשלים מיד ושירותים מקומיים (צליל, "
                            "תצוגה) ממשיכים לעבוד. עותק שכבר רץ נשאר מחובר עד שפותחים אותו מחדש."),
))

register(ActionSpec(
    id="app.online",
    scope="user",
    validate=_app_offline_validate,
    apply=_app_online_apply,
    risk=lambda p: "low",
    effect=lambda p: "weakens",
    summary=lambda p, lang: _t(lang, "{app} opens with network access again", "{app} נפתח עם גישה לרשת שוב", app=p["app"]),
    files=_app_offline_files,
))


# --------------------------------------------------------------------------
# Memory saver for old computers (docs/BEYOND.md §14): zram tightened, Diamond
# on its smallest model, MOM says what is heavy
# --------------------------------------------------------------------------

SAVER_MARK = "/etc/dai/memory-saver"
SAVER_SYSCTL = "/etc/sysctl.d/60-dai-memory-saver.conf"
SAVER_ZRAM = "/etc/systemd/zram-generator.conf.d/dai-memory-saver.conf"
AI_CONFIG = ".config/dai/ai.json"


def _saver_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"enabled"})
    return {"enabled": _bool(params.get("enabled"))}


def _saver_apply(params: Params, ctx: Context) -> None:
    mark, sysctl, zram = ctx.path(SAVER_MARK), ctx.path(SAVER_SYSCTL), ctx.path(SAVER_ZRAM)
    if params["enabled"]:
        write_file(sysctl, (
            "# Managed by dai-tune: memory saver (docs/BEYOND.md §14). Values recommended for zram swap.\n"
            "vm.swappiness = 180\n"
            "vm.page-cluster = 0\n"
            "vm.watermark_boost_factor = 0\n"
            "vm.watermark_scale_factor = 125\n"
        ))
        write_file(zram, (
            "# Managed by dai-tune: memory saver (docs/BEYOND.md §14). Takes effect at the next boot.\n"
            "[zram0]\n"
            "zram-size = min(ram, 8192)\n"
            "compression-algorithm = zstd\n"
        ))
        write_file(mark, json.dumps({"on": True}) + "\n")
    else:
        for path in (sysctl, zram, mark):
            path.unlink(missing_ok=True)
    _saver_reload(ctx)


SAVER_DEFAULTS = ("vm.swappiness=60", "vm.page-cluster=3", "vm.watermark_boost_factor=15000", "vm.watermark_scale_factor=10")


def _saver_reload(ctx: Context) -> None:
    """The kernel's own defaults first (removing a sysctl file does not undo its values), then every file."""
    ctx.run(["sysctl", "-q", "-w", *SAVER_DEFAULTS], check=False)
    ctx.run(["sysctl", "--system", "-q"], check=False)


def saver_on(ctx: Context) -> bool:
    return ctx.path(SAVER_MARK).exists()


register(ActionSpec(
    id="memory.saver",
    scope="system",
    validate=_saver_validate,
    apply=_saver_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Memory saver on: compressed swap first, tuned for little RAM",
                                "מצב חיסכון בזיכרון: החלפה דחוסה קודם, מכוון למעט זיכרון") if p["enabled"]
                             else _t(lang, "Memory saver off: the usual memory settings", "חיסכון בזיכרון כבוי: הגדרות הזיכרון הרגילות")),
    files=lambda p, c: [c.path(SAVER_MARK), c.path(SAVER_SYSCTL), c.path(SAVER_ZRAM)],
    restore=lambda p, c, e: _saver_reload(c),
    note=lambda p, lang: _t(lang, "The larger compressed swap starts at the next boot; the rest applies now.",
                            "ההחלפה הדחוסה הגדולה יותר מתחילה באתחול הבא; השאר חל עכשיו.") if p["enabled"] else "",
))


def _small_model_apply(params: Params, ctx: Context) -> None:
    path = ctx.user_path(AI_CONFIG)
    try:
        data = json.loads(read_text(path, "{}"))
    except json.JSONDecodeError:
        data = {}
    data = data if isinstance(data, dict) else {}
    if params["enabled"]:
        data["prefer_small"] = True
    else:
        data.pop("prefer_small", None)
    write_file(path, json.dumps(data, indent=2) + "\n", mode=0o600)


register(ActionSpec(
    id="diamond.small_model",
    scope="user",
    validate=_saver_validate,
    apply=_small_model_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Diamond answers with its smallest installed model", "Diamond עונה עם המודל הקטן ביותר שמותקן")
                             if p["enabled"] else _t(lang, "Diamond uses the chosen model again", "Diamond משתמש שוב במודל שנבחר")),
    files=lambda p, c: [c.user_path(AI_CONFIG)],
))


# --------------------------------------------------------------------------
# Which AI answers: the local Diamond, or a provider the person set up and agreed
# to (docs/PROVIDERS.md); the consent itself is only ever typed at dai-models.
# --------------------------------------------------------------------------

PROVIDERS_FILE = ".config/dai/providers.json"


def _providers_module():
    from dai_ai import providers  # installed next to dai_tune in /usr/lib/dai
    return providers


def _provider_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name"})
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise ValidationError("name: 'local' or a provider set up with dai-models provider")
    if name == "local":
        return {"name": "local"}
    if policy_forbids_providers(ctx):
        raise ValidationError("name: an organization policy forbids external AI providers on this computer (dai-tune policy)")
    config = _providers_module().load(ctx.user_path(PROVIDERS_FILE))
    provider = config.providers.get(name)
    if provider is None:
        raise ValidationError(f"name: no provider called {name} (dai-models provider add {name})")
    if not provider.consented:
        raise ValidationError(f"name: {name} needs your typed consent first (dai-models provider use {name})")
    return {"name": name}


def _provider_apply(params: Params, ctx: Context) -> None:
    providers = _providers_module()
    path = ctx.user_path(PROVIDERS_FILE)
    config = providers.load(path)
    config.active = "" if params["name"] == "local" else params["name"]
    providers.save(config, path)


def _providers_policy_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"allowed"})
    return {"allowed": _bool(params.get("allowed", False))}


def _providers_policy_apply(params: Params, ctx: Context) -> None:
    path = ctx.path(POLICY_AI_ENV)
    if params["allowed"]:
        if path.exists():
            path.unlink()
        return
    update_env_file(path, {"DAI_AI_PROVIDERS": "forbidden"}, mode=0o644)


register(ActionSpec(
    id="ai.providers_policy",
    scope="system",
    validate=_providers_policy_validate,
    apply=_providers_policy_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral" if p["allowed"] else "hardens",
    summary=lambda p, lang: (_t(lang, "Every user: external AI providers are allowed again", "כל המשתמשים: ספקי AI חיצוניים מותרים שוב") if p["allowed"]
                             else _t(lang, "Every user: Diamond answers on this computer only, no external AI providers",
                                     "כל המשתמשים: Diamond עונה במחשב הזה בלבד, בלי ספקי AI חיצוניים")),
    files=lambda p, c: [c.path(POLICY_AI_ENV)],
    note=lambda p, lang: "" if p["allowed"] else _t(lang, "Keys already saved stay in each user's config but are not used; dai-models provider use refuses.",
                                                     "מפתחות שכבר נשמרו נשארים בהגדרות של כל משתמש אך לא בשימוש; dai-models provider use מסרב."),
))


register(ActionSpec(
    id="diamond.provider",
    scope="user",
    validate=_provider_validate,
    apply=_provider_apply,
    risk=lambda p: "low" if p["name"] == "local" else "medium",
    effect=lambda p: "hardens" if p["name"] == "local" else "weakens",
    summary=lambda p, lang: (_t(lang, "Diamond answers on this computer only", "Diamond עונה במחשב הזה בלבד") if p["name"] == "local"
                             else _t(lang, "Diamond's questions and code go to {name}, with your own key",
                                     "השאלות והקוד של Diamond נשלחים ל־{name}, במפתח שלך", name=p["name"])),
    files=lambda p, c: [c.user_path(PROVIDERS_FILE)],
    note=lambda p, lang: "" if p["name"] == "local" else _t(lang, "Speech stays on the computer. The consent was given at dai-models provider use.",
                                                             "דיבור נשאר במחשב. ההסכמה ניתנה ב־dai-models provider use."),
))


# --------------------------------------------------------------------------
# Diamond's Way, when: (docs/WAY.md §2): a user timer that runs one D.Ai Tune sentence at a time. The sentence
# is kept as text and parsed again at every run; only user-scope actions, because a timer cannot ask for an
# administrator. dai-way run-when NAME is what the timer starts.
# --------------------------------------------------------------------------

WAY_DIR = ".config/dai/way"
WAY_UNIT_DIR = ".config/systemd/user"
WAY_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
WAY_SENTENCE_MAX = 200


def way_unit(name: str, suffix: str) -> str:
    return f"dai-way-{name}.{suffix}"


def way_schedule(value: Any):
    from dai_forge.schedule import Schedule  # installed next to dai_tune in /usr/lib/dai
    schedule = Schedule.from_json(value)
    if schedule is None:
        raise ValidationError("schedule: not a schedule (every day at 18:00, every monday at 9, at login …)")
    return schedule


def way_sentence_requests(sentence: str) -> list:
    """The requests one sentence makes; every one must be a user-scope action."""
    from .parser import parse as parse_sentence
    if not isinstance(sentence, str) or not sentence.strip() or len(sentence) > WAY_SENTENCE_MAX:
        raise ValidationError(f"sentence: 1 to {WAY_SENTENCE_MAX} characters")
    if "\n" in sentence:
        raise ValidationError("sentence: one line")
    parsed = parse_sentence(sentence.strip())
    if parsed.unknown or not parsed.requests:
        raise ValidationError(f"sentence: not understood: {', '.join(parsed.unknown) or sentence.strip()}")
    for request in parsed.requests:
        spec = CATALOG.get(request.action)
        if spec is None or spec.scope != "user":
            raise ValidationError(f"sentence: {request.action} needs an administrator; a timer cannot ask for one")
        if request.action in ("way.when", "way.when_off"):
            raise ValidationError("sentence: a timer may not set timers")
    return parsed.requests


def _way_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name", "schedule", "sentence"})
    name = params.get("name")
    if not isinstance(name, str) or not WAY_NAME_RE.match(name):
        raise ValidationError("name: a-z, 0-9 and '-', 2 to 40 characters, starting with a letter")
    schedule = way_schedule(params.get("schedule"))
    way_sentence_requests(params.get("sentence"))
    return {"name": name, "schedule": schedule.to_json(), "sentence": str(params["sentence"]).strip()}


def _way_off_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"name"})
    name = params.get("name")
    if not isinstance(name, str) or not WAY_NAME_RE.match(name):
        raise ValidationError("name: a-z, 0-9 and '-', 2 to 40 characters, starting with a letter")
    if not ctx.user_path(f"{WAY_DIR}/{name}.json").is_file():
        raise ValidationError(f"name: no timer called {name} (dai-way when)")
    return {"name": name}


def _way_files(params: Params, ctx: Context) -> list[Path]:
    name = params["name"]
    return [ctx.user_path(f"{WAY_DIR}/{name}.json"),
            ctx.user_path(f"{WAY_UNIT_DIR}/{way_unit(name, 'service')}"),
            ctx.user_path(f"{WAY_UNIT_DIR}/{way_unit(name, 'timer')}")]


def way_unit_texts(name: str, schedule, sentence: str) -> dict[str, str]:
    """The service and, unless the schedule is "at login", the timer."""
    service = [
        f"# Written by Diamond's Way (docs/WAY.md): when {schedule.describe('en')}: {sentence}. dai-way when remove {name}",
        "[Unit]",
        f"Description=D.Ai Way: {sentence}",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart=/usr/bin/dai-way run-when {name}",
        "NoNewPrivileges=yes",
    ]
    files = {}
    if schedule.kind == "login":
        service += ["", "[Install]", "WantedBy=default.target"]
        files[way_unit(name, "service")] = "\n".join(service) + "\n"
        return files
    files[way_unit(name, "service")] = "\n".join(service) + "\n"
    files[way_unit(name, "timer")] = "\n".join([
        f"# Written by Diamond's Way (docs/WAY.md). dai-way when remove {name}",
        "[Unit]",
        f"Description=D.Ai Way timer: {sentence}",
        "",
        "[Timer]",
        *schedule.timer_lines(),
        "",
        "[Install]",
        "WantedBy=timers.target",
    ]) + "\n"
    return files


def _way_target(name: str, schedule) -> str:
    return way_unit(name, "service" if schedule.kind == "login" else "timer")


def _way_apply(params: Params, ctx: Context) -> None:
    name, schedule, sentence = params["name"], way_schedule(params["schedule"]), params["sentence"]
    for filename, content in way_unit_texts(name, schedule, sentence).items():
        write_file(ctx.user_path(f"{WAY_UNIT_DIR}/{filename}"), content)
    write_file(ctx.user_path(f"{WAY_DIR}/{name}.json"),
               json.dumps({"schedule": schedule.to_json(), "sentence": sentence}, ensure_ascii=False, indent=1) + "\n", mode=0o600)
    ctx.run(["systemctl", "--user", "daemon-reload"], check=False)
    ctx.run(["systemctl", "--user", "enable", "--now", _way_target(name, schedule)])


def _way_disable(name: str, ctx: Context) -> None:
    for suffix in ("timer", "service"):
        ctx.run(["systemctl", "--user", "disable", "--now", way_unit(name, suffix)], check=False)
    ctx.run(["systemctl", "--user", "daemon-reload"], check=False)
    for suffix in ("timer", "service"):
        ctx.run(["systemctl", "--user", "reset-failed", way_unit(name, suffix)], check=False)


def _way_off_apply(params: Params, ctx: Context) -> None:
    name = params["name"]
    _way_disable(name, ctx)
    for path in _way_files(params, ctx):
        if path.exists():
            path.unlink()


def _way_restore(params: Params, ctx: Context, extra: dict) -> None:
    # The files are already back as they were (gone after an install's undo, present after a remove's undo).
    name = params["name"]
    _way_disable(name, ctx)
    stored = read_text(ctx.user_path(f"{WAY_DIR}/{name}.json"), "")
    if stored:
        try:
            schedule = way_schedule(json.loads(stored).get("schedule"))
        except (ValueError, ValidationError):
            return
        ctx.run(["systemctl", "--user", "enable", "--now", _way_target(name, schedule)], check=False)


# files: (docs/WAY.md §2, stage 3): a folder or a small text file in the home, never hidden, never executable.
WAY_FILE_MAX = 64 * 1024
WAY_PATH_RE = re.compile(r"^[^\0]{1,200}$")


def way_relative_path(value: Any) -> str:
    """"Documents/School/" or "Documents/Welcome.txt": relative, visible, inside the home; the error says why not."""
    if not isinstance(value, str) or not WAY_PATH_RE.match(value) or not value.strip():
        raise ValidationError("path: 1 to 200 characters")
    text = value.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~"):
        raise ValidationError(f"path: only inside your home, as a relative path ({text})")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in ("..", ".") for part in parts):
        raise ValidationError(f"path: no .. or . in a path ({text})")
    if any(part.startswith(".") for part in parts):
        raise ValidationError(f"path: hidden files and folders are not written by a .dway file ({text})")
    if parts[-1].lower().endswith(".desktop") and not text.endswith("/"):
        raise ValidationError("path: a .desktop file is not written by a .dway file")
    return "/".join(parts) + ("/" if text.endswith("/") else "")


def _way_file_validate(params: Params, ctx: Context) -> Params:
    _only_keys(params, {"path", "content"})
    path = way_relative_path(params.get("path"))
    content = params.get("content", "")
    if path.endswith("/"):
        if content:
            raise ValidationError("content: a folder has no content")
        return {"path": path, "content": ""}
    if not isinstance(content, str):
        raise ValidationError("content: text")
    if len(content.encode("utf-8")) > WAY_FILE_MAX:
        raise ValidationError(f"content: larger than {WAY_FILE_MAX // 1024} KB")
    target = ctx.user_path(path)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValidationError(f"path: {path} exists and is not a plain file")
    if target.is_file() and read_text(target, None) != content:
        raise ValidationError(f"path: {path} exists with other content; it is not replaced")
    return {"path": path, "content": content}


def _way_file_apply(params: Params, ctx: Context) -> None:
    target = ctx.user_path(params["path"].rstrip("/"))
    if params["path"].endswith("/"):
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ActionError(f"{params['path']} exists and is not a folder")
        target.mkdir(parents=True, exist_ok=True, mode=0o755)
        return
    if target.is_file() and read_text(target, None) == params["content"]:
        return
    write_file(target, params["content"], mode=0o644)


def _way_file_capture(params: Params, ctx: Context) -> dict:
    return {"existed": ctx.user_path(params["path"].rstrip("/")).exists()}


def _way_file_restore(params: Params, ctx: Context, extra: dict) -> None:
    # A file is already back from the snapshot (gone, when it was new); a new, now empty folder goes too.
    if params["path"].endswith("/") and not extra.get("existed"):
        target = ctx.user_path(params["path"].rstrip("/"))
        try:
            target.rmdir()
        except OSError:
            pass


register(ActionSpec(
    id="way.file",
    scope="user",
    validate=_way_file_validate,
    apply=_way_file_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: (_t(lang, "Folder {path} in your home", "תיקייה {path} בבית שלך", path=p["path"]) if p["path"].endswith("/")
                             else _t(lang, "File {path} in your home ({size} characters)", "קובץ {path} בבית שלך ({size} תווים)",
                                     path=p["path"], size=len(p["content"]))),
    files=lambda p, c: [] if p["path"].endswith("/") else [c.user_path(p["path"])],
    capture=_way_file_capture,
    restore=_way_file_restore,
))


def way_timers(ctx: Context) -> list[tuple[str, dict]]:
    """(name, {"schedule": …, "sentence": …}) for every timer Diamond's Way installed."""
    out = []
    for path in sorted(ctx.user_path(WAY_DIR).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and WAY_NAME_RE.match(path.stem):
            out.append((path.stem, data))
    return out


def _way_effect(params: Params) -> str:
    try:
        requests = way_sentence_requests(params["sentence"])
    except ValidationError:
        return "neutral"
    effects = set()
    for request in requests:
        try:
            effects.add(CATALOG[request.action].effect(request.params))
        except (KeyError, TypeError, ValueError):     # the parser's raw params; validation happens at run time
            effects.add("neutral")
    return "weakens" if "weakens" in effects else ("hardens" if "hardens" in effects else "neutral")


def _way_summary(params: Params, lang: str) -> str:
    when = way_schedule(params["schedule"]).describe(lang)
    return _t(lang, "{when}: {sentence} (a timer, Diamond's Way)", "{when}: {sentence} (טיימר, דרך היהלום)",
              when=when, sentence=params["sentence"])


register(ActionSpec(
    id="way.when",
    scope="user",
    validate=_way_validate,
    apply=_way_apply,
    risk=lambda p: "low",
    effect=_way_effect,
    summary=_way_summary,
    files=_way_files,
    restore=_way_restore,
    note=lambda p, lang: _t(lang, "Runs as you, without questions; the sentence is parsed again at every run. Undo one run: dai-tune undo",
                            "רץ בשמך, בלי שאלות; המשפט מפורש מחדש בכל הרצה. ביטול הרצה אחת: dai-tune undo"),
))

register(ActionSpec(
    id="way.when_off",
    scope="user",
    validate=_way_off_validate,
    apply=_way_off_apply,
    risk=lambda p: "low",
    effect=lambda p: "neutral",
    summary=lambda p, lang: _t(lang, "Remove the timer {name} (Diamond's Way)", "הסרת הטיימר {name} (דרך היהלום)", name=p["name"]),
    files=_way_files,
    restore=_way_restore,
))
