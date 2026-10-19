# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""How two D.Ai computers talk (docs/SEND.md §0): the same exchange over the local network or over Tor.

On the wire every frame is   length (4 bytes, big-endian) | bytes
  1. the initiator sends the HELLO, the responder the REPLY (session.py);
  2. then both sides, at the same time, send their queued messages as encrypted frames (message.py), answer
     each text or picture with a receipt, and say BYE when everything they sent was answered;
  3. the connection closes when both said BYE, or after a quiet minute.

Rules that hold whoever connects:
  - only a known, unblocked contact gets through the handshake (store.may_talk);
  - a picture from a contact whose six symbols were not compared yet is refused (docs/SEND.md §0);
  - a receipt only changes a message that was sent to the contact who sends it (store.set_state);
  - a broken frame ends the connection: nothing that failed its check is kept;
  - each address gets a few handshakes a minute, then is told nothing.

Tor is reached through its SOCKS port (a Unix socket in the user's runtime folder, tor.py), so nothing here
knows an IP address for an onion contact.
"""
from __future__ import annotations

import asyncio
import re
import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from . import message as msg
from . import pairing, pictures
from .invite import FPR_SIZE, Invite
from .keys import Identity, fingerprint
from .session import HELLO_SIZE, MAX_MESSAGE, REPLY_SIZE, HandshakeError, Initiator, Responder, Session, SessionError
from .store import Contact, Store

PORT = 7714  # the local-network port (chosen for D.Ai, not registered with IANA)
HANDSHAKE_TIMEOUT = 30.0  # Tor circuits can take a while
IDLE_TIMEOUT = 60.0
ATTEMPTS_PER_MINUTE = 10

Connect = Callable[[], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


class TransportError(Exception):
    """The connection broke, timed out or carried something that is not Diamond Chat."""


async def read_frame(reader: asyncio.StreamReader, limit: int, timeout: float) -> bytes:
    try:
        size = struct.unpack(">I", await asyncio.wait_for(reader.readexactly(4), timeout))[0]
        if size > limit:
            raise TransportError("frame too large")
        return await asyncio.wait_for(reader.readexactly(size), timeout)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError) as exc:
        raise TransportError("the connection ended") from exc


def write_frame(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(struct.pack(">I", len(data)) + data)


@dataclass
class Result:
    """What one connection did: for the window, the notifications and the tests."""

    peer: bytes = b""
    sent: list[str] = field(default_factory=list)  # ids the contact confirmed
    received: list[msg.Message] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)  # ids we refused, or the contact refused


class RateLimit:
    def __init__(self, per_minute: int = ATTEMPTS_PER_MINUTE, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute, self.clock = per_minute, clock
        self.seen: dict[str, deque] = defaultdict(deque)

    def allow(self, address: str) -> bool:
        now, times = self.clock(), self.seen[address]
        while times and now - times[0] > 60:
            times.popleft()
        if len(times) >= self.per_minute:
            return False
        times.append(now)
        return True


class Node:
    """One person's Diamond Chat: answers contacts who connect and delivers the queue to them."""

    def __init__(self, me: Identity, store: Store, on_message: Callable[[bytes, msg.Message], None] | None = None,
                 idle_timeout: float = IDLE_TIMEOUT, service: bytes = b"",
                 on_paired: Callable[[Contact], None] | None = None,
                 clean: Callable[[bytes], tuple[bytes, str]] | None = None) -> None:
        """`service` is the public key of our onion service, the one in our invitation code; `clean` re-draws
        a received picture in the sandbox (pictures.py)."""
        self.me, self.store, self.on_message = me, store, on_message
        self.service, self.on_paired = service, on_paired
        self.clean = clean or (lambda data: pictures.clean(data, scan_first=True))
        self.idle_timeout = idle_timeout
        self.limit = RateLimit()

    # the responder side: a contact connected to us
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> Result | None:
        peer_address = writer.get_extra_info("peername")
        address = peer_address[0] if isinstance(peer_address, tuple) else "local"  # Tor arrives on a Unix socket
        try:
            if not self.limit.allow(address):
                return None
            hello = await read_frame(reader, max(HELLO_SIZE, pairing.PAIR_SIZE), HANDSHAKE_TIMEOUT)
            if hello[:1] == pairing.MARK:
                await self._answer_pairing(hello, writer)
                return None
            reply, session = Responder(self.me, self.store.may_talk).answer(hello)
            write_frame(writer, reply)
            await writer.drain()
            return await self._exchange(session, reader, writer)
        except (HandshakeError, pairing.PairingError, TransportError, ConnectionError):
            return None  # a stranger or a broken connection learns nothing more
        finally:
            await _close(writer)

    async def _answer_pairing(self, frame: bytes, writer: asyncio.StreamWriter) -> None:
        if not self.service:
            raise pairing.PairingError("pairing is not on")
        ack, public, _service = pairing.answer(self.me, self.service, frame, self.store.waiting_for)
        write_frame(writer, ack)
        await writer.drain()
        contact = self.store.paired(fingerprint(public)[:FPR_SIZE], public)
        if contact and self.on_paired:
            self.on_paired(contact)

    async def pair(self, theirs: Invite, connect: Connect) -> Contact:
        """We typed their code (store.wait_for); they typed ours. Swap keys and become contacts."""
        if not self.service:
            raise TransportError("pairing is not on")
        try:
            reader, writer = await asyncio.wait_for(connect(), HANDSHAKE_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as exc:
            raise TransportError("the contact is not reachable") from exc
        try:
            write_frame(writer, pairing.request(self.me, self.service, theirs))
            await writer.drain()
            public = pairing.finish(self.me, theirs, await read_frame(reader, pairing.ACK_SIZE, HANDSHAKE_TIMEOUT))
        except pairing.PairingError as exc:
            raise TransportError("the answer does not match their code") from exc
        finally:
            await _close(writer)
        contact = self.store.paired(theirs.fingerprint, public)
        if contact is None:
            raise TransportError("this code was cancelled")
        if self.on_paired:
            self.on_paired(contact)
        return contact

    # the initiator side: we have something for a contact (or just say hello)
    async def deliver(self, contact: bytes, connect: Connect) -> Result:
        if not self.store.may_talk(contact):
            raise TransportError("not a contact")
        try:
            reader, writer = await asyncio.wait_for(connect(), HANDSHAKE_TIMEOUT)
        except (OSError, asyncio.TimeoutError) as exc:
            raise TransportError("the contact is not reachable") from exc
        try:
            initiator = Initiator(self.me, contact)
            write_frame(writer, initiator.hello())
            await writer.drain()
            session = initiator.finish(await read_frame(reader, REPLY_SIZE, HANDSHAKE_TIMEOUT))
            return await self._exchange(session, reader, writer)
        except HandshakeError as exc:
            raise TransportError("the other computer is not this contact") from exc
        finally:
            await _close(writer)

    async def _exchange(self, session: Session, reader: asyncio.StreamReader,
                        writer: asyncio.StreamWriter) -> Result:
        """Sending and reading run side by side: two queues of big pictures must not wait on each other."""
        peer, result = session.peer, Result(session.peer)
        queued = self.store.queued(peer)
        waiting = set(queued)
        outbox: asyncio.Queue = asyncio.Queue()
        for message_id in queued:
            outbox.put_nowait(message_id)  # read from the disk one at a time, when its turn comes

        async def pump() -> None:
            while (item := await outbox.get()) is not None:
                if isinstance(item, str):
                    item = self.store.outgoing(peer, item)
                    if item is None:
                        continue
                write_frame(writer, session.seal(item.encode()))  # sealed in sending order: the counters match
                await writer.drain()

        sender = asyncio.ensure_future(pump())
        said_bye = heard_bye = False
        try:
            while True:
                if not waiting and not said_bye:
                    outbox.put_nowait(msg.Message.bye())
                    said_bye = True
                if said_bye and heard_bye:
                    outbox.put_nowait(None)
                    await sender
                    return result
                reading = asyncio.ensure_future(read_frame(reader, MAX_MESSAGE, self.idle_timeout))
                done, _ = await asyncio.wait({reading, sender}, return_when=asyncio.FIRST_COMPLETED)
                if reading not in done:  # the sending side broke first
                    reading.cancel()
                    sender.result()
                    raise TransportError("the connection ended")
                try:
                    incoming = msg.decode(session.open(reading.result()))
                except msg.MessageError as exc:
                    raise TransportError("the contact sent something malformed") from exc
                if incoming.kind == msg.BYE:
                    heard_bye = True
                elif incoming.kind == msg.RECEIPT:
                    if incoming.id in waiting:
                        waiting.discard(incoming.id)
                        self.store.set_state(peer, incoming.id, incoming.state)
                        (result.refused if incoming.state == "refused" else result.sent).append(incoming.id)
                else:
                    state = await self._receive(peer, incoming, result)
                    outbox.put_nowait(msg.Message.receipt(incoming.id, state))
        except SessionError as exc:
            raise TransportError("a message failed its check") from exc
        except (ConnectionError, OSError) as exc:
            raise TransportError("the connection ended") from exc
        finally:
            if not sender.done():
                sender.cancel()
            session.close()

    async def _receive(self, peer: bytes, incoming: msg.Message, result: Result) -> str:
        contact = self.store.contact(peer)
        if incoming.kind == msg.PICTURE and not self.store.has_message(peer, incoming.id):
            if not (contact and contact.verified):
                result.refused.append(incoming.id)
                return "refused"
            try:  # in a thread: the sandbox takes a moment, and the connection keeps going meanwhile
                body, mime = await asyncio.to_thread(self.clean, incoming.body)
            except pictures.PictureError:
                result.refused.append(incoming.id)
                return "refused"
            incoming = msg.Message(msg.PICTURE, body, incoming.id, incoming.time, mime=mime)
        if not self.store.has_message(peer, incoming.id):
            self.store.add_message(peer, incoming, outgoing=False, state="delivered")
            result.received.append(incoming)
            if self.on_message:
                self.on_message(peer, incoming)
        return "delivered"


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 5)
    except (ConnectionError, OSError, asyncio.TimeoutError):
        writer.transport.abort()  # a contact that stopped reading does not hold the connection open


def tcp(host: str, port: int = PORT) -> Connect:
    """A contact on the local network (found with mDNS, discovery.py)."""
    return lambda: asyncio.open_connection(host, port, limit=2 ** 16)


def tor(onion: str, socks_path: str, port: int = PORT) -> Connect:
    """A contact on the internet: through Tor's SOCKS5 port, by .onion name (RFC 1928, no authentication)."""

    async def connect() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        _onion_name(onion)  # checked before Tor hears anything
        reader, writer = await asyncio.open_unix_connection(socks_path, limit=2 ** 16)
        try:
            await socks5_connect(reader, writer, onion, port)
        except BaseException:
            await _close(writer)
            raise
        return reader, writer

    return connect


def _onion_name(host: str) -> bytes:
    if not re.fullmatch(r"[a-z2-7]{56}\.onion", host):
        raise TransportError("only .onion names go through Tor here")
    return host.encode("ascii")


async def socks5_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, port: int) -> None:
    name = _onion_name(host)
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    try:
        if await reader.readexactly(2) != b"\x05\x00":
            raise TransportError("Tor did not accept the connection")
        writer.write(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack(">H", port))
        await writer.drain()
        head = await reader.readexactly(4)
        if head[:2] != b"\x05\x00":
            raise TransportError("the contact is not online (Tor reply %d)" % head[1])
        kind = head[3]
        size = {1: 4, 4: 16}.get(kind)
        if size is None:
            size = (await reader.readexactly(1))[0]
        await reader.readexactly(size + 2)  # the bound address and port, unused
    except asyncio.IncompleteReadError as exc:
        raise TransportError("Tor closed the connection") from exc
