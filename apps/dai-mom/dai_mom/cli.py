# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""dai-mom: MOM, the task manager (docs/MOM.md).

  dai-mom                           open MOM (Ctrl+Shift+Esc), or bring the open one forward
  dai-mom list [--json]             what runs now, as apps
  dai-mom close NAME|PID [--force] [--yes]
                                    close an app; forcing and parts of the session need --yes,
                                    and parts of the session can never be forced
  dai-mom services                  what runs in the background (yours, then the system's)
  dai-mom startup [on|off NAME.desktop]
                                    the apps that start at login, or turn one on or off
  dai-mom --version
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dai_i18n import ui_lang

from . import __author__, __version__
from . import actions, apps, procs
from .text import describe, t


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    return Path(runtime) / "dai-mom.sock"


def recording_now() -> list[str]:
    try:
        import dai_status

        return [str(a) for a in dai_status.read().get("privacy", []) if isinstance(a, str)]
    except Exception:  # noqa: BLE001 - a badge is never worth a crash
        return []


def current(lang: str, root: Path = Path("/"), sample: float = 0.5) -> list[apps.App]:
    first = procs.snapshot(root)
    if sample > 0:
        time.sleep(sample)
    snap = procs.snapshot(root, first)
    return apps.group(snap, apps.load_desktop_apps(apps.desktop_dirs(), lang), recording=recording_now())


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv[1:])
    lang = ui_lang()
    if "--version" in args:
        print(f"dai-mom {__version__} — {__author__}")
        return 0
    if "-h" in args or "--help" in args:
        print(__doc__.strip())
        return 0
    if not args:
        return open_or_raise()
    command, rest = args[0], args[1:]
    if command == "list":
        found = current(lang)
        if "--json" in rest:
            print(json.dumps([{"key": a.key, "name": a.name, "memory": a.memory, "cpu": a.cpu,
                               "processes": [p.pid for p in a.processes], "app": a.is_app,
                               "protected": a.protected, "sandboxed": a.sandboxed, "recording": a.recording}
                              for a in found], ensure_ascii=False, indent=2))
        else:
            for app in found:
                print(describe(app, lang))
        return 0
    if command == "services":
        from . import background as bg

        for user in (True, False):
            for service in bg.services(user=user):
                owner = "user" if user else "system"
                print(f"{owner:6} {service.active:10} {service.unit}  {service.description}")
        return 0
    if command == "startup":
        from . import background as bg

        if len(rest) == 2 and rest[0] in ("on", "off"):
            try:
                bg.set_login_item(rest[1], rest[0] == "on")
            except (bg.Refused, OSError) as exc:
                print(exc, file=sys.stderr)
                return 1
        for item in bg.login_items(lang):
            print(f"{'on ' if item.enabled else 'off'} {item.id}  {item.name}")
        return 0
    if command == "close":
        names = [a for a in rest if not a.startswith("--")]
        if len(names) != 1:
            print(__doc__.strip(), file=sys.stderr)
            return 2
        return close(names[0], "--force" in rest, "--yes" in rest, lang)
    print(__doc__.strip(), file=sys.stderr)
    return 2


def close(wanted: str, force: bool, confirmed: bool, lang: str) -> int:
    app = apps.find(current(lang, sample=0), wanted)
    if app is None:
        print(t("not_found", lang, name=wanted), file=sys.stderr)
        return 1
    try:
        actions.close(app, force=force, confirmed=confirmed)
    except actions.Refused as refused:
        print(t(str(refused), lang, name=app.name), file=sys.stderr)
        return 3
    if not force:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and actions.still_running(app):
            time.sleep(0.1)
        if actions.still_running(app):
            print(t("still", lang, name=app.name))
            return 4
    print(t("forced" if force else "closed", lang, name=app.name))
    return 0


def open_or_raise() -> int:
    """One MOM per user: a second start brings the open window forward."""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtWidgets import QApplication

    path = str(socket_path())
    probe = QLocalSocket()
    probe.connectToServer(path)
    if probe.waitForConnected(150):
        probe.write(b"raise")
        probe.flush()
        probe.waitForBytesWritten(150)
        probe.disconnectFromServer()
        return 0
    app = QApplication(sys.argv)
    QLocalServer.removeServer(path)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)  # this user only
    from .gui import main as gui_main

    return gui_main(server if server.listen(path) else None)
