# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Tor for Diamond Chat (docs/SEND.md §0): the person's own Tor, only while Chat is on.

  - Tor runs as the user, not as a system service (that one is masked in D.Ai), with every socket in a 0700
    folder in $XDG_RUNTIME_DIR: SOCKS (to reach contacts) and control (cookie authentication).
  - Tor exits by itself when Chat does (__OwningControllerProcess).
  - The onion service key is an Ed25519 seed kept like the identity key (the keyring, else a 0600 file), and
    is given to Tor over the control socket (ADD_ONION), so it is never written in Tor's own folder and the
    address stays the same. The address is checked against the one we compute from the key.
  - The service forwards to Chat on 127.0.0.1 only.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .invite import onion_address
from .transport import PORT


class TorError(Exception):
    """Tor is missing, did not start, or refused a command."""


def expanded_key(seed: bytes) -> bytes:
    """The 64-byte expanded Ed25519 secret key Tor takes (ADD_ONION ED25519-V3), from a 32-byte seed (RFC 8032)."""
    digest = bytearray(hashlib.sha512(seed).digest())
    digest[0] &= 248
    digest[31] &= 127
    digest[31] |= 64
    return bytes(digest)


@dataclass
class Paths:
    run: Path  # sockets and the cookie: $XDG_RUNTIME_DIR/dai-chat
    data: Path  # Tor's state (guards, consensus cache): ~/.local/share/dai/chat/tor

    @classmethod
    def default(cls) -> "Paths":
        run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return cls(Path(run) / "dai-chat", Path(data) / "dai" / "chat" / "tor")

    @property
    def socks(self) -> Path:
        return self.run / "socks.sock"

    @property
    def control(self) -> Path:
        return self.run / "control.sock"

    @property
    def cookie(self) -> Path:
        return self.run / "control.cookie"

    @property
    def torrc(self) -> Path:
        return self.run / "torrc"


def torrc(paths: Paths, owner: int) -> str:
    return "\n".join([
        "# Written by Diamond Chat each time it starts Tor (docs/SEND.md).",
        f"DataDirectory {paths.data}",
        f"SocksPort unix:{paths.socks}",
        f"ControlPort unix:{paths.control}",
        "CookieAuthentication 1",
        f"CookieAuthFile {paths.cookie}",
        f"__OwningControllerProcess {owner}",
        "AvoidDiskWrites 1",
        "Log notice stderr",
        "",
    ])


class Controller:
    """Tor's control protocol (control-spec.txt), the few commands Chat needs, over the Unix socket."""

    def __init__(self, path: Path, connect: Callable[[str], socket.socket] | None = None) -> None:
        self.sock = (connect or _unix)(str(path))
        self.buffer = b""

    def command(self, line: str) -> list[str]:
        if "\r" in line or "\n" in line:
            raise TorError("one command per line")
        self.sock.sendall(line.encode("ascii") + b"\r\n")
        lines = []
        while True:
            reply = self._line()
            code, rest = reply[:3], reply[4:]
            lines.append(rest)
            if reply[3:4] == " ":
                if code != "250":
                    raise TorError(f"Tor refused: {reply}")
                return lines

    def _line(self) -> str:
        while b"\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise TorError("Tor closed the control connection")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\r\n", 1)
        return line.decode("utf-8", "replace")

    def authenticate(self, cookie: bytes) -> None:
        self.command("AUTHENTICATE " + cookie.hex())

    def bootstrap(self) -> int:
        """How far Tor has got joining the network, 0-100."""
        for line in self.command("GETINFO status/bootstrap-phase"):
            found = re.search(r"PROGRESS=(\d+)", line)
            if found:
                return int(found.group(1))
        return 0

    def add_onion(self, seed: bytes, port: int = PORT) -> str:
        blob = base64.b64encode(expanded_key(seed)).decode()
        lines = self.command(f"ADD_ONION ED25519-V3:{blob} Port={port},127.0.0.1:{port}")
        for line in lines:
            if line.startswith("ServiceID="):
                return line.split("=", 1)[1] + ".onion"
        raise TorError("Tor did not say the onion address")

    def close(self) -> None:
        self.sock.close()


def _unix(path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(path)
    return sock


class Tor:
    """Starts the person's Tor, publishes their onion service and stops it all when Chat stops."""

    def __init__(self, paths: Paths | None = None, popen: Callable = subprocess.Popen,
                 controller: Callable[[Path], Controller] = Controller, sleep: Callable = time.sleep) -> None:
        self.paths = paths or Paths.default()
        self.popen, self.controller, self.sleep = popen, controller, sleep
        self.process = None
        self.control: Controller | None = None
        self.address = ""

    def start(self, timeout: float = 60.0) -> None:
        for folder in (self.paths.run, self.paths.data):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(folder, 0o700)  # Tor refuses sockets in a folder others can enter
        for stale in (self.paths.socks, self.paths.control, self.paths.cookie):
            stale.unlink(missing_ok=True)
        fd = os.open(self.paths.torrc, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(torrc(self.paths, os.getpid()))
        try:
            self.process = self.popen(["tor", "-f", str(self.paths.torrc)], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise TorError("Tor is not installed") from exc
        deadline = time.monotonic() + timeout
        while not (self.paths.control.exists() and self.paths.cookie.exists()):
            if self.process.poll() is not None:
                raise TorError("Tor stopped while starting")
            if time.monotonic() > deadline:
                self.stop()
                raise TorError("Tor did not start in time")
            self.sleep(0.2)
        self.control = self.controller(self.paths.control)
        self.control.authenticate(self.paths.cookie.read_bytes())

    def publish(self, seed: bytes) -> str:
        """Puts the person's onion service up; returns its address, the one in their invitation code."""
        if self.control is None:
            raise TorError("Tor is not running")
        if self.address:
            return self.address  # already up: Tor refuses the same key twice
        address = self.control.add_onion(seed)
        from nacl.signing import SigningKey  # here, so the module loads (for --help) without PyNaCl
        if address != onion_address(bytes(SigningKey(seed).verify_key)):
            raise TorError("Tor published a different address than the key's")
        self.address = address
        return address

    def wait_online(self, timeout: float = 120.0) -> bool:
        deadline = time.monotonic() + timeout
        while self.control is not None and time.monotonic() < deadline:
            if self.control.bootstrap() >= 100:
                return True
            self.sleep(1)
        return False

    def stop(self) -> None:
        if self.control is not None:
            self.control.close()
            self.control = None
        self.address = ""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
