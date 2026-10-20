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

import base64
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
HEBREW_CLIP = "שלום מהלוח של D.Ai"

# Runs as root in the VM against the real snapper, on a Btrfs image (the live root is not Btrfs).
SNAPSHOT_PROBE = """
import sys
sys.path.insert(0, "/usr/lib/dai")
from pathlib import Path
from dai_tune import snapshots as s
from dai_tune.context import Context
ctx, mnt, cfg = Context(root=Path("/"), home=Path("/root")), "/mnt/dai-snap", "daitest"
print("FS", s.filesystem(ctx, mnt))
s.enable(ctx, cfg, mnt)
print("ENABLED", s.enabled(ctx, cfg))
f = Path(mnt) / "app.conf"
f.write_text("before update")
pre = ctx.run(s.snapper(cfg, "create", "-t", "pre", "-d", "apt", "-p")).stdout.strip()
f.write_text("after update")
ctx.run(s.snapper(cfg, "create", "-t", "post", "--pre-number", pre, "-d", "apt"))
print("LIST", s.listing(ctx, cfg)[-1])
safety = s.create_safety(ctx, cfg)
print("UNDONE", s.undo_update(ctx, cfg), f.read_text())
s.back_to(ctx, safety, cfg)
print("REDONE", f.read_text())
s.disable(ctx, cfg)
print("DISABLED", not s.enabled(ctx, cfg))
"""
SNAPSHOT_PROBE_B64 = base64.b64encode(SNAPSHOT_PROBE.encode()).decode()

# A user service that fails the first time and works the second (D.Ai Heal restarts it).
HEAL_UNIT = (
    "[Unit]\nDescription=D.Ai Heal test\n[Service]\n"
    "ExecStart=/bin/sh -c 'test -e /tmp/heal-ok || { touch /tmp/heal-ok; exit 1; }; exec sleep 600'\n"
)
HEAL_UNIT_B64 = base64.b64encode(HEAL_UNIT.encode()).decode()

# D.Ai OCR (docs/V2.md F1): a picture with English and Hebrew text, drawn by Qt on the VM itself.
OCR_PICTURE = (
    "import sys\n"
    "from PyQt6.QtCore import Qt\n"
    "from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter\n"
    "app = QGuiApplication(sys.argv)\n"
    "image = QImage(1000, 280, QImage.Format.Format_RGB32)\n"
    "image.fill(QColor('white'))\n"
    "painter = QPainter(image)\n"
    "painter.setPen(QColor('black'))\n"
    "font = QFont('Noto Sans')\n"
    "font.setPixelSize(60)\n"
    "painter.setFont(font)\n"
    "painter.drawText(40, 100, 'Hello from 2026')\n"
    "font = QFont('Noto Sans Hebrew')\n"
    "font.setPixelSize(60)\n"
    "painter.setFont(font)\n"
    "painter.drawText(image.rect().adjusted(0, 150, -40, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, "
    "'\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd')\n"
    "painter.end()\n"
    "image.save(sys.argv[1])\n"
)
OCR_PICTURE_B64 = base64.b64encode(OCR_PICTURE.encode()).decode()

# A small PNG re-drawn as a JPEG, then that JPEG with a made-up location in its EXIF re-drawn again (docs/SEND.md).
CHAT_PICTURE = r"""
import struct, sys, zlib
sys.path.insert(0, "/usr/lib/dai")
from dai_chat import pictures

def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
       + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x80" * 192) * 64)) + chunk(b"IEND", b""))
jpeg, _ = pictures.clean(png)
secret = b"Exif\x00\x00GPS SECRET" + b"PLACE"
photo = jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(secret) + 2) + secret + jpeg[2:]
out, mime = pictures.clean(photo)
print(mime, "GONE" if b"SECRETPLACE" not in out else "KEPT")
"""
CHAT_PICTURE_B64 = base64.b64encode(CHAT_PICTURE.encode()).decode()

# Runs inside the VM: makes a PDF that wants things, opens it the way the window does, and proves the helper
# runs under bwrap (its command line) while the file's wishes are only listed.
PDF_CHECK = r'''
import sys
sys.path.insert(0, "/usr/lib/dai")
import pikepdf
pdf = pikepdf.new()
pdf.pages.append(pikepdf.Page(pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 300, 200])))
page = pdf.pages[0]
font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
page.Contents = pdf.make_stream(b"BT /F1 24 Tf 20 100 Td (Hello sandbox) Tj ET")
pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS="app.alert(1)")
pdf.attachments["evil.exe"] = pikepdf.AttachedFileSpec(pdf, b"MZ")
pdf.save("/tmp/wants.pdf")
from dai_pdf.reader import Reader
r = Reader("/tmp/wants.pdf")
doc = r.open()
cmdline = open(f"/proc/{r.proc.pid}/cmdline", "rb").read()
print("SANDBOXED" if b"bwrap" in cmdline and b"--unshare-all" in cmdline else "NOT_SANDBOXED", cmdline[:60])
png, w, h = r.render(0, 300, 200)
print("RENDER", w, h, png[:4] == b"\x89PNG", "JS", doc.findings.javascript, "ATT", [a["name"] for a in doc.findings.attachments])
r.close()
'''
PDF_CHECK_B64 = base64.b64encode(PDF_CHECK.encode()).decode()

# Checks that must pass on the TV edition too (everything about the system, nothing about the LXQt desktop).
TV_REQUIRED = {
    "dai-release", "credit", "graphical target", "display manager", "labwc compositor", "pipewire",
    "network manager", "firewall loaded", "firewall input policy", "apparmor enabled", "kptr_restrict",
    "root locked", "zram swap", "failed units", "tune: version", "tune: polkit action", "tune: security score",
    "ai: daid has no network", "packages: installed by dpkg", "policy: applied on drop", "installer: calamares",
    "installer: LUKS available", "boot: D.Ai loading screen (Plymouth)", "login: D.Ai login screen loads (SDDM)",
    "os: secure boot shim", "i18n: boot menu languages", "pdf: opened in the sandbox, wants listed, text out",
}

# Runs inside the VM (which has no KVM of its own): defines a D.Ai VM machine through libvirt's session daemon,
# which validates the whole definition (UEFI with Secure Boot, the TPM, passt, SPICE on a socket), and removes it.
VM_CHECK = r'''
import sys
from pathlib import Path
sys.path.insert(0, "/usr/lib/dai")
from dai_vm import control, hardware, machine
missing = hardware.missing_tools()
print("FIRMWARE" if hardware.firmware_present() else "NO_FIRMWARE", "TOOLS_OK" if not missing else "TOOLS_MISSING=" + ",".join(missing))
home = Path.home()
m = machine.Machine(name="citest", memory_mb=2048, cpus=1, disk_gb=32, iso=None, drivers_iso=None, windows="11")
definition = machine.create(m, home)
v = control.Virsh()
try:
    v.define(definition)
except control.VmError as exc:
    # Seen once on the CI VM with identical packages and XML: libvirt's firmware match failed on first contact.
    # Say what libvirt knows, then ask once more after its QEMU probe had a moment.
    import subprocess, time
    print("DEFINE_FIRST_TRY_FAILED", exc)
    caps = subprocess.run(["virsh", "-c", "qemu:///session", "domcapabilities", "--machine", "q35", "--arch", "x86_64"],
                          capture_output=True, text=True, timeout=120)
    text = caps.stdout + caps.stderr
    start = text.find("<firmware")
    print("DOMCAPS_RC", caps.returncode, text[start:start + 600].replace("\n", " ") if start >= 0 else text[-400:])
    time.sleep(5)
    v.define(definition)
    print("DEFINED_ON_RETRY")
print("DEFINED", v.state("citest"))
# Stage 2: a shared folder, the clipboard and a USB device in the definition; libvirt must accept it too.
share = home / "dai-vm-share"
share.mkdir(exist_ok=True)
m = machine.load("citest", home)
m.clipboard, m.shared_folder, m.usb = True, str(share), ["0781:5583"]
v.redefine(machine.update(m, home))
xml = (machine.machine_dir("citest", home) / "domain.xml").read_text()
print("SHARED_DEFINED", v.state("citest"), "virtiofs" in xml and "memfd" in xml and "0x0781" in xml)
try:
    v.snapshot_take("citest", "ci-snap", "taken by the boot test")
    print("SNAP_TAKEN", [s["label"] for s in v.snapshots("citest")])
    v.snapshot_delete("citest", "ci-snap")
    print("SNAP_GONE", v.snapshots("citest"))
except control.VmError as exc:
    print("SNAP_FAILED", exc)
# Stage 3: the machine by sentence through D.Ai Tune (user scope, neutral, so --yes is fine), with undo.
import subprocess
tune = subprocess.run(["dai-tune", "--yes", "צילום מצב של ווינדוס לפני העדכון"], capture_output=True, text=True, timeout=300)
print("TUNE_RC", tune.returncode, (tune.stdout + tune.stderr).strip().splitlines()[-1:])
print("TUNE_SNAP", [s["label"] for s in v.snapshots("citest")])
undo = subprocess.run(["dai-tune", "undo"], capture_output=True, text=True, timeout=300)
print("UNDO_RC", undo.returncode, "TUNE_SNAP_AFTER", [s["label"] for s in v.snapshots("citest")])
v.undefine("citest")
print("UNDEFINED", v.state("citest"))
'''
VM_CHECK_B64 = base64.b64encode(VM_CHECK.encode()).decode()

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

    # The edition decides which checks are required: the TV edition boots into Kodi, not LXQt, so the desktop's
    # checks are run (as information) but only the shared ones and its own are required (docs/TV.md §5).
    edition = (serial.run(". /etc/dai-release 2>/dev/null; echo EDITION=$EDITION").strip().splitlines() or [""])[-1]
    edition = edition.removeprefix("EDITION=").strip()

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
        # The Living Diamond (docs/TASKBAR.md §2.1): the plugin is in the panel and the state file is private.
        ("taskbar: living diamond", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "echo LOADED=$(grep -c libdaistatus.so /proc/$(pgrep -x lxqt-panel | head -n1)/maps); "
         "python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); import dai_status; "
         "dai_status.update(\"ideas\", 1); print(\"STATUS\", sorted(dai_status.read().items()))'; "
         "stat -c 'MODE=%a' $XDG_RUNTIME_DIR/dai/status.json $XDG_RUNTIME_DIR/dai", True,
         lambda o: re.search(r"LOADED=[1-9]", o) is not None and "('ideas', 1)" in o and "MODE=600" in o and "MODE=700" in o),
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
         "\"apply\": [\"block usb storage\", \"lock the screen after 5 minutes\"]}' | sudo install -m 0644 /dev/stdin /etc/dai/policy.d/90-ci.json; "
         "sleep 8; dai-tune policy; test -f /etc/modprobe.d/dai-tune-usb_storage.conf && echo POLICY_APPLIED; "
         "cat /etc/dai/policy-session.env; dai-tune --dry-run 'never lock the screen' </dev/null; "
         "sudo rm -f /etc/dai/policy.d/90-ci.json /etc/modprobe.d/dai-tune-usb_storage.conf /etc/dai/policy-session.env", True,
         lambda o: "POLICY_APPLIED" in o and "applied" in o and "DAI_LOCK_MAX_SECONDS=300" in o
         and "at most 5 minutes" in o, 120),
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
        # Btrfs by default (docs/SNAPSHOTS.md stage 2): the installer's default file system, and the first-boot
        # service that turns snapshots on, which must stay inactive in the live session.
        ("installer: btrfs by default", "grep -E '^(defaultFileSystemType|initialSwapChoice):' "
         "/etc/calamares/modules/partition.conf; systemctl is-enabled dai-snapshots-firstboot.service; "
         "test -e /etc/snapper/configs/root || echo NO_LIVE_SNAPSHOTS", True,
         lambda o: 'defaultFileSystemType: "btrfs"' in o and "initialSwapChoice: none" in o and "enabled" in o
         and "NO_LIVE_SNAPSHOTS" in o),
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
         "| head -n 2; dai-forge app list; test -f ~/.local/share/applications/dai-app-tasks.desktop && echo IN_MENU; "
         # docs/TASKBAR.md §12: it runs as "dai-app-tasks", so the taskbar shows its 🛡 icon
         "grep -h '^StartupWMClass=\\|^Icon=' ~/.local/share/applications/dai-app-tasks.desktop; "
         "test -f /usr/share/icons/hicolor/scalable/apps/dai-app-sandboxed.svg && echo SHIELD_ICON; "
         "python3 -I /usr/lib/dai/dai_forge/sandbox_start.py dai-app-x /etc/passwd; echo START_RC=$?", True,
         lambda o: "IN_MENU" in o and "tasks" in o and "StartupWMClass=dai-app-tasks" in o
         and "Icon=dai-app-sandboxed" in o and "SHIELD_ICON" in o and "START_RC=2" in o),
        # D.Ai Clip: the real labwc clipboard → history; tokens and password-manager copies stay out.
        # The secrets are assembled in the shell so the command echo never contains them.
        ("clip: history without secrets", WAYLAND_ENV + "dai-clip --version; dai-clip clear >/dev/null; "
         "pgrep -f 'wl-paste --type text --watch dai-clip _store' >/dev/null && echo WATCHING; "
         "printf 'hello from the VM clipboard' | wl-copy; sleep 1; "
         "T=gh; T=\"${T}p_A1b2C3d4A1b2C3d4A1b2C3d4A1b2C3d4A1b2C3d4\"; printf '%s' \"$T\" | wl-copy; sleep 1; "
         "printf secret | wl-copy --type x-kde-passwordManagerHint; sleep 1; "
         "P=Hunter-Pm; printf '%s' \"$P-Secret-77 copied by a password manager\" | CLIPBOARD_STATE=data dai-clip _store; "
         f"printf '{_hex(HEBREW_CLIP)}' | wl-copy; sleep 1; "
         "dai-clip list; dai-clip status; stat -c 'MODE=%a' \"$XDG_RUNTIME_DIR/dai-clip\" \"$XDG_RUNTIME_DIR/dai-clip/history.json\"",
         True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "WATCHING" in o and "hello from the VM clipboard" in o
         and HEBREW_CLIP in o and "ghp_" not in o and "Hunter-Pm-Secret" not in o
         and re.search(r"(On|פועל) · 2 ", o) is not None and "MODE=700" in o and "MODE=600" in o),
        # Keyboard layout switching with a known state (panel indicator).
        ("lang: switch", WAYLAND_ENV + "dai-lang --label; dai-lang toggle; dai-lang --label; dai-lang toggle; dai-lang --label", True,
         lambda o: o.strip().splitlines()[-3:] == ["EN", "HE", "EN"]),
        # Global wrong-layout fixer: real Wayland primary selection round trip.
        ("fixlayout: selection", WAYLAND_ENV + "printf akuo | wl-copy --primary && dai-fixlayout --print", True,
         lambda o: o.strip().splitlines()[-1:] == ["שלום"]),
        # Snapshots before updates: the real snapper on a Btrfs image (docs/SNAPSHOTS.md).
        ("snapshots: update undo and redo", "command -v snapper && truncate -s 400M /tmp/snap.img && "
         "sudo mkfs.btrfs -q /tmp/snap.img && sudo mkdir -p /mnt/dai-snap && sudo mount -o loop /tmp/snap.img /mnt/dai-snap && "
         f"echo {SNAPSHOT_PROBE_B64} | base64 -d > /tmp/snap-probe.py && sudo python3 -I /tmp/snap-probe.py; "
         "sudo umount /mnt/dai-snap; rm -f /tmp/snap.img; dai-tune --dry-run 'undo the last update' </dev/null", True,
         lambda o: "FS btrfs" in o and "ENABLED True" in o and re.search(r"UNDONE \(\d+, \d+\) before update", o) is not None
         and "REDONE after update" in o and "DISABLED True" in o
         and ("Undo the last software update" in o or "ביטול העדכון האחרון" in o), 180),
        # D.Ai Rescue (docs/BASICS.md): an "installed" system on a Btrfs image ("@" with snapper's layout: a
        # read-only "pre" snapshot from before an update and a "post" one after it), then dai-rescue from outside
        # brings "@" back to before the update, keeps the old system whole, and the snapshots stay.
        # A subshell: `set -e` and the variables must not reach the shell the later checks run in.
        ("rescue: undo an update from the USB", "( set -e; I=/tmp/inst.img; M=/mnt/dai-inst; truncate -s 600M $I; "
         "sudo mkfs.btrfs -q $I; sudo mkdir -p $M; sudo mount -o loop $I $M; sudo btrfs -q subvolume create $M/@; "
         "sudo mkdir -p $M/@/etc; sudo cp /etc/os-release $M/@/etc/; echo before | sudo tee $M/@/app.conf >/dev/null; "
         "sudo btrfs -q subvolume create $M/@/.snapshots; sudo mkdir $M/@/.snapshots/1 $M/@/.snapshots/2; "
         "sudo btrfs -q subvolume snapshot -r $M/@ $M/@/.snapshots/1/snapshot; "
         "printf '<snapshot><type>pre</type><num>1</num><date>2026-10-17 21:00:00</date><description>apt</description>"
         "</snapshot>' | sudo tee $M/@/.snapshots/1/info.xml >/dev/null; echo after | sudo tee $M/@/app.conf >/dev/null; "
         "sudo btrfs -q subvolume snapshot -r $M/@ $M/@/.snapshots/2/snapshot; "
         "printf '<snapshot><type>post</type><num>2</num><date>2026-10-17 21:01:00</date><description>apt</description>"
         "<pre_num>1</pre_num></snapshot>' | sudo tee $M/@/.snapshots/2/info.xml >/dev/null; sudo umount $M; "
         "D=$(sudo losetup -f --show $I); set +e; sudo dai-rescue --device $D --undo-last-update --yes </dev/null; "
         "echo RESCUE_RC=$?; sudo mount -o subvolid=5 $D $M; printf 'FILE='; cat $M/@/app.conf; "
         "printf 'KEPT='; cat $M/@.before-rescue-*/app.conf; printf 'SNAPSHOTS='; ls $M/@/.snapshots | tr '\\n' ' '; "
         "echo; sudo umount $M; sudo losetup -d $D; rm -f $I )", True,
         lambda o: "RESCUE_RC=0" in o and "FILE=before" in o and "KEPT=after" in o and "SNAPSHOTS=1 2" in o, 180),
        # Automations (docs/EVOLVE.md §2): a real user timer, a sandboxed run, NOTIFY → notification and log.
        ("forge: automation on a timer", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "printf 'import shutil\\nfree = shutil.disk_usage(\"/\").free // 2**30\\nprint(f\"NOTIFY: {free} GB free\")\\n' > /tmp/disk.py; "
         "echo y | dai-forge app add disk-report /tmp/disk.py --schedule 'every day at 18:00' | tail -n 1; "
         "systemctl --user list-timers --all --no-pager | grep -q dai-auto-disk-report && echo TIMER_ACTIVE; "
         "systemctl --user start dai-auto-disk-report.service; dai-forge auto log disk-report; dai-forge auto list; "
         "echo y | dai-forge auto remove disk-report >/dev/null; "
         "test -f ~/.config/systemd/user/dai-auto-disk-report.timer || echo UNITS_GONE", True,
         lambda o: "TIMER_ACTIVE" in o and re.search(r"NOTIFY: \d+ GB free", o) is not None and "exit 0" in o
         and "every day at 18:00" in o and "UNITS_GONE" in o, 90),
        # D.Ai Heal: a failed service is noticed, explained and fixed (docs/EVOLVE.md §4).
        ("heal: failed service fixed", "export XDG_RUNTIME_DIR=/run/user/$(id -u); dai-heal --version; "
         "pgrep -f 'dai_heal.cli import main.* watch' >/dev/null && echo WATCHING; "
         "test -f /usr/lib/systemd/coredump.conf.d/50-dai.conf && echo NO_DUMPS_KEPT; "
         f"mkdir -p ~/.config/systemd/user && echo {HEAL_UNIT_B64} | base64 -d > ~/.config/systemd/user/dai-heal-test.service; "
         "rm -f /tmp/heal-ok; systemctl --user daemon-reload; systemctl --user start dai-heal-test.service; sleep 1; "
         "dai-heal status | grep -A1 dai-heal-test; "
         "KEY=$(dai-heal status --json | python3 -c 'import json,sys; print(next(p[\"key\"] for p in json.load(sys.stdin) "
         "if p[\"name\"] == \"dai-heal-test.service\"))'); dai-heal fix \"$KEY\" --yes; "
         "echo STATE=$(systemctl --user is-active dai-heal-test.service); systemctl --user stop dai-heal-test.service; "
         "rm -f ~/.config/systemd/user/dai-heal-test.service /tmp/heal-ok; systemctl --user daemon-reload", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "WATCHING" in o and "NO_DUMPS_KEPT" in o
         and "Your background service dai-heal-test.service failed" in o and "Fixed" in o and "STATE=active" in o, 60),
        ("heal: forge app crash", "printf 'raise ValueError(\"heal test\")\\n' > /tmp/crashy.py && "
         "dai-forge app add crashy /tmp/crashy.py --kind cli </dev/null >/dev/null; dai-forge app run crashy >/dev/null 2>&1; "
         "dai-heal status; echo y | dai-forge app remove crashy >/dev/null 2>&1", True,
         lambda o: "crashy" in o and "crashed" in o and "ValueError: heal test" in o, 60),
        ("heal: program crash recorded", "sleep 60 & P=$!; sleep 0.5; kill -SEGV $P; sleep 4; dai-heal status", False,
         lambda o: "sleep crashed" in o, 40),
        # D.Ai Evolve (docs/EVOLVE.md §3): a book no program opens and a command run every day become suggestions.
        ("evolve: notices what is missing", "export XDG_RUNTIME_DIR=/run/user/$(id -u); dai-evolve --version; "
         "echo TIMER=$(systemctl --user is-enabled dai-evolve.timer); mkdir -p ~/Downloads && printf x > ~/Downloads/novel.epub; "
         "for i in 1 2 3; do python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); "
         "from dai_evolve.store import count_command; count_command(\">df -h /\")'; done; "
         "dai-evolve scan; stat -c 'MODE=%a' ~/.local/state/dai/evolve/commands.json; "
         "dai-forge --dry-run 'install ebook-reader' </dev/null | grep -i foliate | head -n 3; "
         "dai-evolve off; test -e ~/.local/state/dai/evolve/commands.json || echo FORGOTTEN; dai-evolve; dai-evolve on >/dev/null; "
         "rm -f ~/Downloads/novel.epub", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "TIMER=enabled" in o and "Install an e-book reader" in o
         and "Let D.Ai do it every morning" in o and "MODE=600" in o and "foliate" in o and "FORGOTTEN" in o
         and "D.Ai Evolve is off" in o, 60),
        # D.Ai Quick (docs/TASKBAR.md §2.4): reads the real switches; do not disturb goes to LXQt and back.
        ("taskbar: quick settings", "export XDG_RUNTIME_DIR=/run/user/$(id -u); dai-quick --version; dai-quick --state; "
         "echo CLOCK=$(grep -c libdaiclock.so /proc/$(pgrep -x lxqt-panel | head -n1)/maps); "
         "python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); from dai_quick.controls import Controls; "
         "c = Controls(); c.set_dnd(True); print(\"DND_ON\", c.dnd()); c.set_dnd(False); print(\"DND_OFF\", c.dnd())'; "
         "grep -c '^doNotDisturb=false' ~/.config/lxqt/notifications.conf", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and '"wifi"' in o and '"volume"' in o and '"security"' in o
         and re.search(r"CLOCK=[1-9]", o) is not None and "DND_ON True" in o and "DND_OFF False" in o, 60),
        # Ruby (docs/BROWSER.md stage 1): Firefox ESR reads D.Ai's policies (root-owned), the menu shows one
        # browser named Ruby, the Hebrew interface is installed, and a headless start installs uBlock Origin and
        # Containers from Mozilla's add-on site (which proves the policies are active). Without a network the
        # add-ons cannot download; the check then says so instead of failing.
        ("ruby: private browsing policies", "python3 -c 'import json; p = json.load(open(\"/etc/firefox/policies/"
         "policies.json\"))[\"policies\"]; print(\"POLICIES\", len(p), p[\"HttpsOnlyMode\"])'; "
         "stat -c 'OWNER %U %a' /etc/firefox/policies/policies.json; "
         "echo DIVERTED=$(dpkg-divert --list | grep -c 'firefox-esr.desktop.debian'); "
         "grep -m1 '^Name=' /usr/share/applications/firefox-esr.desktop; "
         "dpkg -s firefox-esr-l10n-he >/dev/null 2>&1 && echo HEBREW_UI; "
         "rm -rf /tmp/ruby-test; mkdir /tmp/ruby-test; "
         "(timeout 150 firefox-esr --headless --no-remote --profile /tmp/ruby-test about:blank >/tmp/ruby.log 2>&1 &); "
         "for i in $(seq 120); do grep -q '@testpilot-containers' /tmp/ruby-test/extensions.json 2>/dev/null "
         "&& grep -q 'uBlock0@raymondhill.net' /tmp/ruby-test/extensions.json && break; sleep 1; done; "
         "grep -q 'uBlock0@raymondhill.net' /tmp/ruby-test/extensions.json 2>/dev/null && echo UBLOCK; "
         "grep -q '@testpilot-containers' /tmp/ruby-test/extensions.json 2>/dev/null && echo CONTAINERS; "
         "python3 -c 'import urllib.request; urllib.request.urlopen(\"https://addons.mozilla.org/\", timeout=10)' "
         ">/dev/null 2>&1 && echo NETWORK || echo NO_NETWORK; pkill -f ruby-test; tail -n 5 /tmp/ruby.log", True,
         lambda o: re.search(r"POLICIES \d+ enabled", o) is not None and "OWNER root 644" in o
         and "DIVERTED=1" in o and "Name=Ruby" in o and "HEBREW_UI" in o
         and ("UBLOCK" in o and "CONTAINERS" in o or "NO_NETWORK" in o), 200),
        # Raz (docs/RAZ.md stage 1): the same checks a user's computer runs, here before every release.
        ("raz: D.Ai checks itself", "export XDG_RUNTIME_DIR=/run/user/$(id -u); dai-raz check; echo RAZ_EXIT=$?; "
         "dai-raz last --json | python3 -c 'import json, sys; d = json.load(sys.stdin); "
         "print(\"RAZ_KEPT\", len(d[\"results\"]))'; stat -c 'RAZ_DIR %a' ~/.local/state/dai/raz", True,
         lambda o: "RAZ_EXIT=0" in o and "RAZ_KEPT 9" in o and "RAZ_DIR 700" in o and "✗" not in o, 120),
        # Raz stage 2, the update guard (docs/RAZ.md §3): apt knows the hook; a setting broken "by an update"
        # becomes a regression that Heal shows, and once it is repaired the next run clears it.
        ("raz: update guard", "export XDG_RUNTIME_DIR=/run/user/$(id -u); apt-config dump | grep -c dai-raz-guard; "
         "P=/etc/firefox/policies/policies.json; sudo /usr/lib/dai/dai-raz-guard pre; sudo chmod o+w $P; "
         "sudo /usr/lib/dai/dai-raz-guard post; python3 -c 'import json; d = json.load(open(\"/var/lib/dai/raz/"
         "regressions.json\")); print(\"REGRESSIONS\", [r[\"id\"] for r in d[\"regressions\"]])'; "
         "LANG=C.UTF-8 dai-heal status | grep -c 'last update broke' | sed 's/^/HEAL_SHOWS=/'; sudo chmod o-w $P; "
         "sudo /usr/lib/dai/dai-raz-guard post; LANG=C.UTF-8 dai-heal status | grep -c 'last update broke' | sed 's/^/HEAL_AFTER=/'",
         True, lambda o: "REGRESSIONS ['files']" in o and "HEAL_SHOWS=1" in o and "HEAL_AFTER=0" in o
         and re.search(r"^\s*2\s*$", o, re.M) is not None, 180),
        # J stage 2 (docs/MAIL.md §3.1): settings imported from a Thunderbird profile, read-only, no password.
        ("j: imports from other mail apps", "mkdir -p ~/.thunderbird/t.default; printf '%s\\n' "
         "'user_pref(\"mail.account.account1.server\", \"server1\");' "
         "'user_pref(\"mail.account.account1.identities\", \"id1\");' "
         "'user_pref(\"mail.identity.id1.useremail\", \"dana@example.org\");' "
         "'user_pref(\"mail.identity.id1.smtpServer\", \"smtp1\");' "
         "'user_pref(\"mail.server.server1.type\", \"imap\");' "
         "'user_pref(\"mail.server.server1.hostname\", \"imap.example.org\");' "
         "'user_pref(\"mail.server.server1.socketType\", 3);' "
         "'user_pref(\"mail.smtpserver.smtp1.hostname\", \"smtp.example.org\");' "
         "'user_pref(\"mail.smtpserver.smtp1.try_ssl\", 2);' > ~/.thunderbird/t.default/prefs.js; "
         "S=$(md5sum ~/.thunderbird/t.default/prefs.js); dai-j import --add; "
         "grep -c password ~/.local/share/dai-j/accounts.json | sed 's/^/PASSWORDS=/'; "
         "[ \"$S\" = \"$(md5sum ~/.thunderbird/t.default/prefs.js)\" ] && echo THUNDERBIRD_UNTOUCHED; "
         "rm -rf ~/.thunderbird ~/.local/share/dai-j", True,
         lambda o: '"dana@example.org"' in o and "PASSWORDS=0" in o and "THUNDERBIRD_UNTOUCHED" in o, 60),
        # MOM stage 2 (docs/MOM.md): the user's services and the system's, and a login app turned off and on again
        # with the user's own file (the system's file is never touched).
        ("mom: background and login apps", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "S=$(md5sum /etc/xdg/autostart/dai-clip.desktop); dai-mom startup off dai-clip.desktop | grep dai-clip; "
         "dai-mom startup on dai-clip.desktop | grep dai-clip; test -e ~/.config/autostart/dai-clip.desktop || "
         "echo USER_FILE_GONE; [ \"$S\" = \"$(md5sum /etc/xdg/autostart/dai-clip.desktop)\" ] && echo SYSTEM_UNTOUCHED; "
         # Only the lines that matter: the full list is long, and the report keeps the first 30 lines.
         "dai-mom services > /tmp/mom-services.txt; wc -l < /tmp/mom-services.txt; "
         "grep -E '^(user +active +dai-daid[.]socket|system +active +nftables[.]service)' /tmp/mom-services.txt",
         True, lambda o: re.search(r"^user\s+active\s+dai-daid\.socket", o, re.M) is not None
         and re.search(r"^system\s+active\s+nftables\.service", o, re.M) is not None
         and "off dai-clip.desktop" in o and "on  dai-clip.desktop" in o and "USER_FILE_GONE" in o
         and "SYSTEM_UNTOUCHED" in o, 60),
        # J (docs/MAIL.md stage 1): installed, finds Gmail's servers from the address alone, can keep passwords in
        # the keyring (secret-tool + a Secret Service on D-Bus), and is the handler for mailto: links.
        ("j: mail client", "dai-j --version; dai-j discover dana@gmail.com; "
         "command -v secret-tool >/dev/null && echo KEYRING_TOOL; ls /usr/share/dbus-1/services | grep -i secret; "
         "grep -h mailto /etc/xdg/mimeapps.list; "
         "python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); import dai_j.gui, dns.resolver; "
         "print(\"J_IMPORTS\")'", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and '"host": "imap.gmail.com"' in o and "KEYRING_TOOL" in o
         and "secrets" in o and "mailto=dai-j.desktop" in o and "J_IMPORTS" in o, 60),
        # MOM (docs/MOM.md stage 1): closes the user's own app, refuses to force a part of the session, and
        # groups processes into apps. A copy of sleep with its own name, so nothing else in the session is hit.
        ("mom: closes apps, protects the session", "export XDG_RUNTIME_DIR=/run/user/$(id -u); dai-mom --version; "
         "cp /usr/bin/sleep /tmp/dai-mom-test; /tmp/dai-mom-test 300 & sleep 1; dai-mom close dai-mom-test; "
         "echo RC_CLOSE=$?; sleep 1; pgrep -x dai-mom-test || echo TEST_GONE; dai-mom close --force labwc --yes; "
         "echo RC_PROTECT=$?; pgrep -x labwc >/dev/null && echo LABWC_ALIVE; dai-mom list --json | "
         "python3 -c 'import json, sys; a = json.load(sys.stdin); print(\"APPS\", len(a), "
         "sorted(x[\"key\"] for x in a if x[\"protected\"])[:6])'", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "RC_CLOSE=0" in o and "TEST_GONE" in o
         and "RC_PROTECT=3" in o and "LABWC_ALIVE" in o and "proc:labwc" in o, 60),
        # MOM stage 3 (docs/MOM.md §11): Diamond's facts about a process whose command line holds a password show
        # the password hidden; "explain" and "why" always answer (the local answer when no model is installed).
        ("mom: Diamond explains, secrets hidden", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "python3 -c 'import time; time.sleep(300)' --password hunter2 --token=abc123def456 & P=$!; sleep 1; "
         "dai-mom explain $P --facts > /tmp/mom-facts.txt; echo RC_FACTS=$?; "
         "grep -c hunter2 /tmp/mom-facts.txt || echo NO_PASSWORD; grep -c abc123def456 /tmp/mom-facts.txt || "
         "echo NO_TOKEN; grep -q '‹hidden›' /tmp/mom-facts.txt && echo HIDDEN_SHOWN; "
         "timeout 60 dai-mom explain $P > /tmp/mom-explain.txt; echo RC_EXPLAIN=$?; head -c 300 /tmp/mom-explain.txt; "
         "timeout 60 dai-mom why | head -n 5; kill $P", True,
         lambda o: "RC_FACTS=0" in o and "NO_PASSWORD" in o and "NO_TOKEN" in o and "HIDDEN_SHOWN" in o
         and "RC_EXPLAIN=0" in o, 150),
        # MOM stage 4 (docs/MOM.md §12): the guard starts at login, notices a copy of python that keeps a core busy
        # (thresholds shortened for the test), and never closes it.
        ("mom: the guard notices, never closes", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "test -f /etc/xdg/autostart/dai-mom-guard.desktop && echo AUTOSTART; "
         "cp \"$(readlink -f /usr/bin/python3)\" /tmp/dai-burn; /tmp/dai-burn -c 'while True: pass' & B=$!; "
         "timeout 90 dai-mom guard --cpu-seconds 10 --rounds 3 | head -n 5; "
         "kill -0 $B && echo STILL_RUNNING; kill $B", True,
         lambda o: "AUTOSTART" in o and "cpu proc:dai-burn" in o and "STILL_RUNNING" in o, 120),
        # Raz stage 4 (docs/RAZ.md §14): the daily timer is on for every user, a check keeps the boot time, the
        # week is told in words, and the problem report names neither the user nor the computer.
        ("raz: trends, week and report", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "systemctl --user is-enabled dai-raz.timer; dai-raz check --quiet; "
         "python3 -c 'import glob, json, os; f = sorted(glob.glob(os.path.expanduser(\"~/.local/state/dai/raz/run-*.json\")))[-1]; "
         "print(\"BOOT\", json.load(open(f))[\"metrics\"][\"boot_seconds\"])'; dai-raz week; dai-raz improve; "
         "dai-raz report 2>/dev/null > /tmp/raz-report.txt; head -n 4 /tmp/raz-report.txt; "
         "grep -cE \"(^|[^[:alnum:]_.-])($(id -un)|$(hostname))([^[:alnum:]_.-]|$)\" /tmp/raz-report.txt || echo NO_NAMES",
         True,
         lambda o: re.search(r"^enabled", o, re.M) is not None and re.search(r"^BOOT \d", o, re.M) is not None
         and ("everything worked" in o or "Not working" in o) and "nothing was sent" in o and "NO_NAMES" in o, 90),
        # Languages, stage 3 (docs/I18N.md §9): "language russian" through Tune generates the locale (root, through
        # the helper) and keeps the choice for the next login (user); the recipe exists. Cleaned up afterwards.
        ("i18n: choose the language", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "DAI_TUNE_ELEVATE=sudo dai-tune --yes 'language russian' >/dev/null; echo RC=$?; "
         "grep -x 'ru_RU.UTF-8 UTF-8' /etc/locale.gen; locale -a | grep -ix ru_RU.utf8; cat ~/.config/dai/language.env; "
         "dai-forge recipe list 2>/dev/null | grep -c language- ; rm -f ~/.config/dai/language.env", True,
         lambda o: "RC=0" in o and "ru_RU.UTF-8 UTF-8" in o and re.search(r"^ru_RU\.utf8$", o, re.M | re.I) is not None
         and "LANG=ru_RU.UTF-8" in o and "LANGUAGE=ru:en" in o and re.search(r"^6$", o, re.M) is not None, 180),
        # i18n stage 3b (docs/I18N.md §9): the boot menu on the medium has the eight languages, and the default
        # entry (the one this test booted) is still English and Hebrew.
        ("i18n: boot menu languages", "grep -ho 'dai-languages-[a-z]*' /run/live/medium/boot/grub/grub.cfg "
         "/run/live/medium/isolinux/live.cfg 2>/dev/null | sort -u | tr '\\n' ' '; echo; grep -o 'locales=[^ ]*' /proc/cmdline",
         True, lambda o: all(f"dai-languages-{c} " in o for c in ("en", "he", "ar", "ru", "es", "fr", "de", "pt"))
         and "locales=en_US.UTF-8,he_IL.UTF-8" in o, 30),
        # J stage 2b (docs/MAIL.md §11): a Thunderbird "Local Folders" mbox is copied into J's local folders, the
        # message marked deleted is not, importing again adds nothing, and Thunderbird's file is not changed.
        ("j: mail kept on this computer", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "D=~/.thunderbird/t.default; mkdir -p \"$D/Mail/Local Folders\"; echo 'user_pref(\"x\", 1);' > $D/prefs.js; "
         "printf 'From a@b Mon Oct 12 10:00:00 2026\\nFrom: Dana <dana@example.org>\\nSubject: Kept\\n"
         "Message-ID: <k1@example.org>\\nX-Mozilla-Status: 0001\\n\\nhello\\n\\n"
         "From a@b Mon Oct 12 10:01:00 2026\\nFrom: Dana <dana@example.org>\\nSubject: Gone\\n"
         "Message-ID: <k2@example.org>\\nX-Mozilla-Status: 0009\\n\\nbye\\n' > \"$D/Mail/Local Folders/Inbox\"; "
         "S=$(md5sum \"$D/Mail/Local Folders/Inbox\"); dai-j import-mail | tr -d ' \\n'; echo; dai-j import-mail | tr -d ' \\n'; "
         "echo; [ \"$S\" = \"$(md5sum \"$D/Mail/Local Folders/Inbox\")\" ] && echo SOURCE_UNTOUCHED; "
         "stat -c %a ~/.local/share/dai-j/mail.sqlite; rm -rf ~/.thunderbird", True,
         lambda o: '"added":1,"skipped":1' in o and '"added":0,"skipped":2' in o and "SOURCE_UNTOUCHED" in o
         and re.search(r"^600$", o, re.M) is not None, 60),
        # OS basics on Wayland: drives mount by themselves, the screens can be read and arranged, Print works,
        # and the medium boots with Secure Boot on (Debian's signed shim and GRUB).
        ("os: drives mount by themselves", "udisksctl status >/dev/null 2>&1 && echo UDISKS; "
         "test -x /usr/libexec/gvfsd && echo GVFS; systemctl is-enabled udisks2 2>/dev/null", True,
         lambda o: "UDISKS" in o and "GVFS" in o, 60),
        ("os: screens on Wayland", WAYLAND_ENV + "wlr-randr 2>&1 | head -n 8; command -v wdisplays >/dev/null && echo WDISPLAYS",
         True, lambda o: re.search(r"\d+x\d+ px", o) is not None, 30),
        ("os: screenshot (Print)", WAYLAND_ENV + "f=$(dai-screenshot 2>/dev/null) && test -s \"$f\" && echo SHOT_OK; "
         "rm -f -- \"$f\"", True, lambda o: "SHOT_OK" in o, 40),
        ("os: secure boot shim", "for f in $(find /run/live/medium -iname 'bootx64.efi' -o -iname 'efi.img' 2>/dev/null); do "
         "printf '%s ' \"$f\"; grep -c -a 'UEFI SHIM' \"$f\"; done; find /run/live/medium -iname 'grubx64.efi' | head -n 2",
         False, lambda o: re.search(r" [1-9]\d*$", o, re.M) is not None, 60),
        # The way to the desktop (docs/V2.md D2): the D.Ai Plymouth theme is the default and is inside the initrd
        # (where the disk passphrase is asked), the USB menu got D.Ai's look, and the login theme loads.
        ("boot: D.Ai loading screen (Plymouth)", "/usr/sbin/plymouth-set-default-theme; "
         "lsinitramfs $(ls /run/live/medium/live/initrd.img* | head -n 1) 2>/dev/null | grep -c 'plymouth/themes/dai/'; "
         "grep -c 'Start D.Ai OS' /run/live/medium/isolinux/live.cfg /run/live/medium/boot/grub/grub.cfg 2>/dev/null; "
         "grep -c 'menu title D.Ai OS' /run/live/medium/isolinux/menu.cfg",
         True, lambda o: re.search(r"^dai$", o, re.M) is not None and re.search(r"^[1-9]\d*$", o, re.M) is not None
         and "live.cfg:0" not in o and re.search(r"^0$", o, re.M) is None, 90),
        ("login: D.Ai login screen loads (SDDM)", "cd /tmp && QT_QPA_PLATFORM=offscreen timeout 12 sddm-greeter-qt6 "
         "--test-mode --theme /usr/share/sddm/themes/dai >/tmp/greeter.log 2>&1; echo GREETER_RC=$?; "
         "grep -E 'themes/dai/.*(Error|error|TypeError|ReferenceError|not installed|is not a type)' /tmp/greeter.log "
         "| head -n 5 | sed 's/^/QML_''ERROR: /'; grep 'themes/dai/' /tmp/greeter.log | head -n 3", True,
         lambda o: "GREETER_RC=124" in o and "QML_ERROR:" not in o, 40),
        # D.Ai OCR (docs/V2.md F1): the text of a picture, read on the VM in English and Hebrew (the Hebrew word is
        # checked as \xNN so only ASCII crosses the serial line).
        ("ocr: text from a picture (English and Hebrew)", f"echo {OCR_PICTURE_B64} | base64 -d > /tmp/ocr-picture.py && "
         "QT_QPA_PLATFORM=offscreen python3 /tmp/ocr-picture.py /tmp/ocr.png && "
         "dai-ocr --file /tmp/ocr.png --print --lang he,en > /tmp/ocr.txt; echo OCR_RC=$?; cat /tmp/ocr.txt | head -n 4; "
         f"grep -c \"$(printf '{_hex('שלום')}')\" /tmp/ocr.txt; tesseract --list-langs 2>/dev/null | tr '\\n' ' '",
         True, lambda o: "OCR_RC=0" in o and "Hello" in o and "2026" in o, 90),
        # D.Ai sounds (docs/SOUNDS.md): the theme is installed, one sound really plays through PipeWire, quiet and off
        # are respected, and the USB/charger watcher started with the session (its command line is the launcher's
        # "python3 -I -c '<code>' watch", so it is found by "dai_sound ... watch", not by "dai-sound watch").
        ("sound: the diamond family plays", WAYLAND_ENV + "ls /usr/share/sounds/dai/stereo/ | grep -c '\\.oga$'; "
         "dai-sound complete; echo PLAY_RC=$?; sleep 1; dai-sound off; dai-sound complete; echo OFF_RC=$?; "
         "dai-sound on; sleep 1; pgrep -u $(id -u) -f 'dai_sound.* watch$' >/dev/null && echo WATCH''ING; "
         "pgrep -u $(id -u) -af dai_''sound | cut -c1-60; "
         "timeout 5 pw-play --volume 0.1 /usr/share/sounds/dai/stereo/bell.oga; echo PW_RC=$?",
         True, lambda o: re.search(r"^1[5-9]$", o, re.M) is not None and "PLAY_RC=0" in o and "OFF_RC=1" in o
         and "WATCHING" in o, 40),  # PW_RC is information: a VM may have no sound card
        # Diamond Chat (docs/SEND.md): the encryption library is there, and Tor is NOT running as a system service.
        ("chat: no system Tor at boot", "python3 -c 'import nacl.bindings, zeroconf; print(\"NACL\" + \"_OK\")'; "
         "command -v tor >/dev/null && echo TOR_''INSTALLED; systemctl is-active tor.service tor@default.service; "
         "pgrep -x tor >/dev/null && echo TOR_''RUNNING || echo TOR_''IDLE",
         True, lambda o: "NACL_OK" in o and "TOR_INSTALLED" in o and "TOR_IDLE" in o and "\nactive" not in "\n" + o, 30),
        # Diamond Chat (docs/SEND.md): an invitation code, a valid user unit, the service with the person's own Tor
        # (not a system one), and Tor gone when the service stops.
        ("chat: the service and its own Tor", WAYLAND_ENV + "dai-chat name 'VM test' >/dev/null; dai-chat code | grep -c '^dai1-'; "
         "systemd-analyze --user verify /usr/lib/systemd/user/dai-chat.service >/tmp/chat-unit 2>&1; "
         "echo UNIT_RC=$?; head -n 3 /tmp/chat-unit; dai-chat ''run >/tmp/chat-run.log 2>&1 & CHAT=$!; "
         "for i in $(seq 1 30); do dai-chat status >/tmp/chat-status 2>&1 && break; sleep 1; done; "
         "cat /tmp/chat-status; sleep 5; pgrep -u $(id -u) -x tor >/dev/null && echo TOR_''AS_USER; "
         "stat -c %a $XDG_RUNTIME_DIR/dai-chat; kill $CHAT; sleep 4; "
         "pgrep -x tor >/dev/null && echo TOR_''LEFT || echo TOR_''GONE; tail -n 5 /tmp/chat-run.log",
         True, lambda o: re.search(r"^1$", o, re.M) is not None and "UNIT_RC=0" in o and "Tor:" in o
         and "TOR_AS_USER" in o and re.search(r"^700$", o, re.M) is not None and "TOR_GONE" in o, 90),
        # Diamond Chat pictures (docs/SEND.md): Debian's Qt decodes them inside bubblewrap, and a hidden location goes.
        ("chat: pictures are re-drawn in the sandbox", f"echo {CHAT_PICTURE_B64} | base64 -d > /tmp/chat-picture.py && "
         "python3 -I /tmp/chat-picture.py", True, lambda o: "image/jpeg GONE" in o, 60),
        # D.Ai PDF (docs/PDF.md): the default handler, a file with JavaScript and an attachment is opened only
        # through the bubblewrap helper, what it wants is listed and not done, and the text comes out.
        ("pdf: opened in the sandbox, wants listed, text out", f"echo {PDF_CHECK_B64} | base64 -d > /tmp/pdf-check.py && "
         "python3 -I /tmp/pdf-check.py; dai-pdf check /tmp/wants.pdf; echo CHECK_RC=$?; dai-pdf text /tmp/wants.pdf; "
         "xdg-mime query default application/pdf; "
         # Stage 2 (editing) in the sandbox: a merged, turned copy and the form's fields, from the command line.
         "dai-pdf merge /tmp/wants.pdf /tmp/wants.pdf -o /tmp/two.pdf; dai-pdf rotate /tmp/two.pdf --by 90 --pages 2 -o /tmp/turned.pdf; "
         "echo EDIT_RC=$?; dai-pdf info /tmp/turned.pdf | grep -E '^Pages'; dai-pdf fields /tmp/wants.pdf | head -n 3; "
         "ls -l /tmp/turned.pdf | cut -c1-10; "
         # Stage 3: a black box that truly removes, metadata gone, a text layer from Tesseract (Hebrew and English on
         # the image), pages as pictures; all inside the sandbox.
         "dai-pdf redact /tmp/wants.pdf --page 1 --box 10,80,280,40 -o /tmp/black.pdf >/dev/null; echo REDACT_RC=$?; "
         "dai-pdf text /tmp/black.pdf | grep -c sandbox | sed 's/^/WORDS_LEFT=/'; dai-pdf strip /tmp/wants.pdf -o /tmp/clean.pdf >/dev/null; "
         "dai-pdf info /tmp/clean.pdf | grep -c '^Title' | sed 's/^/TITLE_LEFT=/'; "
         "dai-pdf ocr /tmp/black.pdf -o /tmp/ocr.pdf; echo OCR_RC=$?; dai-pdf export /tmp/wants.pdf --dir /tmp/pics --dpi 72 | wc -l | sed 's/^/PICS=/'",
         True, lambda o: "SANDBOXED" in o and "CHECK_RC=1" in o and "JavaScript" in o and "Hello sandbox" in o
         and "dai-pdf.desktop" in o and "EDIT_RC=0" in o and "Pages: 2" in o and "-rw-------" in o
         and "REDACT_RC=0" in o and "WORDS_LEFT=0" in o and "TITLE_LEFT=0" in o and "OCR_RC=0" in o and "PICS=1" in o, 420),
        # D.Ai TV (docs/TV.md §5): the television session is the default and is what runs (Kodi on labwc, no
        # LXQt), Kodi's defaults keep every server off and speak Hebrew, CEC's tool is there, nothing listens.
        ("tv: the session, Kodi, the defaults, nothing listening",
         ". /etc/dai-release; if [ \"$EDITION\" != tv ]; then echo TV_NOT_THIS_EDITION; else "
         "grep -h Session= /etc/sddm.conf /etc/sddm.conf.d/*.conf; pgrep -af 'kodi' | grep -c -v grep | sed 's/^/KODI_PROCS=/'; "
         "pgrep -x lxqt-session >/dev/null && echo LXQT_RUNNING || echo NO_LXQT; kodi --version | head -n 1; "
         # Kodi rewrites guisettings.xml with a default="..." attribute, so the patterns allow attributes.
         "grep -cE 'id=.services.webserver.[^>]*>false' ~/.kodi/userdata/guisettings.xml | sed 's/^/WEBSERVER_OFF=/'; "
         "grep -cE 'id=.locale.language.[^>]*>resource.language.he_il' ~/.kodi/userdata/guisettings.xml | sed 's/^/HEBREW=/'; "
         "test -d ~/.kodi/addons/resource.language.he_il && echo HE_PACK; command -v cec-client >/dev/null && echo CEC_TOOL; "
         # Nothing reachable from the network: loopback listeners (the local print service) do not count.
         "ss -ltnH | awk '{print $4}' | grep -vE '^(127[.]|[[]::1[]])' | sed 's/^/OPEN=/'; echo LISTENERS_CHECKED; "
         "grep -iE 'Loaded language|windowing|Running on' ~/.kodi/temp/kodi.log 2>/dev/null | head -n 4; fi",
         True, lambda o: "TV_NOT_THIS_EDITION" in o or (all(mark in o for mark in (
             "dai-tv.desktop", "NO_LXQT", "HE_PACK", "CEC_TOOL", "LISTENERS_CHECKED", "HEBREW=1"))
          and re.search(r"WEBSERVER_OFF=[1-9]", o)
             and "LXQT_RUNNING" not in o and "OPEN=" not in o and "KODI_PROCS=0" not in o), 90),
        # D.Ai TV stage 2 (docs/TV.md §8): "remote control from the phone" turns Kodi's services on and opens the
        # three ports to the local network only; undo closes them and puts Kodi's settings back.
        ("tv: remote control from the phone, with undo",
         ". /etc/dai-release; if [ \"$EDITION\" != tv ]; then echo TV_NOT_THIS_EDITION; else "
         "cp ~/.kodi/userdata/guisettings.xml /tmp/gui-before.xml; echo yes | DAI_TUNE_ELEVATE=sudo dai-tune 'שלט מהטלפון' >/tmp/tune-tv.txt 2>&1; echo TUNE_RC=$?; "
         "grep -cE 'id=.services.webserver.>true' ~/.kodi/userdata/guisettings.xml | sed 's/^/WEB_ON=/'; "
         "grep -cE 'id=.services.esallinterfaces.>true' ~/.kodi/userdata/guisettings.xml | sed 's/^/ES_ON=/'; "
         "sudo nft list chain inet dai_filter input | grep -cE 'dport (8080|9090|9777)' | sed 's/^/PORTS=/'; "
         "DAI_TUNE_ELEVATE=sudo dai-tune undo >/dev/null 2>&1; DAI_TUNE_ELEVATE=sudo dai-tune undo >/dev/null 2>&1; "
         "sudo nft list chain inet dai_filter input | grep -cE 'dport (8080|9090|9777)' | sed 's/^/PORTS_AFTER=/'; "
         "cmp -s /tmp/gui-before.xml ~/.kodi/userdata/guisettings.xml && echo SETTINGS_RESTORED || diff /tmp/gui-before.xml ~/.kodi/userdata/guisettings.xml | head -n 6; "
         "tail -n 3 /tmp/tune-tv.txt; fi",
         True, lambda o: "TV_NOT_THIS_EDITION" in o or all(mark in o for mark in (
             "TUNE_RC=0", "WEB_ON=1", "ES_ON=1", "PORTS_AFTER=0", "SETTINGS_RESTORED")) and re.search(r"PORTS=[3-9]", o) is not None, 120),
        # D.Ai TV stage 2b (docs/TV.md §9): Kodi's service listens on this computer only, and dai-tv reaches it.
        ("tv: D.Ai talks to Kodi on this computer only",
         ". /etc/dai-release; if [ \"$EDITION\" != tv ]; then echo TV_NOT_THIS_EDITION; else "
         "ss -ltnH | grep 9090 | awk '{print \"RPC_LISTEN=\" $4}'; dai-tv ping; echo PING_RC=$?; dai-tv playing; "
         "dai-tv say 'שלום מ-D.Ai'; echo SAY_RC=$?; dai-tv do info; echo DO_RC=$?; dai-tv ask 'מה זה' | head -c 200; echo; echo ASK_RC=$?; fi",
         True, lambda o: "TV_NOT_THIS_EDITION" in o or (all(mark in o for mark in (
             "RPC_LISTEN=127.0.0.1:9090", "pong", "PING_RC=0", "SAY_RC=0", "DO_RC=0", "ASK_RC=0"))
             and "RPC_LISTEN=0.0.0.0" not in o and "RPC_LISTEN=*" not in o), 120),
        # D.Ai VM (docs/VM.md): the stack is there, the check says plainly there is no KVM in this VM, and libvirt
        # accepts a whole machine definition (define, state, undefine). Only in the editions that ship it.
        ("vm: the stack, the honest check, a definition libvirt accepts",
         # No `exit` here: the checks share one shell over the serial line, and an exit would end it.
         "if ! command -v virsh >/dev/null; then echo VM_NOT_IN_THIS_EDITION; else dai-vm check; echo CHECK_RC=$?; "
         f"echo {VM_CHECK_B64} | base64 -d > /tmp/vm-check.py && python3 -I /tmp/vm-check.py; fi",
         True, lambda o: "VM_NOT_IN_THIS_EDITION" in o or all(mark in o for mark in (
             "CHECK_RC=1", "✗", "FIRMWARE TOOLS_OK", "DEFINED shut off", "SHARED_DEFINED shut off True",
             "TUNE_RC 0", "UNDO_RC 0", "UNDEFINED missing")), 300),
        # OS basics, stage 2 (docs/BASICS.md §2): optional packages, so a WARN (not a FAIL) when Debian lacks one.
        ("os: firmware, codecs, printers", "command -v fwupdmgr && echo FWUPD; "
         "ls /usr/lib/x86_64-linux-gnu/gstreamer-1.0/ 2>/dev/null | grep -c -E 'libgst(libav|isomp4|matroska)\\.so'; "
         "command -v hp-setup && echo HPLIP; systemctl is-enabled ipp-usb cups-browsed 2>/dev/null", False,
         lambda o: "FWUPD" in o and "HPLIP" in o and re.search(r"^[23]$", o, re.M) is not None, 60),
        ("os: night light and on-screen keyboard", WAYLAND_ENV + "labwc --version 2>&1 | head -n 1; "
         "timeout 3 wlsunset -t 4000 -T 6500 -S 07:00 -s 19:00 >/dev/null 2>&1; echo SUNSET_RC=$?; "
         "command -v wvkbd-mobintl && echo WVKBD; test -x /usr/bin/dai-nightlight && test -x /usr/bin/dai-keyboard && echo SCRIPTS",
         False, lambda o: "SUNSET_RC=124" in o and "WVKBD" in o and "SCRIPTS" in o, 30),
        # Touch (docs/MOBILE.md A1): the profile reads the hardware (no touch screen in QEMU), the environment and
        # D.Ai Tune's file, with undo; wvkbd can start hidden (-H) and dai-keyboard toggles it with SIGRTMIN.
        ("touch: the profile, Tune, the keyboard", WAYLAND_ENV + "echo CmltcG9ydCBzeXMKc3lzLnBhdGguaW5zZXJ0KDAsICIvdXNyL2xpYi9kYWkiKQppbXBvcnQgZGFpX3N0eWxlCnByaW50KCJTQ1JFRU4iIGlmIGRhaV9zdHlsZS50b3VjaHNjcmVlbl9wcmVzZW50KCkgZWxzZSAiTk9fU0NSRUVOIikKcHJpbnQoIkFVVE8iLCBkYWlfc3R5bGUudG91Y2hfbW9kZSgpLCAiT04iIGlmIGRhaV9zdHlsZS50b3VjaCgpIGVsc2UgIk9GRiIpCnByaW50KCJFTlYiLCAiT04iIGlmIGRhaV9zdHlsZS50b3VjaCh7IkRBSV9UT1VDSCI6ICIxIn0pIGVsc2UgIk9GRiIpCnByaW50KCJTSEVFVCIsIGxlbihkYWlfc3R5bGUud2l0aF90b3VjaCgiIiwgb249VHJ1ZSkpID4gMTAwKQo= | base64 -d > /tmp/touch-check.py && python3 -I /tmp/touch-check.py; "
         "dai-tune --yes 'מצב מגע' >/dev/null; echo TUNE_RC=$?; cat ~/.config/dai/touch | sed 's/^/FILE=/'; "
         "python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); import dai_style; print(\"NOW\", \"ON\" if dai_style.touch() else \"OFF\")'; "
         "dai-tune undo >/dev/null 2>&1; test -f ~/.config/dai/touch && echo FILE_LEFT || echo FILE_GONE; "
         "wvkbd-mobintl -h 2>&1 | grep -c -- '--hidden' | sed 's/^/HIDDEN_FLAG=/'; wvkbd-mobintl -L 260 --hidden >/tmp/wvkbd.log 2>&1 & sleep 2; "
         "pgrep -x wvkbd-mobintl >/dev/null && echo KBD_RUNNING || cat /tmp/wvkbd.log; dai-keyboard & sleep 2; "
         "pgrep -x wvkbd-mobintl >/dev/null && echo KBD_STILL_RUNNING; pgrep -c -x wvkbd-mobintl | sed 's/^/KBD_PROCS=/'; "
         "pkill -x wvkbd-mobintl; grep -c 'wvkbd-mobintl -L 260 --hidden' ~/.config/labwc/autostart | sed 's/^/AUTOSTART=/'",
         False, lambda o: all(mark in o for mark in ("NO_SCREEN", "AUTO auto OFF", "ENV ON", "SHEET True", "TUNE_RC=0", "FILE=on",
                                                     "NOW ON", "FILE_GONE", "KBD_RUNNING", "KBD_STILL_RUNNING", "KBD_PROCS=1", "AUTOSTART=1"))
         and "HIDDEN_FLAG=0" not in o, 60),
        # Touch, A2 (docs/MOBILE.md): the panel grows for touch and comes back, and the responsive pieces import.
        ("touch: the panel and the responsive pieces", "cp ~/.config/lxqt/panel.conf /tmp/panel.conf; dai-panel-touch on /tmp/panel.conf; "
         "grep -E '^(panelSize|iconSize|width|buttonWidth)=' /tmp/panel.conf | tr '\\n' ' '; echo; dai-panel-touch off /tmp/panel.conf; "
         "cmp -s /tmp/panel.conf ~/.config/lxqt/panel.conf && echo PANEL_RESTORED; grep -c dai-panel-touch /usr/bin/startdai-wayland | sed 's/^/LOGIN_HOOK=/'; "
         "QT_QPA_PLATFORM=offscreen python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); from dai_style.panes import Panes, WrapRow, fit_width; print(\"PIECES\", fit_width(720))'",
         False, lambda o: all(mark in o for mark in ("panelSize=72", "iconSize=36", "width=100", "buttonWidth=64", "PANEL_RESTORED",
                                                     "PIECES 720")) and re.search(r"LOGIN_HOOK=[1-9]", o) is not None, 30),
        # J (docs/MAIL.md §11): readpst is on the image for Outlook files, and a file that is not one is refused.
        ("j: outlook files", "command -v readpst >/dev/null && echo READPST; printf '!BDN' > /tmp/x.pst; "
         "dai-j import-mail /tmp/x.pst >/dev/null 2>&1; echo PST_RC=$?; rm -f /tmp/x.pst", False,
         lambda o: "READPST" in o and "PST_RC=1" in o, 60),
        # J stage 4b (docs/MAIL.md §14): the image's own GnuPG checks a signed mail, with a throwaway key; one changed
        # word makes it "bad".
        ("j: signed mail checked", "export GNUPGHOME=$(mktemp -d); "
         "gpg --batch --pinentry-mode loopback --passphrase '' --quick-gen-key 'Dana VM <dana@example.org>' "
         "default default 1d 2>/dev/null; printf 'Content-Type: text/plain\\r\\n\\r\\nhello\\r\\n' > $GNUPGHOME/in; "
         "gpg --batch --pinentry-mode loopback --passphrase '' -a --detach-sign -o $GNUPGHOME/sig $GNUPGHOME/in; "
         "python3 -I -c 'import sys, os; sys.path.insert(0, \"/usr/lib/dai\"); from dai_j import pgp; "
         "h = os.environ[\"GNUPGHOME\"]; inner = open(h + \"/in\", \"rb\").read(); sig = open(h + \"/sig\", \"rb\").read(); "
         "mk = lambda body: b\"Subject: s\\r\\nContent-Type: multipart/signed; protocol=\\\"application/pgp-signature\\\"; "
         "boundary=\\\"B\\\"\\r\\n\\r\\n--B\\r\\n\" + body + b\"\\r\\n--B\\r\\nContent-Type: application/pgp-signature\\r\\n\\r\\n\" "
         "+ sig + b\"\\r\\n--B--\\r\\n\"; "
         "print(\"SIG\", pgp.verify(mk(inner)).state, pgp.verify(mk(inner.replace(b\"hello\", b\"hellO\"))).state)'; "
         "gpgconf --kill all; rm -r -- \"$GNUPGHOME\"", True,
         lambda o: "SIG good bad" in o, 90),
        # Ruby stage 3 (docs/BROWSER.md §11): Firefox finds the native host, only Ruby may start it, it refuses an
        # action outside its list, and answers (or says Diamond is unavailable) without crashing.
        ("ruby: Diamond's native host", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "M=/usr/lib/mozilla/native-messaging-hosts/io.github.dai_os.ruby_diamond.json; "
         "python3 -c 'import json, sys; m = json.load(open(sys.argv[1])); print(\"ALLOWED\", m[\"allowed_extensions\"])' $M; "
         "for req in '{\"action\": \"shell\", \"text\": \"id\"}' '{\"action\": \"summarize\", \"text\": \"Hello\"}'; do "
         "python3 -c 'import json, struct, sys; d = sys.argv[1].encode(); sys.stdout.buffer.write(struct.pack(\"<I\", len(d)) + d)' \"$req\" "
         "| timeout 120 /usr/lib/dai/dai-ruby-diamond | python3 -c 'import json, struct, sys; r = sys.stdin.buffer.read(); "
         "n = struct.unpack(\"<I\", r[:4])[0]; print(\"ANSWER\", json.loads(r[4:4 + n]))'; done", True,
         lambda o: "ALLOWED ['ruby@dai-os.github.io']" in o and "ANSWER {'ok': False, 'error': 'invalid'}" in o
         and ("ANSWER {'ok': True" in o or "ANSWER {'ok': False, 'error': 'unavailable'}" in o), 150),
        # Languages (docs/I18N.md stage 1): every app reads the language through dai_i18n; other languages fall
        # back to English until their catalog exists, Hebrew stays Hebrew, and nothing crashes.
        ("i18n: languages fall back safely", "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
         "for l in ru_RU ar_EG pt_BR; do echo \"== $l\"; LANG=$l.UTF-8 dai-heal status 2>&1 | head -n 2; "
         "LANG=$l.UTF-8 dai-tune status 2>&1 | head -n 1; done; echo '== he'; LANG=he_IL.UTF-8 dai-evolve wishes; "
         "python3 -I -c 'import sys; sys.path.insert(0, \"/usr/lib/dai\"); import dai_i18n; "
         "print(\"I18N\", dai_i18n.__author__, dai_i18n.is_rtl(\"ar\"))'", True,
         lambda o: "Traceback" not in o and o.count("== ") == 4 and "I18N Diamond Rubinny (d.Ai) True" in o
         and re.search(r"== he\n[^\n]*[\u0590-\u05ff]", o) is not None, 60),
        # D.Ai OEM, the whole cycle in the live session (last: it resets the machine ID and journal).
        # LUKS is not part of it here (no installed disk); unit tests run it against a fake and real cryptsetup.
        ("oem: prepare, finish, cleanup", "dai-oem --version; sudo useradd -m -G sudo,audio,lpadmin oemtest; "
         "sudo dai-oem prepare --remove-user oemtest --yes --allow-live; dai-oem status; "
         "grep -c '^User=dai-setup' /etc/sddm.conf; test -f /usr/local/share/wayland-sessions/dai-oem.desktop && echo SESSION_READY; "
         "printf '%s' '{\"full_name\": \"Dana Levi\", \"username\": \"dana\", \"password\": \"correct horse 9\", "
         "\"hostname\": \"dana-pc\", \"language\": \"en\"}' | sudo /usr/lib/dai/dai-oem-helper complete; "
         "id dana; sudo grep -c '^dana:[$]y[$]' /etc/shadow; cat /etc/hostname; "
         "grep -q dai-setup /etc/sddm.conf || echo SDDM_RESTORED; "
         "sudo dai-oem cleanup; getent passwd oemtest dai-setup || echo TEMP_USERS_GONE; dai-oem status; "
         "sudo userdel -r dana; sudo hostnamectl set-hostname dai-os", True,
         lambda o: "Diamond Rubinny (d.Ai)" in o and "Prepared" in o and "SESSION_READY" in o
         and '{"ok": true}' in o and "(sudo)" in o and "(lpadmin)" in o and "dana-pc" in o
         and "SDDM_RESTORED" in o and "TEMP_USERS_GONE" in o and "Not prepared" in o, 120),
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
        # Facts for docs/SNAPSHOTS.md: what the installer does with Btrfs.
        ("build info", "cat /usr/share/dai/build-info"),
        ("calamares btrfs", "for f in /etc/calamares/modules/mount.conf /usr/share/calamares/modules/mount.conf; do "
         "test -f $f && echo \"== $f\" && grep -n -i -A3 'btrfs\\|subvol' $f | grep -v '^[0-9]*[-:] *#' | head -n 30; done; "
         "echo \"modules: $(ls /etc/calamares/modules/ | tr '\\n' ' ')\""),
        # Packages of the D.Ai Evolve recipes (docs/EVOLVE.md §3) in this Debian release.
        ("evolve recipe packages", "apt-cache policy foliate vlc gimp unar 7zip | grep -E '^[a-z0-9]|Candidate'"),
        ("layer-shell packages", "dpkg -l | grep -Ei 'layer-?shell' | cut -c1-80"),
    ]

    failed_required = 0
    lines = [f"[INFO] edition: {edition or '?'}"]
    for check in checks:
        name, command, required, ok = check[:4]
        timeout = check[4] if len(check) > 4 else 30
        if edition == "tv" and name not in TV_REQUIRED and not name.startswith("tv:"):
            required = False
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
