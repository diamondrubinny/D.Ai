# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Prepare a computer for its new owner, and finish it on their first boot (docs/OEM.md).

  prepare  (the partner, as root)    pending: autologin into the setup wizard
  complete (the wizard, via polkit)  new encryption password, new admin user, hostname
  cleanup  (next boot, before SDDM)  remove the temporary and setup users
  cancel   (the partner, as root)    back to how it was before prepare

Every command runs without a shell; passwords only ever travel on stdin.
`Machine` takes a root folder and a runner so tests never touch the real system.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

STATE_DIR = "/var/lib/dai/oem"
STATE_FILE = f"{STATE_DIR}/state.json"
LUKS_KEY = f"{STATE_DIR}/luks-key"
SDDM_BACKUP = f"{STATE_DIR}/sddm.conf.orig"
SDDM_CONF = "/etc/sddm.conf"
SETUP_USER = "dai-setup"
SETUP_HOME = f"{STATE_DIR}/home"
SESSION = "dai-oem.desktop"
SESSION_TEMPLATE = "/usr/share/dai/oem/dai-oem.desktop"
# Local, admin-owned session folder that SDDM also reads; only present while pending.
SESSION_FILE = f"/usr/local/share/wayland-sessions/{SESSION}"
WORK_DIR = "/run/dai-oem"

USERNAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
HOSTNAME = re.compile(r"^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
RESERVED = {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp", "proxy",
            "www-data", "backup", "list", "irc", "nobody", "systemd-network", "messagebus", "sddm", "polkitd",
            "admin", "sudo", "users", "dai-setup", "oem"}
DEFAULT_GROUPS = ("sudo", "users", "audio", "video", "plugdev", "netdev", "bluetooth", "lpadmin", "scanner")


class OemError(RuntimeError):
    """Refused or failed; the message is safe to show (never contains a password)."""


@dataclass(frozen=True)
class Owner:
    """What the new owner chose in the wizard."""

    full_name: str
    username: str
    password: str
    hostname: str
    luks_password: str | None = None
    language: str = "he"


def validation_errors(owner: Owner, existing_users: set[str], needs_luks: bool) -> list[str]:
    """Keys of the problems (also used by the wizard to point at the field)."""
    problems = []
    if not owner.full_name.strip() or len(owner.full_name) > 80 or any(c in owner.full_name for c in ":,\n\r\t\x00"):
        problems.append("full_name")
    if not USERNAME.match(owner.username) or owner.username in RESERVED or owner.username in existing_users:
        problems.append("username")
    if not 8 <= len(owner.password) <= 256 or any(c in owner.password for c in "\n\r\x00"):
        problems.append("password")
    if not HOSTNAME.match(owner.hostname):
        problems.append("hostname")
    if needs_luks:
        if owner.luks_password is None or not 8 <= len(owner.luks_password) <= 512 \
                or any(c in owner.luks_password for c in "\n\r\x00"):
            problems.append("luks_password")
    if owner.language not in ("he", "en"):
        problems.append("language")
    return problems


def suggest_username(full_name: str) -> str:
    """"Dana Levi" → "dana"; Hebrew-only names give "" (the user types one)."""
    first = re.sub(r"[^a-z0-9-]", "", (full_name.strip().split() or [""])[0].lower())
    return first if USERNAME.match(first) and first not in RESERVED else ""


def run_command(argv: Sequence[str], data: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), input=data, capture_output=True, text=True, timeout=600, check=False,
                          env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})


@dataclass
class Machine:
    root: Path = Path("/")
    runner: Callable[..., subprocess.CompletedProcess] = run_command
    clock: Callable[[], float] = time.time
    log: list[str] = field(default_factory=list)

    # -- files and commands ----------------------------------------------------

    def path(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    def run(self, argv: Sequence[str], data: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        self.log.append(" ".join(argv))  # never the data: it may hold a password
        try:
            result = self.runner(argv, data)
        except FileNotFoundError:  # e.g. no ssh-keygen without openssh
            result = subprocess.CompletedProcess(list(argv), 127, "", f"{argv[0]}: not installed")
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-2:]
            raise OemError(f"{argv[0]} failed (exit {result.returncode}): {' '.join(detail)}")
        return result

    def write(self, absolute: str, content: str, mode: int = 0o644) -> None:
        path = self.path(absolute)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.dai-oem.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temp, mode)
        os.replace(temp, path)

    def shred(self, absolute: str) -> None:
        path = self.path(absolute)
        if path.exists():
            self.run(["shred", "-u", "-z", str(path)], check=False)
            if path.exists():
                path.unlink()

    # -- facts -------------------------------------------------------------------

    def users(self) -> dict[str, tuple[int, str]]:
        """name → (uid, home) from /etc/passwd."""
        found = {}
        try:
            lines = self.path("/etc/passwd").read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for line in lines:
            fields = line.split(":")
            if len(fields) >= 7 and fields[2].isdigit():
                found[fields[0]] = (int(fields[2]), fields[5])
        return found

    def groups_of(self, user: str) -> list[str]:
        groups = []
        try:
            lines = self.path("/etc/group").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            fields = line.split(":")
            if len(fields) >= 4 and user in fields[3].split(","):
                groups.append(fields[0])
        return groups

    def existing_groups(self) -> set[str]:
        try:
            return {line.split(":")[0] for line in self.path("/etc/group").read_text(encoding="utf-8").splitlines() if line}
        except OSError:
            return set()

    def luks_devices(self) -> list[str]:
        """Encrypted devices from /etc/crypttab (UUID= resolved to /dev/disk/by-uuid)."""
        devices = []
        try:
            lines = self.path("/etc/crypttab").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            fields = line.split()
            if len(fields) >= 2 and not fields[0].startswith("#"):
                source = fields[1]
                if source.startswith("UUID="):
                    source = f"/dev/disk/by-uuid/{source[5:]}"
                devices.append(source)
        return devices

    def state(self) -> dict:
        try:
            data = json.loads(self.path(STATE_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict) -> None:
        self.write(STATE_FILE, json.dumps(state, indent=1), mode=0o644)  # the wizard reads it (no secrets)

    # -- prepare (the partner) -----------------------------------------------------

    def prepare(self, remove_user: str, luks_password: str | None = None, allow_live: bool = False) -> dict:
        if self.path("/run/live").exists() and not allow_live:
            raise OemError("this is the live session: install D.Ai OS first, then run dai-oem prepare on it")
        if self.state().get("phase") == "pending":
            raise OemError("already prepared (dai-oem cancel undoes it)")
        users = self.users()
        uid = users.get(remove_user, (-1, ""))[0]
        if remove_user in (SETUP_USER, "root") or not 1000 <= uid < 60000:
            raise OemError(f"{remove_user!r} is not a regular user account to remove (--remove-user)")
        devices = self.luks_devices()
        if len(devices) > 1:
            raise OemError("more than one encrypted disk in /etc/crypttab: not supported yet (docs/OEM.md §4)")
        device = devices[0] if devices else None
        if device:
            if not luks_password:
                raise OemError("the temporary disk encryption password is needed")
            self.run(["cryptsetup", "open", "--test-passphrase", device], data=luks_password + "\n")
        self.path(STATE_DIR).mkdir(parents=True, exist_ok=True)
        os.chmod(self.path(STATE_DIR), 0o755)
        if device:
            # No newline: cryptsetup reads a key file as is. Inside the encrypted disk, root only.
            self.write(LUKS_KEY, luks_password, mode=0o600)

        if SETUP_USER not in users:
            self.run(["useradd", "--system", "--create-home", "--home-dir", SETUP_HOME, "--shell", "/bin/sh",
                      "--comment", "D.Ai first-boot setup", SETUP_USER])
        try:
            session = self.path(SESSION_TEMPLATE).read_text(encoding="utf-8")
        except OSError as exc:
            raise OemError(f"the setup session is missing ({SESSION_TEMPLATE})") from exc
        self.write(SESSION_FILE, session)
        sddm = self.path(SDDM_CONF)
        if sddm.exists():
            os.replace(sddm, self.path(SDDM_BACKUP))
        self.write(SDDM_CONF, "# Written by dai-oem prepare; removed when the new owner finishes the setup.\n"
                              f"[Autologin]\nUser={SETUP_USER}\nSession={SESSION}\nRelogin=true\n")
        self._reset_identity()
        state = {"phase": "pending", "remove_users": [remove_user], "luks": device, "prepared": int(self.clock())}
        self._save_state(state)
        return state

    def _reset_identity(self) -> None:
        """Nothing that identifies this unit or its preparation goes to the owner."""
        self.run(["apt-get", "clean"], check=False)
        self.run(["journalctl", "--rotate"], check=False)
        self.run(["journalctl", "--vacuum-time=1s"], check=False)
        self.write("/etc/machine-id", "", mode=0o444)  # empty: systemd makes a new one at boot
        dbus_id = self.path("/var/lib/dbus/machine-id")
        if dbus_id.exists() and not dbus_id.is_symlink():
            dbus_id.unlink()
        for key in self.path("/etc/ssh").glob("ssh_host_*"):
            key.unlink()

    # -- complete (the new owner, through the wizard) -------------------------------

    def complete(self, owner: Owner) -> None:
        state = self.state()
        if state.get("phase") != "pending":
            raise OemError("there is no setup waiting to be finished")
        device = state.get("luks")
        problems = validation_errors(owner, set(self.users()), needs_luks=bool(device) and not state.get("luks_done"))
        if problems:
            raise OemError(f"invalid: {', '.join(problems)}")
        # Encryption first: if it fails, nothing else has changed and the old password still works.
        if device and not state.get("luks_done"):
            self._change_luks(device, owner.luks_password or "")
            state["luks_done"] = True  # a retry after a later failure must not ask for the old password again
            self._save_state(state)
        groups = [g for g in dict.fromkeys([*DEFAULT_GROUPS, *self._partner_groups(state)]) if g in self.existing_groups()]
        self.run(["useradd", "--create-home", "--shell", "/bin/bash", "--comment", owner.full_name.strip(),
                  *(["--groups", ",".join(groups)] if groups else []), owner.username])
        self.run(["chpasswd"], data=f"{owner.username}:{owner.password}\n")
        self._set_hostname(owner.hostname)
        if owner.language == "he":  # i18n: ok (the new owner's system language)
            self.run(["localectl", "set-locale", "LANG=he_IL.UTF-8"], check=False)
        self._restore_sddm()
        state.update(phase="cleanup", owner=owner.username, completed=int(self.clock()))
        self._save_state(state)

    def _partner_groups(self, state: dict) -> list[str]:
        removed = state.get("remove_users") or []
        return [g for user in removed for g in self.groups_of(user) if g != user]

    def _change_luks(self, device: str, new_password: str) -> None:
        work = self.path(WORK_DIR)
        work.mkdir(mode=0o700, parents=True, exist_ok=True)
        new_key = f"{WORK_DIR}/new-key-{secrets.token_hex(4)}"
        self.write(new_key, new_password, mode=0o600)
        try:
            self.run(["cryptsetup", "luksChangeKey", "--force-password", "--key-file", str(self.path(LUKS_KEY)),
                      device, str(self.path(new_key))])
        finally:
            self.shred(new_key)
        self.run(["cryptsetup", "open", "--test-passphrase", device], data=new_password + "\n")
        self.shred(LUKS_KEY)

    def _set_hostname(self, hostname: str) -> None:
        self.write("/etc/hostname", f"{hostname}\n")
        hosts = self.path("/etc/hosts")
        try:
            lines = hosts.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = ["127.0.0.1\tlocalhost"]
        lines = [line for line in lines if not line.startswith("127.0.1.1")]
        lines.insert(1 if lines else 0, f"127.0.1.1\t{hostname}")
        self.write("/etc/hosts", "\n".join(lines) + "\n")
        self.run(["hostnamectl", "set-hostname", hostname], check=False)

    def _restore_sddm(self) -> None:
        self.path(SESSION_FILE).unlink(missing_ok=True)
        backup = self.path(SDDM_BACKUP)
        if backup.exists():
            os.replace(backup, self.path(SDDM_CONF))
        else:
            self.path(SDDM_CONF).unlink(missing_ok=True)

    # -- cleanup (next boot) and cancel (the partner) ----------------------------------

    def cleanup(self) -> bool:
        state = self.state()
        if state.get("phase") != "cleanup":
            return False
        for user in [*state.get("remove_users", []), SETUP_USER]:
            if user in self.users() and user != state.get("owner"):
                self.run(["pkill", "-KILL", "-u", user], check=False)
                self.run(["userdel", "--remove", user], check=False)
        if self.path("/etc/ssh").is_dir():
            self.run(["ssh-keygen", "-A"], check=False)
        self._forget()
        return True

    def cancel(self) -> None:
        if self.state().get("phase") != "pending":
            raise OemError("nothing to cancel")
        self._restore_sddm()
        if SETUP_USER in self.users():
            self.run(["userdel", "--remove", SETUP_USER], check=False)
        self._forget()

    def _forget(self) -> None:
        self.shred(LUKS_KEY)
        for name in ("state.json",):
            self.path(f"{STATE_DIR}/{name}").unlink(missing_ok=True)
