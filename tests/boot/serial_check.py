#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Log into a booted D.Ai OS live system over a QEMU serial socket and verify it.

Usage: serial_check.py <serial-unix-socket> <report-file> [--launch-apps]

With --launch-apps, opens a terminal, the file manager and a Hebrew text file
in the editor inside the graphical session, for screenshots.

Exits 0 when every required check passes, 1 otherwise. Optional checks are
reported but never fail the run.
"""

from __future__ import annotations

import re
import socket
import sys
import time

LIVE_USER = "dai"
LIVE_PASSWORD = "live"  # live-config default; live session only
MARKER_PREFIX = "__DAI_"
LOGIN_FAILED = re.compile(rb"Login incorrect")
SHELL_PROMPT_OR_FAILURE = re.compile(rb"[$#] $|Login incorrect")


class Serial:
    def __init__(self, path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.sock.settimeout(0.5)
        self.buf = b""

    def send(self, text: str) -> None:
        self.sock.sendall(text.encode())

    def expect(self, pattern: re.Pattern[bytes], timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = pattern.search(self.buf)
            if match:
                out, self.buf = self.buf[: match.end()], self.buf[match.end():]
                return out
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            self.buf += chunk
        tail = self.buf[-800:].decode(errors="replace")
        raise TimeoutError(f"pattern {pattern.pattern!r} not seen within {timeout}s; console tail:\n{tail}")

    def recover(self) -> None:
        """After a timeout: interrupt whatever still runs and resync with the shell."""
        self.send("\x03")
        time.sleep(1)
        self.send("\n")
        try:
            self.run("true", timeout=20)
        except TimeoutError:
            pass

    def run(self, command: str, timeout: float = 30) -> str:
        """Run a shell command and return its output between unique markers."""
        marker = f"{MARKER_PREFIX}{time.monotonic_ns()}__"
        self.buf = b""
        # The echo splits the marker so the terminal echo of the command
        # line never matches the end pattern.
        self.send(f"{command} 2>&1; echo {marker[:6]}''{marker[6:]}\n")
        out = self.expect(re.compile(re.escape(marker.encode()) + rb"\r?\n"), timeout)
        text = out.decode(errors="replace").replace("\r", "")
        # Drop terminal echoes of the command line (which may be wrapped or
        # repeated) and the end marker; all of them contain the marker prefix.
        body = [line for line in text.split("\n") if MARKER_PREFIX not in line]
        return "\n".join(body).strip()


WAYLAND_ENV = (
    "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
    'export WAYLAND_DISPLAY="$(basename "$(ls "$XDG_RUNTIME_DIR"/wayland-? | head -n1)")"; '
)
HEBREW_TUNE = "חסום דיסק און קי ונעל מסך אחרי 5 דקות"


def _hex(text: str) -> str:
    """\\xNN escapes so only ASCII crosses the serial line."""
    return "".join(f"\\x{b:02x}" for b in text.encode("utf-8"))


# Runs inside the D.Ai Forge sandbox and reports what it can reach.
SANDBOX_PROBE_B64 = "aW1wb3J0IG9zLCBzb2NrZXQKcHJpbnQoJ2hvbWU6Jywgc29ydGVkKG9zLmxpc3RkaXIob3MucGF0aC5leHBhbmR1c2VyKCd+JykpKSkKdHJ5OgogICAgc29ja2V0LmNyZWF0ZV9jb25uZWN0aW9uKCgnMS4xLjEuMScsIDgwKSwgdGltZW91dD0zKQogICAgcHJpbnQoJ25ldHdvcms6IG9wZW4nKQpleGNlcHQgT1NFcnJvcjoKICAgIHByaW50KCduZXR3b3JrOiBibG9ja2VkJykKZm9yIHBhdGggaW4gWycvYXBwL2FwcC5weScsICcvZXRjL3Bhc3N3ZCddOgogICAgdHJ5OgogICAgICAgIG9wZW4ocGF0aCwgJ2EnKS53cml0ZSgneCcpCiAgICAgICAgcHJpbnQoJ3dyaXRhYmxlOicsIHBhdGgpCiAgICBleGNlcHQgT1NFcnJvcjoKICAgICAgICBwcmludCgncmVhZC1vbmx5OicsIHBhdGgpCnByaW50KCdzc2gga2V5IHZpc2libGU6Jywgb3MucGF0aC5leGlzdHMoJy9ob21lL2RhaS8uc3NoL2NhbmFyeScpKQpwcmludCgneDExIHNvY2tldCB2aXNpYmxlOicsIG9zLnBhdGguZXhpc3RzKCcvdG1wLy5YMTEtdW5peCcpKQo="
HEBREW_FORGE = "תתקין אנטי וירוס"

HEBREW_SAMPLE = "שלום! זוהי D.Ai OS — מערכת הפעלה קלה, מאובטחת וקוד פתוח.\nHello from D.Ai OS.\n"


def launch_apps_command() -> str:
    """Shell command that opens demo windows in the user's Wayland session."""
    # Encode the sample as \xNN escapes so only ASCII crosses the serial line.
    sample = _hex(HEBREW_SAMPLE)
    return (
        "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
        'export WAYLAND_DISPLAY="$(basename "$(ls "$XDG_RUNTIME_DIR"/wayland-? | head -n1)")"; '
        "export QT_QPA_PLATFORM=wayland QT_QPA_PLATFORMTHEME=lxqt XDG_CURRENT_DESKTOP=LXQt:labwc:wlroots; "
        f"printf '{sample}' > ~/hello-he.txt; "
        "mkdir -p ~/.local/state/dai; "
        "printf 'Firefox ESR\\n>htop\\n' > ~/.local/state/dai/command-history; "
        "setsid -f qterminal >/dev/null 2>&1; "
        "setsid -f pcmanfm-qt ~ >/dev/null 2>&1; "
        "setsid -f featherpad ~/hello-he.txt >/dev/null 2>&1; "
        "sleep 4; setsid -f dai-command >/dev/null 2>&1"
    )


def main() -> int:
    args = sys.argv[1:]
    launch_apps = "--launch-apps" in args
    args = [a for a in args if a != "--launch-apps"]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    sock_path, report_path = args

    serial = Serial(sock_path)
    serial.send("\n")
    serial.expect(re.compile(rb"login: ?$", re.M), 60)
    serial.send(f"{LIVE_USER}\n")
    serial.expect(re.compile(rb"Password: ?$", re.M), 30)
    serial.send(f"{LIVE_PASSWORD}\n")
    # login(1) flushes pending input while it starts the shell, so wait for
    # the prompt (or a failure) before typing any command.
    result = serial.expect(SHELL_PROMPT_OR_FAILURE, 60)
    if LOGIN_FAILED.search(result):
        print(f"login as the live user '{LIVE_USER}' failed", file=sys.stderr)
        return 1
    # Quiet the console: no kernel messages, no colors, fixed width.
    serial.run("sudo dmesg -n 1; export TERM=dumb PAGER=cat SYSTEMD_PAGER=cat SYSTEMD_COLORS=0")

    # (name, command, required, predicate on output)
    checks = [
        ("dai-release", "cat /etc/dai-release", True, lambda o: 'NAME="D.Ai OS' in o),
        ("credit", "cat /etc/dai-release; dai-tune --version", True,
         lambda o: o.count("Diamond Rubinny (d.Ai)") >= 2),
        ("graphical target", "systemctl get-default", True, lambda o: "graphical.target" in o),
        ("display manager", "systemctl is-active sddm", True, lambda o: o.splitlines()[-1:] == ["active"]),
        ("labwc compositor", "pgrep -a -x labwc", True, lambda o: "labwc" in o),
        ("lxqt session", "pgrep -a -x lxqt-session", True, lambda o: "lxqt-session" in o),
        ("lxqt panel", "pgrep -a -x lxqt-panel", True, lambda o: "lxqt-panel" in o),
        ("desktop", "pgrep -a -f 'pcmanfm-qt --desktop'", True, lambda o: "--desktop" in o),
        ("pipewire", "pgrep -a -x pipewire", False, lambda o: "pipewire" in o),
        ("network manager", "systemctl is-active NetworkManager", True, lambda o: o.splitlines()[-1:] == ["active"]),
        ("firewall loaded", "sudo nft list tables", True, lambda o: "dai_filter" in o),
        ("firewall input policy", "sudo nft list chain inet dai_filter input", True, lambda o: "policy drop" in o),
        ("apparmor enabled", "cat /sys/module/apparmor/parameters/enabled", True, lambda o: o.strip().endswith("Y")),
        ("kptr_restrict", "cat /proc/sys/kernel/kptr_restrict", True, lambda o: o.strip().endswith("2")),
        ("root locked", "sudo passwd -S root", True, lambda o: " L " in o),
        ("dai theme", "grep -c 'D.Ai Night' /usr/share/lxqt/themes/dai/lxqt-panel.qss", True, lambda o: o.strip().endswith("1")),
        ("dai-command", "dai-command --version", True, lambda o: "dai-command" in o),
        ("zram swap", "cat /proc/swaps", False, lambda o: "zram" in o),
        ("failed units", "systemctl --failed --no-legend --plain", False, lambda o: o.strip() == ""),
        # D.Ai Tune end to end: parse -> plan -> helper (as root) -> journal -> undo.
        ("tune: version", "dai-tune --version", True, lambda o: "dai-tune" in o),
        ("tune: polkit action", "pkaction --action-id io.github.diamondrubinny.dai.tune.apply", True,
         lambda o: "io.github.diamondrubinny.dai.tune.apply" in o),
        ("tune: hebrew dry run", f"LANG=he_IL.UTF-8 dai-tune --dry-run \"$(printf '{_hex(HEBREW_TUNE)}')\"", True,
         lambda o: "הרצת ניסיון" in o and "נעילת מסך אחרי 5 דקות" in o),
        ("tune: block usb", "DAI_TUNE_ELEVATE=sudo dai-tune --yes 'block usb storage' && cat /etc/modprobe.d/dai-tune-usb_storage.conf", True,
         lambda o: "install usb_storage /bin/false" in o),
        ("tune: undo usb", "DAI_TUNE_ELEVATE=sudo dai-tune undo && test ! -e /etc/modprobe.d/dai-tune-usb_storage.conf && echo UNDONE", True,
         lambda o: "UNDONE" in o),
        ("tune: refuse --yes when weakening", "DAI_TUNE_ELEVATE=sudo dai-tune --yes 'open port 8080'; echo rc=$?", True,
         lambda o: "rc=1" in o),
        ("tune: open port (confirmed)", "echo yes | DAI_TUNE_ELEVATE=sudo dai-tune 'open port 8080' && sudo nft list chain inet dai_filter input | grep -c 'dport 8080'", True,
         lambda o: o.strip().splitlines()[-1:] == ["2"]),
        ("tune: undo port", "DAI_TUNE_ELEVATE=sudo dai-tune undo >/dev/null; sudo nft list chain inet dai_filter input | grep -c 'dport 8080'", True,
         lambda o: o.strip().splitlines()[-1:] == ["0"]),
        ("tune: injection refused", "DAI_TUNE_ELEVATE=sudo dai-tune --yes 'install vlc; rm -rf /tmp/x'; echo rc=$?", True,
         lambda o: "rc=2" in o),
        ("tune: security score", "dai-tune status", True, lambda o: "Security score" in o),
        # Local AI runtime (model download is checked separately once pinned).
        ("ai: llama-server", "LD_LIBRARY_PATH=/opt/dai/llama /opt/dai/llama/llama-server --version 2>&1", True,
         lambda o: "0bb496d" in o),
        ("ai: daid socket", "systemctl --user is-active dai-daid.socket", True, lambda o: o.strip().endswith("active")),
        ("ai: daid status", "dai-ai status", True, lambda o: "model:" in o),
        ("ai: daid has no network", "systemctl --user show dai-daid.service -p RestrictAddressFamilies", True,
         lambda o: "AF_UNIX" in o and "AF_INET" not in o),
        # Command field plugin: actually loaded into the running panel process.
        ("panel: lxqt-panel version", "dpkg-query -W -f='${Version}' lxqt-panel", False, lambda o: o.strip().startswith("2.1.4")),
        ("panel: command field loaded", "grep -c libdaicommand.so /proc/$(pgrep -x lxqt-panel | head -n1)/maps", True,
         lambda o: o.strip().splitlines()[-1:] != ["0"] and o.strip().splitlines()[-1:] != []),
        # Local AI end to end: download with SHA-256 check, then inference.
        ("ai: install model (verified)", "dai-models install qwen2.5-0.5b 2>&1 | tail -n 2", True,
         lambda o: "installed and verified" in o, 600),
        ("ai: answer", "dai-ai 'What is 2+2? Reply with only the number.'", True, lambda o: "4" in o, 300),
        # D.Ai Voice: pinned whisper.cpp, verified speech model, sandboxed transcription.
        ("voice: installed", "dai-voice --version; cat /opt/dai/whisper/VERSION; "
         "/opt/dai/whisper/whisper-cli --help >/dev/null 2>&1 && echo WHISPER_RUNS; dai-voice status", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "WHISPER_RUNS" in o and "idle" in o),
        ("voice: install speech model (verified)", "dai-models install whisper-base 2>&1 | tail -n 2", True,
         lambda o: "installed and verified" in o, 600),
        ("voice: transcribe (sandboxed, no network)", "dai-voice transcribe /opt/dai/whisper/test-jfk.wav --lang en", True,
         lambda o: "country" in o.lower(), 300),
        # D.Ai components are real packages: dpkg owns and verifies their files.
        ("packages: installed by dpkg", "dpkg-query -W -f '${Package} ${Version} ${Status}\\n' 'dai-*'; "
         "dpkg -S /usr/bin/dai-code /opt/dai/llama/llama-server; dpkg --verify dai-apps && echo VERIFY_OK; "
         "test -L /etc/systemd/user/sockets.target.wants/dai-daid.socket && echo SOCKET_ENABLED", True,
         lambda o: not re.search(r"^\s*(missing|[?.0-9]{9}) ", o, re.M) and "dai-apps: /usr/bin/dai-code" in o
         and "dai-llama-runtime: /opt/dai/llama/llama-server" in o and "VERIFY_OK" in o and "SOCKET_ENABLED" in o
         and o.count("install ok installed") >= 4),
        # D.Ai Find: files as you remember them, in English and Hebrew.
        ("find: natural language", "mkdir -p ~/Downloads ~/Pictures && echo x > ~/Downloads/boarding-pass.pdf "
         "&& echo x > ~/Pictures/beach.jpg && touch -d '40 days ago' ~/Downloads/old-ticket.pdf; "
         "dai-find --version; dai-find 'find the pdf I downloaded today'; "
         "LANG=he_IL.UTF-8 dai-find \"$(printf '\\xd7\\x9e\\xd7\\xa6\\xd7\\x90\\x20\\xd7\\x90\\xd7\\xaa\\x20\\xd7\\x94\\x2d\\x50\\x44\\x46\\x20"
         "\\xd7\\xa9\\xd7\\x94\\xd7\\x95\\xd7\\xa8\\xd7\\x93\\xd7\\xaa\\xd7\\x99\\x20\\xd7\\x94\\xd7\\x99\\xd7\\x95\\xd7\\x9d')\"; "
         "dai-find 'find photos from today'", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and o.count("boarding-pass.pdf") == 2 and "old-ticket" not in o
         and "beach.jpg" in o),
        # D.Ai Doctor: plain-language answers; its fixes are real D.Ai Tune plans.
        ("doctor: diagnosis", "dai-doctor --version; dai-doctor --json slow disk battery | python3 -c "
         "'import json,sys; f=json.load(sys.stdin); print(\"FINDINGS\", len(f), sorted({x[\"key\"].split(\":\")[0] for x in f}))'; "
         "dai-tune --dry-run 'free up disk space' </dev/null; test -x /usr/bin/powerprofilesctl && powerprofilesctl get", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "FINDINGS" in o and "'memory'" in o and "'disk'" in o
         and "apt-get clean" not in o and ("Free disk space" in o or "פינוי מקום" in o)
         and re.search(r"^\s*(balanced|power-saver|performance)\s*$", o, re.M) is not None),
        # D.Ai Privacy: the indicator starts with the session and stays hidden until something records.
        ("privacy: indicator running", "dai-privacy --version; dai-privacy status; "
         "pgrep -f 'dai_privacy.cli import main.* tray' >/dev/null && echo TRAY_RUNNING; "
         "test -f /etc/xdg/autostart/dai-privacy.desktop && echo AUTOSTART", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "TRAY_RUNNING" in o and "AUTOSTART" in o),
        ("privacy: a recording is seen", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "(timeout 8 pw-record /tmp/privacy-test.wav >/dev/null 2>&1 &); sleep 4; dai-privacy status; sleep 5; "
         "dai-privacy log | tail -n 2; rm -f /tmp/privacy-test.wav", False,
         lambda o: "pw-record" in o or "microphone" in o, 40),
        # D.Ai Backup: the whole cycle on a stand-in drive, with the daily timer for this user.
        ("backup: encrypted cycle", "export XDG_RUNTIME_DIR=/run/user/$(id -u); rm -rf /tmp/drive ~/.config/dai/backup.*; "
         "mkdir -p /tmp/drive ~/Documents && echo 'version 1' > ~/Documents/vm-report.txt; dai-backup --version; "
         "dai-backup setup /tmp/drive --folders Documents | grep -c 'RECOVERY KEY'; dai-backup now; "
         "echo 'version 2' > ~/Documents/vm-report.txt; dai-backup now; "
         "dai-backup restore ~/Documents/vm-report.txt --from \"$(dai-backup list | head -n1 | cut -d' ' -f1)\"; "
         "cat ~/Restored/*/home/*/Documents/vm-report.txt; grep -rl 'version 1' /tmp/drive >/dev/null || echo ENCRYPTED; "
         "systemctl --user is-enabled dai-backup.timer", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "Backed up" in o and "Restored into" in o
         and re.search(r"^\s*version 1\s*$", o, re.M) is not None and "ENCRYPTED" in o and "enabled" in o, 180),
        # Windows refugees: the hardware answer before installing, and their files after.
        ("doctor: hardware", "dai-doctor hardware", True,
         lambda o: re.search(r"Graphics: works|גרפיקה: במצב תקין", o) is not None
         and re.search(r"Wired network: works|רשת קווית: במצב תקין", o) is not None),
        ("move: from windows", "rm -rf /tmp/win && mkdir -p /tmp/win/Users/Dana/Documents /tmp/win/Users/Dana/Pictures "
         "&& echo cv > /tmp/win/Users/Dana/Documents/cv-from-windows.docx && echo j > /tmp/win/Users/Dana/Pictures/desktop.ini; "
         "dai-move --version; dai-move /tmp/win --yes; test -f ~/Documents/cv-from-windows.docx && echo COPIED; "
         "test -f ~/Pictures/desktop.ini || echo JUNK_SKIPPED", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "COPIED" in o and "JUNK_SKIPPED" in o),
        # Organization policies: a root-owned file in /etc/dai/policy.d is applied by itself.
        ("policy: applied on drop", "dai-tune policy; printf '%s' '{\"format\": 1, \"name\": \"CI\", "
         "\"apply\": [\"block usb storage\"]}' | sudo install -m 0644 /dev/stdin /etc/dai/policy.d/90-ci.json; "
         "sleep 8; dai-tune policy; test -f /etc/modprobe.d/dai-tune-usb_storage.conf && echo POLICY_APPLIED; "
         "sudo rm -f /etc/dai/policy.d/90-ci.json /etc/modprobe.d/dai-tune-usb_storage.conf", True,
         lambda o: "POLICY_APPLIED" in o and "applied" in o, 120),
        ("office and edition", ". /etc/dai-release; echo EDITION=$EDITION; command -v libreoffice >/dev/null && echo OFFICE; "
         "if [ \"$EDITION\" = edu ]; then for app in gcompris-qt tuxpaint stellarium; do command -v $app >/dev/null && echo EDU_$app; done; fi",
         True, lambda o: "OFFICE" in o and ("EDITION=edu" not in o or o.count("EDU_") >= 2)),
        # D.Ai Welcome: installed, in the menu, and never opens by itself in the live session.
        ("welcome: first run", "dai-welcome --version; dai-welcome --first-run; "
         "test -f /etc/xdg/autostart/dai-welcome.desktop && echo AUTOSTART; "
         "test -f /usr/share/applications/dai-welcome.desktop && echo IN_MENU", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "not needed (live session)" in o
         and "AUTOSTART" in o and "IN_MENU" in o),
        # D.Ai Code: works inside a project, never outside it or on secrets.
        ("code: installed and confined", "dai-code --version; rm -rf /tmp/demo && mkdir -p /tmp/demo/src && cd /tmp/demo "
         "&& printf 'def add(a, b):\\n    return a - b\\n' > src/util.py && printf 'TOKEN=x\\n' > .env; "
         "dai-code explain ../../etc/passwd; echo rc=$?; dai-code edit .env x --yes; echo rc=$?; cd ~", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "outside the project" in o and "sensitive" in o
         and o.count("rc=1") == 2),
        ("ai: code assistant answers", "cd /tmp/demo && dai-code ask 'what does add do and is it correct?' </dev/null; cd ~",
         False, lambda o: len(o.strip()) > 20, 300),
        ("ai: forge builds an app", "dai-forge --dry-run 'write a python script that prints the numbers 1 to 5' </dev/null", False,
         lambda o: "print" in o and "(dry run" in o, 600),
        ("ai: tune interpretation", "dai-tune --dry-run --ai 'make sure nobody can plug in a flash drive'", False,
         lambda o: "USB" in o, 300),
        # D.Ai Forge: recipes become Tune plans; apps run in the bubblewrap sandbox.
        ("forge: version", "dai-forge --version", True, lambda o: "Diamond Rubinny (d.Ai)" in o),
        ("design: Qt can draw SVG (diamond)", "ls /usr/lib/x86_64-linux-gnu/qt6/plugins/iconengines/ "
         "/usr/lib/x86_64-linux-gnu/qt6/plugins/imageformats/ | grep -c 'svg'", True,
         lambda o: o.strip().splitlines()[-1:] in (["2"], ["3"], ["4"])),
        # Installer: Calamares with Debian's settings (LUKS), D.Ai branding, live user removed.
        ("installer: calamares", "command -v calamares; grep '^branding:' /etc/calamares/settings.conf; "
         "grep '^username:' /etc/calamares/modules/removeuser.conf; ls /etc/calamares/branding/dai; "
         "test -f ~/Desktop/dai-install.desktop && echo ON_DESKTOP", True,
         lambda o: "/calamares" in o and "branding: dai" in o and "username: dai" in o
         and "show.qml" in o and "ON_DESKTOP" in o),
        # Encryption: cryptsetup in the image and Calamares' automatic LUKS partitioning (on unless a
        # config turns it off; Calamares' default is true).
        ("installer: LUKS available", "test -x /usr/sbin/cryptsetup && echo CRYPTSETUP_OK; "
         "cat /etc/calamares/modules/partition.conf 2>/dev/null | grep -iE '^[^#]*luks' || echo 'luks: calamares default'", True,
         lambda o: "CRYPTSETUP_OK" in o and "enableLuksAutomatedPartitioning: false" not in o),
        ("forge: window installed", "dai-forge-gui --version; test -f /usr/share/applications/dai-forge.desktop && echo IN_MENU; "
         "grep -c 'ownIcon=true' /etc/xdg/lxqt/panel.conf; test -f /etc/swaylock/config && echo LOCK_THEMED", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "IN_MENU" in o and "LOCK_THEMED" in o),
        ("forge: recipes", "dai-forge recipe list", True,
         lambda o: all(r in o for r in ("antivirus", "syncthing", "flathub")) and "!" not in o),
        ("forge: hebrew plan", f"LANG=he_IL.UTF-8 dai-forge --dry-run \"$(printf '{_hex(HEBREW_FORGE)}')\"", True,
         lambda o: "ClamAV" in o and "clamav-freshclam" in o and "/var/lib/dai/quarantine" in o),
        ("forge: install antivirus", "DAI_TUNE_ELEVATE=sudo dai-forge --yes 'install antivirus' </dev/null 2>&1 | tail -n 3; "
         "systemctl is-enabled dai-av-scan.timer; systemctl show -p ExecStart dai-av-scan.service | grep -o 'move=[^ ]*'; "
         "test -x /usr/bin/clamscan && echo CLAMSCAN_OK", True,
         lambda o: "CLAMSCAN_OK" in o and "\nenabled" in o and "move=/var/lib/dai/quarantine" in o, 900),
        ("forge: undo antivirus", "DAI_TUNE_ELEVATE=sudo dai-forge undo </dev/null >/dev/null 2>&1; "
         "systemctl is-enabled dai-av-scan.timer 2>&1; test -x /usr/bin/clamscan || echo CLAMAV_REMOVED", True,
         lambda o: "CLAMAV_REMOVED" in o and "\nenabled" not in "\n" + o, 600),
        ("forge: sandboxed app", f"mkdir -p ~/.ssh && touch ~/.ssh/canary && echo {SANDBOX_PROBE_B64} | base64 -d > /tmp/probe.py && "
         "dai-forge app add probe /tmp/probe.py --kind cli </dev/null >/dev/null && dai-forge app run probe", True,
         lambda o: all(x in o for x in ("home: []", "network: blocked", "read-only: /app/app.py", "read-only: /etc/passwd",
                                          "ssh key visible: False", "x11 socket visible: False")), 60),
        ("forge: example app added", "dai-forge app add tasks /usr/share/dai/forge/examples/tasks.py --title Tasks </dev/null "
         "| head -n 2; dai-forge app list; test -f ~/.local/share/applications/dai-app-tasks.desktop && echo IN_MENU", True,
         lambda o: "IN_MENU" in o and "tasks" in o),
        # Keyboard layout switching with a known state (panel indicator).
        ("lang: switch", WAYLAND_ENV + "dai-lang --label; dai-lang toggle; dai-lang --label; dai-lang toggle; dai-lang --label", True,
         lambda o: o.strip().splitlines()[-3:] == ["EN", "HE", "EN"]),
        # Global wrong-layout fixer: real Wayland primary selection round trip.
        ("fixlayout: selection", WAYLAND_ENV + "printf akuo | wl-copy --primary && dai-fixlayout --print", True,
         lambda o: o.strip().splitlines()[-1:] == ["שלום"]),
    ]

    # Always printed, never judged: context for diagnosing failures.
    diagnostics = [
        ("sddm config", "cat /etc/sddm.conf"),
        ("session files", "ls /usr/share/wayland-sessions /usr/share/xsessions"),
        ("login sessions", "loginctl list-sessions --no-legend"),
        ("session processes", "ps -eo user,args | grep -Ei 'sddm|xorg|labwc|lxqt|pcmanfm' | grep -v grep"),
        ("sddm journal", "sudo journalctl -b -u sddm --no-pager -o cat | tail -n 40"),
        ("wayland session log", "tail -n 60 ~/.local/share/sddm/wayland-session.log"),
        ("panel environment", "tr '\\0' '\\n' < /proc/$(pgrep -x lxqt-panel | head -n1)/environ | grep -E '^(WAYLAND_DISPLAY|DISPLAY|QT_QPA|XDG_CURRENT_DESKTOP|XDG_SESSION_TYPE)='"),
        ("panel layer-shell", "grep -oE '[^ ]*(LayerShell|layer-shell|wayland)[^ ]*' /proc/$(pgrep -x lxqt-panel | head -n1)/maps | sort -u"),
        ("layer-shell packages", "dpkg -l | grep -Ei 'layer-?shell' | cut -c1-80"),
    ]

    failed_required = 0
    lines = []
    for check in checks:
        name, command, required, ok = check[:4]
        timeout = check[4] if len(check) > 4 else 30
        try:
            output = serial.run(command, timeout=timeout)
            passed = ok(output)
        except (TimeoutError, OSError) as exc:
            output, passed = f"<error: {exc}>", False
            if isinstance(exc, TimeoutError):
                serial.recover()  # one stuck command must not fail all later checks
        status = "PASS" if passed else ("FAIL" if required else "WARN")
        if not passed and required:
            failed_required += 1
        lines.append(f"[{status}] {name}: {command}")
        if output:
            lines.extend(f"        {line}" for line in output.splitlines()[:30])

    for name, command in diagnostics:
        try:
            output = serial.run(command)
        except (TimeoutError, OSError) as exc:
            output = f"<error: {exc}>"
        lines.append(f"[INFO] {name}: {command}")
        lines.extend(f"        {line}" for line in output.splitlines()[:40])

    if launch_apps:
        try:
            serial.run(launch_apps_command())
            lines.append("[INFO] launched demo apps in the graphical session")
        except (TimeoutError, OSError) as exc:
            lines.append(f"[INFO] could not launch demo apps: {exc}")

    serial.send("exit\n")
    report = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report, end="")
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
