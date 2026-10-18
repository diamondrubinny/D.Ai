# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-quick: quick settings (docs/TASKBAR.md §2.4).

  dai-quick              open D.Ai Quick, or close it if it is open (the clock and Super+N)
  dai-quick --state      what the switches are now, as JSON (null = this computer does not have it)
  dai-quick --version
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import __author__, __version__


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    return Path(runtime) / "dai-quick.sock"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--version" in args:
        print(f"dai-quick {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    if "--state" in args:
        from .controls import Controls

        controls = Controls()
        print(json.dumps({**controls.state(), "security": controls.security()}, indent=2))
        return 0
    if args:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return open_or_close()


def open_or_close() -> int:
    """One D.Ai Quick per user: a second start closes the open one (so the same key toggles it)."""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    path = str(socket_path())
    probe = QLocalSocket()
    probe.connectToServer(path)
    if probe.waitForConnected(150):
        probe.write(b"close")
        probe.flush()
        probe.waitForBytesWritten(150)
        probe.disconnectFromServer()
        return 0
    app = QApplication(sys.argv)
    QLocalServer.removeServer(path)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # this user only
    if server.listen(path):
        server.newConnection.connect(app.quit)
    from .gui import main as gui_main

    return gui_main()
