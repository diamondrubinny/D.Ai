# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Finding contacts on the same network with mDNS (python3-zeroconf), without telling strangers who you are.

Each computer announces "_dai-chat._tcp" with a random instance name and one TXT value, a tag:

  tag = BLAKE2b(key = identity public key, data = the current hour, person "dai-chat-mdns")[:8], in hex

Your contacts know your public key, so they can work out this hour's tag and find you. Someone else on the
network sees only that a D.Ai Chat is there, under a name and tag that change every hour (and at every start),
so they cannot follow one computer over days. The address found is only a hint: the handshake still has to
prove the identity (session.py).
"""
from __future__ import annotations

import secrets
import socket
import time
from dataclasses import dataclass
from typing import Callable

from nacl.encoding import RawEncoder
from nacl.hash import blake2b

SERVICE = "_dai-chat._tcp.local."
HOUR = 3600


def tag(public: bytes, when: float | None = None) -> str:
    hour = int((time.time() if when is None else when) // HOUR)
    return blake2b(hour.to_bytes(8, "big"), key=public, digest_size=8, person=b"dai-chat-mdns",
                   encoder=RawEncoder).hex()


def tags_now(public: bytes, when: float | None = None) -> set[str]:
    """This hour's tag and the last hour's, so clocks a little apart still find each other."""
    now = time.time() if when is None else when
    return {tag(public, now), tag(public, now - HOUR), tag(public, now + HOUR)}


@dataclass(frozen=True)
class Seen:
    tag: str
    host: str
    port: int


class Discovery:
    """Announces this computer and remembers who else announced, until stopped."""

    def __init__(self, public: bytes, port: int, zeroconf_factory: Callable | None = None) -> None:
        self.public, self.port = public, port
        self.factory = zeroconf_factory
        self.seen: dict[str, Seen] = {}
        self.zc = self.info = self.browser = None
        self.announced_tag = ""

    def start(self, address: str) -> None:
        from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf  # python3-zeroconf

        self.zc = (self.factory or (lambda: Zeroconf(ip_version=IPVersion.V4Only)))()
        self._announce(ServiceInfo, address)
        self.browser = ServiceBrowser(self.zc, SERVICE, listener=self)

    def _announce(self, service_info, address: str) -> None:
        self.announced_tag = tag(self.public)
        name = f"{secrets.token_hex(6)}.{SERVICE}"  # never the computer's or the person's name
        self.info = service_info(SERVICE, name, addresses=[socket.inet_aton(address)], port=self.port,
                                 properties={"t": self.announced_tag})
        self.zc.register_service(self.info)

    def refresh(self, address: str) -> None:
        """Called every few minutes: a new hour means a new tag and a new name."""
        if self.zc is None or tag(self.public) == self.announced_tag:
            return
        from zeroconf import ServiceInfo

        self.zc.unregister_service(self.info)
        self._announce(ServiceInfo, address)

    def find(self, contact: bytes) -> list[Seen]:
        wanted = tags_now(contact)
        return [seen for seen in self.seen.values() if seen.tag in wanted]

    # zeroconf's ServiceListener
    def add_service(self, zc, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=3000)
        if info is None or (self.info is not None and name == self.info.name):
            return
        found = (info.properties or {}).get(b"t", b"")
        addresses = info.parsed_addresses()
        if isinstance(found, bytes) and len(found) == 16 and addresses and 0 < (info.port or 0) < 65536:
            self.seen[name] = Seen(found.decode("ascii", "replace"), addresses[0], info.port)

    update_service = add_service

    def remove_service(self, zc, type_: str, name: str) -> None:
        self.seen.pop(name, None)

    def stop(self) -> None:
        if self.zc is not None:
            if self.info is not None:
                self.zc.unregister_service(self.info)
            self.zc.close()
        self.zc = self.info = self.browser = None
