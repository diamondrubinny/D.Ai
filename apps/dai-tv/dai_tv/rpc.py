# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Kodi's JSON-RPC over its local TCP port (docs/TV.md stage 2b).

D.Ai TV keeps Kodi's remote-control service on for this computer only (127.0.0.1:9090, "allow remote control
from applications on other systems" off) so D.Ai can talk to Kodi; nothing reaches it from the network until
"remote control from the phone" is said in D.Ai Tune. One request, one answer, fixed arguments, a short timeout.
"""
from __future__ import annotations

import json
import socket

HOST, PORT = "127.0.0.1", 9090
TIMEOUT = 5.0
MAX_ANSWER = 1_000_000


class KodiError(RuntimeError):
    pass


def call(method: str, params: dict | None = None, host: str | None = None, port: int | None = None,
         timeout: float | None = None):
    """The result of one JSON-RPC call; KodiError when Kodi is not there or says no. The module's HOST, PORT
    and TIMEOUT are read at call time (tests point them at a fake Kodi)."""
    host, port, timeout = host or HOST, port or PORT, timeout or TIMEOUT
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(json.dumps(request).encode("utf-8"))
            buffer = bytearray()
            decoder = json.JSONDecoder()
            while len(buffer) < MAX_ANSWER:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                try:
                    answer, _ = decoder.raw_decode(buffer.decode("utf-8"))
                    break
                except (ValueError, UnicodeDecodeError):
                    continue
            else:
                raise KodiError("Kodi's answer is too long")
    except OSError as exc:
        raise KodiError(f"Kodi is not listening on {host}:{port} ({exc})") from exc
    if "buffer" in locals() and not buffer:
        raise KodiError("Kodi closed the connection")
    if "error" in answer:
        raise KodiError(str(answer["error"].get("message", answer["error"])))
    return answer.get("result")


def ping(**kw) -> bool:
    return call("JSONRPC.Ping", **kw) == "pong"


def notify(title: str, message: str, seconds: int = 6, **kw) -> bool:
    """A notification on the TV; the image is D.Ai's own, never a path from the message."""
    return call("GUI.ShowNotification", {"title": title[:60], "message": message[:200], "displaytime": max(1000, seconds * 1000)}, **kw) == "OK"


def playing(**kw) -> dict | None:
    """What plays now: {"title", "kind", "year", "plot"} or None."""
    players = call("Player.GetActivePlayers", **kw) or []
    if not players:
        return None
    player = int(players[0]["playerid"])
    item = call("Player.GetItem", {"playerid": player, "properties": ["title", "year", "plot", "showtitle", "artist", "album"]}, **kw) or {}
    item = item.get("item", {})
    return {"title": str(item.get("title") or item.get("label") or ""), "kind": str(item.get("type") or ""),
            "year": item.get("year"), "plot": str(item.get("plot") or "")[:2000],
            "show": str(item.get("showtitle") or ""), "artist": ", ".join(item.get("artist") or [])}


def action(name: str, **kw) -> bool:
    """One of Kodi's input actions (play, pause, stop, back, select, up, down...)."""
    return call("Input.ExecuteAction", {"action": name}, **kw) == "OK"
