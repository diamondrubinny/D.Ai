# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Account settings from the mail apps already on this computer (docs/MAIL.md §3.1, stage 2).

Read-only: nothing in the other app is changed. Passwords are never taken:
J asks for them (or uses the keyring) when it first signs in. An account the
other app reaches only through OAuth is marked, since J signs in with a
password for now. Only encrypted servers are offered; an account the other
app used without encryption is skipped and shown as such.

  Thunderbird / Betterbird   prefs.js of every profile (also Flatpak and Snap installs)
  Evolution                  ~/.config/evolution/sources/*.source
  Claws Mail                 ~/.claws-mail/accountrc
  Mutt / NeoMutt             muttrc (imap and smtp URLs)
"""

from __future__ import annotations

import configparser
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from .discover import ADDRESS, HOSTNAME, Server

PREF = re.compile(r'^\s*user_pref\("([^"]+)",\s*("(?:[^"\\]|\\.)*"|-?\d+|true|false)\);', re.M)


@dataclass
class Found:
    source: str               # thunderbird, betterbird, evolution, claws, mutt
    address: str
    name: str
    incoming: Server | None
    outgoing: Server | None
    notes: list[str] = field(default_factory=list)   # oauth, insecure, no-outgoing

    @property
    def usable(self) -> bool:
        return self.incoming is not None and self.outgoing is not None and "insecure" not in self.notes


def _port(value, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def _server(host: str, port, security: str | None, user: str, oauth: bool = False) -> Server | None:
    host = (host or "").strip().lower()
    if not HOSTNAME.match(host) or security not in ("ssl", "starttls"):
        return None
    return Server(host, _port(port, 993 if security == "ssl" else 143), security, user, oauth)


# Thunderbird and Betterbird

def _mozilla_prefs(text: str) -> dict[str, str]:
    prefs = {}
    for name, value in PREF.findall(text):
        prefs[name] = value[1:-1].replace('\\"', '"').replace("\\\\", "\\") if value.startswith('"') else value
    return prefs


def _mozilla_security(value: str) -> str | None:
    return {"3": "ssl", "2": "starttls"}.get(value)    # 0 and 1: no encryption


def thunderbird_profiles(home: Path) -> list[tuple[str, Path]]:
    roots = [("thunderbird", home / ".thunderbird"),
             ("thunderbird", home / ".var/app/org.mozilla.Thunderbird/.thunderbird"),
             ("thunderbird", home / "snap/thunderbird/common/.thunderbird"),
             ("betterbird", home / ".thunderbird-betterbird"), ("betterbird", home / ".betterbird"),
             ("betterbird", home / ".var/app/eu.betterbird.Betterbird/.thunderbird")]
    found = []
    for source, root in roots:
        for prefs in sorted(root.glob("*/prefs.js")) if root.is_dir() else []:
            found.append((source, prefs))
    return found


def from_mozilla(source: str, prefs_file: Path) -> list[Found]:
    try:
        prefs = _mozilla_prefs(prefs_file.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    accounts = []
    for key in sorted(k for k in prefs if re.fullmatch(r"mail\.account\.[^.]+\.server", k)):
        account = key.split(".")[2]
        server = prefs[key]
        base = f"mail.server.{server}."
        if prefs.get(base + "type") != "imap":
            continue  # local folders, POP3, news and feeds stay where they are
        identity = (prefs.get(f"mail.account.{account}.identities", "").split(",") or [""])[0]
        address = prefs.get(f"mail.identity.{identity}.useremail", "")
        if not ADDRESS.match(address):
            continue
        oauth = prefs.get(base + "authMethod") == "10"
        notes = ["oauth"] if oauth else []
        security = _mozilla_security(prefs.get(base + "socketType", "0"))
        incoming = _server(prefs.get(base + "hostname", ""), prefs.get(base + "port"), security,
                           prefs.get(base + "userName", address), oauth)
        smtp = prefs.get(f"mail.identity.{identity}.smtpServer") or prefs.get("mail.smtp.defaultserver", "")
        sbase = f"mail.smtpserver.{smtp}."
        outgoing = _server(prefs.get(sbase + "hostname", ""), prefs.get(sbase + "port") or 587,
                           _mozilla_security(prefs.get(sbase + "try_ssl", "0")), prefs.get(sbase + "username", address),
                           prefs.get(sbase + "authMethod") == "10")
        if incoming is None or outgoing is None:
            notes.append("insecure" if prefs.get(base + "hostname") else "incomplete")
        accounts.append(Found(source, address, prefs.get(f"mail.identity.{identity}.fullName", ""), incoming, outgoing,
                              notes))
    return accounts


# Evolution

def _keyfile(path: Path) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, configparser.Error):
        pass
    return parser


def _evolution_security(method: str) -> str | None:
    return {"ssl-on-alternate-port": "ssl", "starttls-on-standard-port": "starttls"}.get(method)


def from_evolution(home: Path) -> list[Found]:
    directory = home / ".config/evolution/sources"
    sources = {p.stem: _keyfile(p) for p in sorted(directory.glob("*.source"))} if directory.is_dir() else {}
    accounts = []
    for uid, source in sources.items():
        if source.get("Mail Account", "BackendName", fallback="") != "imapx":
            continue
        identity = sources.get(source.get("Mail Account", "IdentityUid", fallback=""))
        if identity is None:
            continue
        address = identity.get("Mail Identity", "Address", fallback="")
        if not ADDRESS.match(address):
            continue
        transport = sources.get(identity.get("Mail Submission", "TransportUid", fallback=""))
        oauth = source.get("Authentication", "Method", fallback="").startswith("OAuth2")
        incoming = _server(source.get("Authentication", "Host", fallback=""), source.get("Authentication", "Port",
                           fallback=None), _evolution_security(source.get("Security", "Method", fallback="none")),
                           source.get("Authentication", "User", fallback=address), oauth)
        outgoing = None
        if transport is not None:
            outgoing = _server(transport.get("Authentication", "Host", fallback=""),
                               transport.get("Authentication", "Port", fallback=None),
                               _evolution_security(transport.get("Security", "Method", fallback="none")),
                               transport.get("Authentication", "User", fallback=address))
        notes = ["oauth"] if oauth else []
        if incoming is None or outgoing is None:
            notes.append("insecure")
        accounts.append(Found("evolution", address, identity.get("Mail Identity", "Name", fallback=""), incoming,
                              outgoing, notes))
    return accounts


# Claws Mail

def from_claws(home: Path) -> list[Found]:
    parser = _keyfile(home / ".claws-mail/accountrc")
    accounts = []
    for section in parser.sections():
        if not section.startswith("Account:"):
            continue
        get = lambda k, d="": parser.get(section, k, fallback=d)  # noqa: E731
        if get("protocol") != "3":   # 3 is IMAP in Claws (0 is POP3) ⚠ docs/MAIL.md
            continue
        address = get("address")
        if not ADDRESS.match(address):
            continue
        imap_security = {"1": "ssl", "2": "starttls"}.get(get("ssl_imap", "0"))
        smtp_security = {"1": "ssl", "2": "starttls"}.get(get("ssl_smtp", "0"))
        incoming = _server(get("receive_server"), get("imap_port") if get("set_imapport") == "1" else None,
                           imap_security, get("user_id", address))
        outgoing = _server(get("smtp_server"), get("smtp_port") if get("set_smtpport") == "1" else
                           (465 if smtp_security == "ssl" else 587), smtp_security, get("smtp_user_id") or
                           get("user_id", address))
        notes = [] if incoming and outgoing else ["insecure"]
        accounts.append(Found("claws", address, get("name"), incoming, outgoing, notes))
    return accounts


# Mutt and NeoMutt

SET = re.compile(r'^\s*set\s+([a-z_]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))', re.M)


def from_mutt(home: Path) -> list[Found]:
    for path in (home / ".neomuttrc", home / ".config/neomutt/neomuttrc", home / ".muttrc", home / ".config/mutt/muttrc"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        values = {m[0]: m[1] or m[2] or m[3] for m in SET.findall(text)}
        address = values.get("from", "")
        name, _, rest = address.rpartition("<")
        address = rest.rstrip(">").strip() if rest else address
        folder = urllib.parse.urlsplit(values.get("folder", "") or values.get("spoolfile", ""))
        smtp = urllib.parse.urlsplit(values.get("smtp_url", ""))
        address = address or values.get("imap_user", "")
        if not ADDRESS.match(address):
            continue
        incoming = _server(folder.hostname or "", folder.port, {"imaps": "ssl"}.get(folder.scheme),
                           values.get("imap_user") or urllib.parse.unquote(folder.username or "") or address)
        outgoing = _server(smtp.hostname or "", smtp.port or (465 if smtp.scheme == "smtps" else 587),
                           {"smtps": "ssl", "smtp": "starttls" if values.get("ssl_starttls", "yes") != "no" else None}
                           .get(smtp.scheme), urllib.parse.unquote(smtp.username or "") or address)
        notes = [] if incoming and outgoing else ["insecure"]
        return [Found("mutt", address, name.strip().strip('"'), incoming, outgoing, notes)]
    return []


def find_all(home: Path | None = None) -> list[Found]:
    """Every account in every mail app found here, once per address (the first app wins)."""
    home = home or Path.home()
    found: list[Found] = []
    for source, prefs in thunderbird_profiles(home):
        found += from_mozilla(source, prefs)
    found += from_evolution(home) + from_claws(home) + from_mutt(home)
    seen, unique = set(), []
    for account in found:
        if account.address.lower() not in seen:
            seen.add(account.address.lower())
            unique.append(account)
    return unique
