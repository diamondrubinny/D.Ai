# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Diamond Chat background service (`dai-chat run`, a user systemd unit while Chat is on).

  - receives only when the person turned receiving on (off by default): only then does it listen on
    127.0.0.1 (where the onion service forwards) or, with the local network on, on every address (the
    firewall opens the port only to the local network: docs/SEND.md §3), publish the onion service and
    announce itself on the local network; until then, messages to this person wait on their senders' computers;
  - starts the person's Tor (tor.py), for sending even while receiving is off;
  - every half minute, and at once when the window or the command line says so, tries to deliver what is
    queued and to finish pairings: the local network first, then Tor, waiting longer after each failure;
  - says "a new message from Dana" (never the message itself: the screen may be seen by others).

The window and the command line write into the same store and then "poke" the service through a Unix
socket in the user's private runtime folder.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import message as msg
from . import transport
from .discovery import Discovery, short
from .keys import Identity
from .pairing import clean_name
from .store import Contact, Store
from .tor import Tor, TorError

ROUND = 30.0
MAX_WAIT = 15 * 60.0


@dataclass
class Settings:
    lan: bool = False  # off until the person turns it on (it opens a port to the local network)
    tor: bool = True
    receive: bool = False  # off until the person turns it on: nobody can reach them before that
    name: str = ""  # the display name contacts see; chosen by the person, never the computer's user name

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        name = data.get("name") if isinstance(data.get("name"), str) else ""
        return cls(lan=data.get("lan") is True, tor=data.get("tor") is not False,
                   receive=data.get("receive") is True, name=clean_name(name))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"lan": self.lan, "tor": self.tor, "receive": self.receive, "name": clean_name(self.name)}
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def settings_path(environ: dict | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".config")
    return Path(base) / "dai" / "chat.json"


def lan_address() -> str:
    """This computer's address on the local network (a UDP connect sends nothing), or "" when offline."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: only picks the route
            return probe.getsockname()[0]
    except OSError:
        return ""


@dataclass
class Backoff:
    """After each failure, wait twice as long (30 s, 1 min, 2 min ... 15 min); a poke starts again."""

    due: dict = field(default_factory=dict)
    wait: dict = field(default_factory=dict)

    def ready(self, key, now: float) -> bool:
        return self.due.get(key, 0.0) <= now

    def failed(self, key, now: float) -> None:
        self.wait[key] = min(self.wait.get(key, ROUND / 2) * 2, MAX_WAIT)
        self.due[key] = now + self.wait[key]

    def succeeded(self, key) -> None:
        self.due.pop(key, None)
        self.wait.pop(key, None)

    def reset(self) -> None:
        self.due.clear()
        self.wait.clear()


def notify(contact: Contact, state: str = "delivered", run: Callable = subprocess.Popen) -> None:
    """A notification that says who wrote, not what (the screen may be shared), and the diamond chime."""
    from dai_i18n import text, ui_lang

    lang = ui_lang()
    if state == "request":
        words = text(lang, "{name} sent a message. Open Diamond Chat to accept or decline.",
                     "‏{name} שלחו הודעה. פתחו את Diamond Chat כדי לאשר או לדחות.", name=contact.name)
    elif state == "held":
        words = text(lang, "A message from {name} was held: it looks suspicious.",
                     "הודעה מאת {name} עוכבה: היא נראית חשודה.", name=contact.name)
    else:
        words = text(lang, "A new message from {name}", "הודעה חדשה מאת {name}", name=contact.name)
    try:
        run(["notify-send", "--app-name=Diamond Chat", "--icon=internet-chat", "Diamond Chat", words],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run(["dai-sound", "message-new-instant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class Service:
    def __init__(self, me: Identity, onion_seed: bytes, store: Store, settings: Settings,
                 tor_runner: Tor | None = None, discovery: Discovery | None = None,
                 on_message: Callable[[Contact, str], None] = notify, port: int = transport.PORT,
                 clock: Callable[[], float] = time.monotonic) -> None:
        from nacl.signing import SigningKey

        self.me, self.store, self.settings, self.port, self.clock = me, store, settings, port, clock
        self.onion_seed = onion_seed
        self.service_public = bytes(SigningKey(onion_seed).verify_key)
        self.tor = tor_runner if settings.tor else None
        self.discovery = discovery if settings.lan else None
        self.on_message = on_message
        self.node = transport.Node(me, store, self._arrived, service=self.service_public, name=settings.name,
                                   accepting=lambda: self.settings.receive)
        self.chat_server = None
        self.backoff = Backoff()
        self.tor_state = "off" if self.tor is None else "starting"
        self.poked = asyncio.Event()
        self.servers: list = []

    def _arrived(self, peer: bytes, message: msg.Message, state: str) -> None:
        contact = self.store.contact(peer)
        if contact is not None:
            self.on_message(contact, state)

    # where a contact or a code can be reached, best first
    def routes(self, fpr: bytes, onion: str) -> list[transport.Connect]:
        found = [transport.tcp(seen.host, seen.port) for seen in self.discovery.find(fpr)] if self.discovery else []
        if self.tor is not None and self.tor_state == "online" and onion:
            found.append(transport.tor(onion, str(self.tor.paths.socks), self.port))
        return found

    async def round(self) -> None:
        now = self.clock()
        for theirs, _name in self.store.waiting():
            key = ("pair", theirs.fingerprint)
            if self.backoff.ready(key, now):
                await self._try(key, self.routes(theirs.fingerprint, theirs.onion),
                                lambda route, theirs=theirs: self.node.pair(theirs, route))
        for contact in self.store.contacts():
            key = ("send", contact.public)
            if contact.blocked or not self.store.queued(contact.public) or not self.backoff.ready(key, now):
                continue
            await self._try(key, self.routes(short(contact.public), contact.onion),
                            lambda route, contact=contact: self.node.deliver(contact.public, route))

    async def _try(self, key, routes, attempt) -> bool:
        for route in routes:
            try:
                result = await attempt(route)
            except transport.TransportError:
                continue
            if getattr(result, "deferred", None):  # they are not receiving now: try again later, not at once
                break
            self.backoff.succeeded(key)
            return True
        self.backoff.failed(key, self.clock())
        return False

    # the control socket: {"op": "poke" | "status"}, one JSON line each way
    async def _control(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            request = json.loads(line or b"{}")
            if request.get("op") == "poke":
                self.backoff.reset()
                self.poked.set()
                reply = {"ok": True}
            elif request.get("op") == "status":
                reply = {"ok": True, **self.status()}
            else:
                reply = {"ok": False}
            writer.write(json.dumps(reply).encode() + b"\n")
            await writer.drain()
        except (ValueError, AttributeError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    def status(self) -> dict:
        return {"tor": self.tor_state, "lan": self.discovery is not None, "receive": self.settings.receive,
                "requests": self.store.waiting_count(),
                "onion": self.tor.address if self.tor is not None else "",
                "waiting": len(self.store.waiting()),
                "queued": sum(len(self.store.queued(c.public)) for c in self.store.contacts())}

    async def start(self, control_path: Path) -> None:
        if self.settings.receive:
            host = "0.0.0.0" if self.discovery is not None else "127.0.0.1"
            self.chat_server = await asyncio.start_server(self.node.handle, host, self.port, limit=2 ** 16)
            self.servers.append(self.chat_server)
        control_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        control_path.unlink(missing_ok=True)
        old = os.umask(0o177)
        try:
            self.servers.append(await asyncio.start_unix_server(self._control, str(control_path)))
        finally:
            os.umask(old)
        if self.discovery is not None:
            address = lan_address()
            if address:
                await asyncio.to_thread(self.discovery.start, address, self.settings.receive)
        if self.tor is not None:
            asyncio.ensure_future(self._start_tor())

    async def _start_tor(self) -> None:
        try:
            await asyncio.to_thread(self.tor.start)
            if self.settings.receive:  # reachable at the onion address only while receiving is on
                await asyncio.to_thread(self.tor.publish, self.onion_seed)
            self.tor_state = "connecting"
            online = await asyncio.to_thread(self.tor.wait_online, 300)
            self.tor_state = "online" if online else "offline"
        except (TorError, OSError):
            self.tor_state = "failed"
        self.poked.set()

    async def run_forever(self, control_path: Path) -> None:
        await self.start(control_path)
        try:
            while True:
                await self.round()
                if self.discovery is not None:
                    address = lan_address()
                    if address:
                        await asyncio.to_thread(self.discovery.refresh, address)
                try:
                    await asyncio.wait_for(self.poked.wait(), ROUND)
                except asyncio.TimeoutError:
                    pass
                self.poked.clear()
        finally:
            self.stop()

    def stop(self) -> None:
        for server in self.servers:
            server.close()
        if self.discovery is not None:
            self.discovery.stop()
        if self.tor is not None:
            self.tor.stop()


def invite_code(onion_seed: bytes, identity: Identity) -> str:
    from nacl.signing import SigningKey

    from .invite import make

    return make(bytes(SigningKey(onion_seed).verify_key), identity.public)


def poke(control_path: Path, op: str = "poke") -> dict | None:
    """Tells a running service to look at the store now; None when it is not running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(control_path))
            sock.sendall(json.dumps({"op": op}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        return json.loads(data or b"null")
    except (OSError, ValueError):
        return None

