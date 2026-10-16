#!/usr/bin/env python3
"""Log into a booted D.Ai OS live system over a QEMU serial socket and verify it.

Usage: serial_check.py <serial-unix-socket> <report-file>

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


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    sock_path, report_path = sys.argv[1], sys.argv[2]

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
        ("graphical target", "systemctl get-default", True, lambda o: "graphical.target" in o),
        ("display manager", "systemctl is-active sddm", True, lambda o: o.splitlines()[-1:] == ["active"]),
        ("labwc compositor", "pgrep -a -x labwc", True, lambda o: "labwc" in o),
        ("lxqt panel", "pgrep -a -x lxqt-panel", True, lambda o: "lxqt-panel" in o),
        ("pipewire", "pgrep -a -x pipewire", False, lambda o: "pipewire" in o),
        ("network manager", "systemctl is-active NetworkManager", True, lambda o: o.splitlines()[-1:] == ["active"]),
        ("firewall loaded", "sudo nft list tables", True, lambda o: "dai_filter" in o),
        ("firewall input policy", "sudo nft list chain inet dai_filter input", True, lambda o: "policy drop" in o),
        ("apparmor enabled", "cat /sys/module/apparmor/parameters/enabled", True, lambda o: o.strip().endswith("Y")),
        ("kptr_restrict", "cat /proc/sys/kernel/kptr_restrict", True, lambda o: o.strip().endswith("2")),
        ("root locked", "sudo passwd -S root", True, lambda o: " L " in o),
        ("zram swap", "cat /proc/swaps", False, lambda o: "zram" in o),
        ("failed units", "systemctl --failed --no-legend --plain", False, lambda o: o.strip() == ""),
    ]

    # Always printed, never judged: context for diagnosing failures.
    diagnostics = [
        ("sddm config", "cat /etc/sddm.conf"),
        ("session files", "ls /usr/share/wayland-sessions /usr/share/xsessions"),
        ("login sessions", "loginctl list-sessions --no-legend"),
        ("session processes", "ps -eo user,args | grep -Ei 'sddm|xorg|labwc|lxqt|pcmanfm' | grep -v grep"),
        ("sddm journal", "sudo journalctl -b -u sddm --no-pager -o cat | tail -n 40"),
        ("wayland session log", "tail -n 40 ~/.local/share/sddm/wayland-session.log"),
    ]

    failed_required = 0
    lines = []
    for name, command, required, ok in checks:
        try:
            output = serial.run(command)
            passed = ok(output)
        except (TimeoutError, OSError) as exc:
            output, passed = f"<error: {exc}>", False
        status = "PASS" if passed else ("FAIL" if required else "WARN")
        if not passed and required:
            failed_required += 1
        lines.append(f"[{status}] {name}: {command}")
        if output:
            lines.extend(f"        {line}" for line in output.splitlines()[:20])

    for name, command in diagnostics:
        try:
            output = serial.run(command)
        except (TimeoutError, OSError) as exc:
            output = f"<error: {exc}>"
        lines.append(f"[INFO] {name}: {command}")
        lines.extend(f"        {line}" for line in output.splitlines()[:40])

    serial.send("exit\n")
    report = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report, end="")
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
