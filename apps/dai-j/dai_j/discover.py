# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""An account from an e-mail address only (docs/MAIL.md §3.2).

In order: a few well-known providers, the provider's own autoconfig file
(HTTPS only), Mozilla's public ISPDB, DNS SRV records (RFC 6186/8314), MX
records (Google Workspace, Microsoft 365) and finally a careful guess.
Every result uses TLS; a server offered without encryption is skipped.
Network access goes through `fetch` and `resolve` so it can be tested.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Callable

HOSTNAME = re.compile(r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$")
ADDRESS = re.compile(r"^[^@\s]{1,64}@([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$")
MAX_BYTES = 64 * 1024

Fetch = Callable[[str], bytes | None]
Resolve = Callable[[str, str], list[tuple[int, str, int]]]   # (name, "SRV"|"MX") -> [(priority, host, port)]


@dataclass
class Server:
    host: str
    port: int
    security: str            # "ssl" (TLS from the start) or "starttls"
    username: str
    oauth_only: bool = False  # the provider accepts only OAuth sign-in (docs/MAIL.md §3.3, stage 3)


@dataclass
class Settings:
    address: str
    incoming: Server
    outgoing: Server
    source: str              # where the settings came from, shown to the user
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def valid_address(address: str) -> bool:
    return bool(ADDRESS.match(address.strip()))


# The biggest providers, so the common case works even when the lookups are slow.
KNOWN = {
    "gmail.com": ("imap.gmail.com", 993, "ssl", "smtp.gmail.com", 465, "ssl", False),
    "googlemail.com": ("imap.gmail.com", 993, "ssl", "smtp.gmail.com", 465, "ssl", False),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "ssl", "smtp.mail.yahoo.com", 465, "ssl", False),
    "icloud.com": ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls", False),
    "me.com": ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls", False),
    # Microsoft's personal accounts accept only OAuth for IMAP (docs/MAIL.md §3.3).
    "outlook.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls", True),
    "hotmail.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls", True),
    "live.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls", True),
}
GOOGLE_MX = ("google.com", "googlemail.com")
MICROSOFT_MX = ("mail.protection.outlook.com",)


def _https_fetch(url: str) -> bytes | None:
    if not url.startswith("https://"):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "D.Ai-J/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 - https only, checked above
            return response.read(MAX_BYTES + 1)[:MAX_BYTES]
    except (OSError, ValueError):
        return None


def _dns_resolve(name: str, kind: str) -> list[tuple[int, str, int]]:
    try:
        import dns.resolver  # python3-dnspython, optional
    except ImportError:
        return []
    try:
        answers = dns.resolver.resolve(name, kind, lifetime=5)
    except Exception:  # noqa: BLE001 - NXDOMAIN, timeouts, no answer: all mean "nothing here"
        return []
    if kind == "SRV":
        return sorted((a.priority, str(a.target).rstrip("."), int(a.port)) for a in answers)
    return sorted((a.preference, str(a.exchange).rstrip("."), 0) for a in answers)


def _username(template: str, address: str) -> str:
    local, domain = address.split("@", 1)
    return (template or "%EMAILADDRESS%").replace("%EMAILADDRESS%", address).replace(
        "%EMAILLOCALPART%", local).replace("%EMAILDOMAIN%", domain)


def parse_autoconfig(xml: bytes, address: str) -> tuple[Server, Server] | None:
    """The first encrypted IMAP and SMTP servers of a Mozilla autoconfig file."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    def pick(tag: str, kind: str) -> Server | None:
        for node in root.iter(tag):
            if node.get("type") != kind:
                continue
            host = (node.findtext("hostname") or "").strip()
            socket = (node.findtext("socketType") or "").strip().upper()
            port = (node.findtext("port") or "").strip()
            auth = [(a.text or "").strip() for a in node.findall("authentication")]
            if not HOSTNAME.match(host) or not port.isdigit() or not 0 < int(port) < 65536:
                continue
            if socket not in ("SSL", "STARTTLS"):
                continue  # never without encryption
            oauth_only = bool(auth) and all(a == "OAuth2" for a in auth)
            return Server(host.lower(), int(port), "ssl" if socket == "SSL" else "starttls",
                          _username((node.findtext("username") or "").strip(), address), oauth_only)
        return None

    incoming, outgoing = pick("incomingServer", "imap"), pick("outgoingServer", "smtp")
    return (incoming, outgoing) if incoming and outgoing else None


def _known(domain: str, address: str) -> tuple[Server, Server] | None:
    row = KNOWN.get(domain)
    if row is None:
        return None
    ih, ip, isec, oh, op, osec, oauth = row
    return Server(ih, ip, isec, address, oauth), Server(oh, op, osec, address, oauth)


def discover(address: str, fetch: Fetch = _https_fetch, resolve: Resolve = _dns_resolve) -> Settings | None:
    address = address.strip()
    if not valid_address(address):
        return None
    domain = address.split("@", 1)[1].lower()
    quoted = urllib.parse.quote(address, safe="@")

    found = _known(domain, address)
    if found:
        return _settings(address, found, "known")

    for url, source in ((f"https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={quoted}", "autoconfig"),
                        (f"https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml", "autoconfig"),
                        (f"https://autoconfig.thunderbird.net/v1.1/{domain}", "ispdb")):
        body = fetch(url)
        found = parse_autoconfig(body, address) if body else None
        if found:
            return _settings(address, found, source)

    imap = [r for r in resolve(f"_imaps._tcp.{domain}", "SRV") if HOSTNAME.match(r[1])]
    smtp = [(r, "ssl") for r in resolve(f"_submissions._tcp.{domain}", "SRV") if HOSTNAME.match(r[1])]
    smtp += [(r, "starttls") for r in resolve(f"_submission._tcp.{domain}", "SRV") if HOSTNAME.match(r[1])]
    if imap and smtp:
        (_, ih, ip), ((_, oh, op), osec) = imap[0], smtp[0]
        return _settings(address, (Server(ih.lower(), ip, "ssl", address), Server(oh.lower(), op, osec, address)), "dns")

    for _, exchange, _ in resolve(domain, "MX"):
        exchange = exchange.lower()
        if exchange.endswith(GOOGLE_MX):
            return _settings(address, _known("gmail.com", address), "mx-google")
        if exchange.endswith(MICROSOFT_MX):
            return _settings(address, _known("outlook.com", address), "mx-microsoft")

    guess = (Server(f"imap.{domain}", 993, "ssl", address), Server(f"smtp.{domain}", 465, "ssl", address))
    return _settings(address, guess, "guess")


def _settings(address: str, servers: tuple[Server, Server], source: str) -> Settings:
    incoming, outgoing = servers
    notes = []
    if incoming.oauth_only or outgoing.oauth_only:
        notes.append("oauth")
    if incoming.host.endswith("gmail.com"):
        notes.append("app_password")
    if source == "guess":
        notes.append("guess")
    return Settings(address, incoming, outgoing, source, notes)
