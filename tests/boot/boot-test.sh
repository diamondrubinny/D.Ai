#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Headless boot test for a D.Ai OS live ISO.
#
# Boots the ISO's live kernel in QEMU with a serial console and passes when
# the system reaches a login prompt. Also captures a screenshot of the
# graphical session and logs in over serial to verify desktop, firewall and
# hardening (tests/boot/serial_check.py).
#
# Usage: boot-test.sh <path-to-iso> [artifact-dir]
#
# Environment:
#   BOOT_TIMEOUT  Seconds to wait for the login prompt (default: 600)
#   DESKTOP_WAIT  Seconds to wait after login prompt before the screenshot (default: 60)
#   APPS_WAIT     Seconds to wait for demo apps before the second screenshot (default: 20)
#   QEMU_MEM      Guest memory in MB (default: 6144)
#   QEMU_SMP      Guest CPUs (default: 2)
#   MEASURE_JSON  If set, measure login, desktop and memory use after login into this file (measure.py)
#   MEASURE_ONLY  If 1, stop after the measurement (no screenshots, no interactive checks)
set -euo pipefail

readonly ISO="${1:-}"
ARTIFACT_DIR="$(realpath -m "${2:-boot-artifacts}")"
readonly BOOT_TIMEOUT="${BOOT_TIMEOUT:-600}"
readonly DESKTOP_WAIT="${DESKTOP_WAIT:-60}"
readonly APPS_WAIT="${APPS_WAIT:-20}"
readonly QEMU_MEM="${QEMU_MEM:-6144}"
readonly QEMU_SMP="${QEMU_SMP:-2}"
readonly MEASURE_JSON="${MEASURE_JSON:-}"
readonly MEASURE_ONLY="${MEASURE_ONLY:-0}"
readonly LOGIN_PATTERN='dai-os login:'
readonly PANIC_PATTERN='Kernel panic|end Kernel panic|Unable to find a medium containing a live file system'

log() { printf '[boot-test] %s\n' "$*" >&2; }
die() { log "FAIL: $*"; exit 1; }

[[ -f "$ISO" ]] || die "usage: $(basename "$0") <iso> [artifact-dir]"
# An arm64 image (the phone edition, docs/MOBILE.md C1; the tv edition for ARM boxes, docs/TV.md §14) boots in
# QEMU's virt machine, the kernel loaded directly, the ISO on a virtio SCSI CD, the console on ttyAMA0;
# everything else below is the same. The phone boots into Phosh, so the desktop's checks do not apply to it.
PHONE=0
[[ "$(basename "$ISO")" == dai-os-phone-* ]] && PHONE=1
ARM64=0
[[ "$(basename "$ISO")" == *-arm64.iso ]] && ARM64=1
readonly PHONE ARM64
QEMU_BIN=qemu-system-x86_64
[[ "$ARM64" == 1 ]] && QEMU_BIN=qemu-system-aarch64
readonly QEMU_BIN
for tool in "$QEMU_BIN" xorriso python3; do
  command -v "$tool" >/dev/null 2>&1 || die "missing required tool: $tool"
done

mkdir -p "$ARTIFACT_DIR"
readonly SERIAL_LOG="$ARTIFACT_DIR/serial.log"
readonly MONITOR_SOCK="$ARTIFACT_DIR/qemu-monitor.sock"
readonly SERIAL_SOCK="$ARTIFACT_DIR/qemu-serial.sock"
readonly QMP_SOCK="$ARTIFACT_DIR/qemu-qmp.sock"
readonly REPORT="$ARTIFACT_DIR/system-checks.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
EXTRACT_DIR="$(mktemp -d)"
readonly ARTIFACT_DIR EXTRACT_DIR
QEMU_PID=""

cleanup() {
  if [[ -n "$QEMU_PID" ]] && kill -0 "$QEMU_PID" 2>/dev/null; then
    kill "$QEMU_PID" 2>/dev/null || true
    wait "$QEMU_PID" 2>/dev/null || true
  fi
  # xorriso extracts ISO files and directories read-only.
  chmod -R u+w -- "$EXTRACT_DIR" 2>/dev/null || true
  rm -rf -- "$EXTRACT_DIR" "$MONITOR_SOCK" "$SERIAL_SOCK" || true
}
trap cleanup EXIT

# Send commands to the QEMU human monitor over one connection.
monitor() { # monitor <command>...; MON=<socket> for another QEMU
  python3 - "${MON:-$MONITOR_SOCK}" "$@" <<'PY'
import socket, sys, time
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
sock.connect(sys.argv[1])
time.sleep(0.5)
sock.recv(65536)
for command in sys.argv[2:]:
    sock.sendall((command + "\n").encode())
    time.sleep(0.15)
time.sleep(1.5)
sock.close()
PY
}

# Click with the absolute pointer (usb-tablet) through QMP. The human
# monitor's mouse_move sends relative motion, which goes to the PS/2 mouse.
qmp_click() { # qmp_click <x> <y> in screen pixels (1280x800)
  python3 - "$QMP_SOCK" "$(($1 * 32767 / 1280))" "$(($2 * 32767 / 800))" <<'PY'
import json, socket, sys, time
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
sock.connect(sys.argv[1])
stream = sock.makefile("rw")
stream.readline()  # greeting

def call(command, **arguments):
    stream.write(json.dumps({"execute": command, "arguments": arguments} if arguments else {"execute": command}) + "\n")
    stream.flush()
    while True:
        reply = json.loads(stream.readline())
        if "return" in reply or "error" in reply:
            if "error" in reply:
                print(f"qmp {command}: {reply['error']}", file=sys.stderr)
            return reply

call("qmp_capabilities")
x, y = int(sys.argv[2]), int(sys.argv[3])
call("input-send-event", events=[
    {"type": "abs", "data": {"axis": "x", "value": x}},
    {"type": "abs", "data": {"axis": "y", "value": y}},
])
time.sleep(0.3)
for down in (True, False):
    call("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": "left"}}])
    time.sleep(0.15)
sock.close()
PY
}

# Extract the live kernel and initrd so we can append a serial console
# without depending on the bootloader menu.
xorriso -osirrox on -indev "$ISO" -extract /live "$EXTRACT_DIR/live" >/dev/null 2>&1 \
  || die "could not extract /live from $ISO"
KERNEL="$(find "$EXTRACT_DIR/live" -maxdepth 1 -name 'vmlinuz*' | sort | head -n1)"
INITRD="$(find "$EXTRACT_DIR/live" -maxdepth 1 -name 'initrd.img*' | sort | head -n1)"
[[ -n "$KERNEL" && -n "$INITRD" ]] || die "kernel/initrd not found in ISO /live"
log "kernel=$(basename "$KERNEL") initrd=$(basename "$INITRD")"

ACCEL=(-accel tcg)
if [[ "$ARM64" == 1 ]]; then
  ACCEL=(-accel tcg -M virt -cpu cortex-a72)  # an arm64 guest on an amd64 runner: emulated
  log "arm64 guest: QEMU virt machine under TCG (slow)"
elif [[ -r /dev/kvm && -w /dev/kvm ]]; then
  ACCEL=(-accel kvm -cpu host)
  log "using KVM acceleration"
else
  log "KVM unavailable, using TCG (slow)"
fi
CONSOLE="console=tty0 console=ttyS0,115200"
[[ "$ARM64" == 1 ]] && CONSOLE="console=tty0 console=ttyAMA0,115200"
readonly CMDLINE="boot=live components hostname=dai-os username=dai locales=en_US.UTF-8,he_IL.UTF-8 keyboard-layouts=us,il timezone=Asia/Jerusalem $CONSOLE"
MEDIA=(-cdrom "$ISO" -vga std -usb -device usb-tablet)
NET=(-nic "user,model=virtio-net-pci")
if [[ "$ARM64" == 1 ]]; then
  MEDIA=(-device virtio-scsi-pci -drive "file=$ISO,if=none,id=cd0,media=cdrom,format=raw" -device "scsi-cd,drive=cd0"
    -device virtio-gpu-pci -device qemu-xhci -device usb-tablet)
  # No option ROM for the card: the kernel is loaded directly, and qemu-system-arm without recommends has no
  # iPXE ROMs (QEMU otherwise exits: failed to find romfile "efi-virtio.rom").
  NET=(-netdev "user,id=net0" -device "virtio-net-pci,netdev=net0,romfile=")
fi

: >"$SERIAL_LOG"
# An empty, sparse target disk so the installer sees somewhere to install.
truncate -s 24G "$EXTRACT_DIR/target-disk.raw"
LAUNCH_EPOCH="$(date +%s)"
"$QEMU_BIN" \
  "${ACCEL[@]}" \
  -m "$QEMU_MEM" -smp "$QEMU_SMP" \
  "${MEDIA[@]}" \
  -drive "file=$EXTRACT_DIR/target-disk.raw,format=raw,if=virtio" \
  -kernel "$KERNEL" -initrd "$INITRD" -append "$CMDLINE" \
  -display none \
  -chardev "socket,id=ser0,path=$SERIAL_SOCK,server=on,wait=off,logfile=$SERIAL_LOG" \
  -serial chardev:ser0 \
  -monitor "unix:$MONITOR_SOCK,server,nowait" \
  -qmp "unix:$QMP_SOCK,server,nowait" \
  "${NET[@]}" \
  -no-reboot &
QEMU_PID=$!

log "waiting up to ${BOOT_TIMEOUT}s for '$LOGIN_PATTERN'"
start=$SECONDS
while ((SECONDS - start < BOOT_TIMEOUT)); do
  kill -0 "$QEMU_PID" 2>/dev/null || die "QEMU exited early (see $SERIAL_LOG)"
  if grep -Eq "$PANIC_PATTERN" "$SERIAL_LOG"; then
    die "boot failure detected (see $SERIAL_LOG)"
  fi
  if grep -q "$LOGIN_PATTERN" "$SERIAL_LOG"; then
    LOGIN_EPOCH="$(date +%s)"
    log "login prompt reached after $((SECONDS - start))s"
    break
  fi
  sleep 1
done
grep -q "$LOGIN_PATTERN" "$SERIAL_LOG" || die "timed out after ${BOOT_TIMEOUT}s (see $SERIAL_LOG)"

if [[ -n "$MEASURE_JSON" ]]; then
  log "measuring: ${QEMU_MEM} MB, ${QEMU_SMP} CPU(s), accel=${ACCEL[1]}"
  measure_ok=1
  python3 "$SCRIPT_DIR/measure.py" "$SERIAL_SOCK" "$LAUNCH_EPOCH" "$LOGIN_EPOCH" "$MEASURE_JSON" \
    "$QEMU_MEM" "$QEMU_SMP" "${ACCEL[1]}" "${MEASURE_IDLE:-60}" || measure_ok=0
  [[ "$measure_ok" == 1 ]] || log "warning: the measurement did not complete (see the output above)"
  if [[ "$MEASURE_ONLY" == 1 ]]; then
    exit 0
  fi
fi

if grep -q 'FAILED' "$SERIAL_LOG"; then
  log "warning: some units failed to start:"
  grep 'FAILED' "$SERIAL_LOG" | sed 's/^/  /' >&2
fi

log "waiting ${DESKTOP_WAIT}s for the graphical session"
sleep "$DESKTOP_WAIT"

monitor "screendump $ARTIFACT_DIR/desktop.png -f png" || log "warning: screenshot failed"
[[ -s "$ARTIFACT_DIR/desktop.png" ]] && log "screenshot: $ARTIFACT_DIR/desktop.png"

log "running in-guest system checks over the serial console"
checks_ok=1
if [[ "$(basename "$ISO")" == dai-os-tv-* || "$PHONE" == 1 ]]; then
  # Kodi owns the screen on the TV edition (docs/TV.md §5), Phosh on the phone: no desktop demo apps over them.
  python3 "$SCRIPT_DIR/serial_check.py" "$SERIAL_SOCK" "$REPORT" || checks_ok=0
else
  python3 "$SCRIPT_DIR/serial_check.py" "$SERIAL_SOCK" "$REPORT" --launch-apps || checks_ok=0

  log "waiting ${APPS_WAIT}s for demo apps, then capturing a second screenshot"
  sleep "$APPS_WAIT"
  monitor "screendump $ARTIFACT_DIR/apps.png -f png" || log "warning: screenshot failed"
  [[ -s "$ARTIFACT_DIR/apps.png" ]] && log "screenshot: $ARTIFACT_DIR/apps.png"
fi

# The TV edition boots into Kodi, not the desktop: the desktop's interactive checks and screenshots below do
# not apply to it (docs/TV.md §5); its own checks ran in serial_check.py, and its screenshot is desktop.png.
if [[ "$(basename "$ISO")" == dai-os-tv-* || "$PHONE" == 1 ]]; then
  log "tv or phone edition: skipping the desktop's interactive checks"
else

# Interactive checks driven through the QEMU monitor (real keyboard/mouse).
# usb-tablet gives absolute coordinates: 0..32767 across the 1280x800 screen.
click() { # click <x> <y> in screen pixels
  qmp_click "$1" "$2" || log "warning: click failed"
}
type_keys() {
  local key commands=()
  for key in "$@"; do commands+=("sendkey $key"); done
  monitor "${commands[@]}"
}

log "interactive: type into the panel command field"
type_keys esc
click 300 768  # the command field: the Diamond Bar is 80% wide, centered (x 128-1152), y 744-792
sleep 1
type_keys a k u o
sleep 3
monitor "screendump $ARTIFACT_DIR/panel-field.png -f png" || log "warning: screenshot failed"

log "interactive: ask the local AI from D.Ai Command"
type_keys esc
type_keys meta_l-spc
sleep 2
type_keys shift-slash w h a t spc i s spc l i n u x shift-slash ret
sleep "${AI_WAIT:-45}"
monitor "screendump $ARTIFACT_DIR/ai-answer.png -f png" || log "warning: screenshot failed"

log "interactive: the diamond Start button opens the Start menu"
type_keys esc
click 161 768  # the diamond (docs/TASKBAR.md)
sleep 3
monitor "screendump $ARTIFACT_DIR/start-menu.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 1

log "interactive: ask D.Ai Forge from the command bar (+install antivirus → Forge window)"
type_keys meta_l-spc
sleep 2
type_keys shift-equal i n s t a l l spc a n t i v i r u s
sleep 2
monitor "screendump $ARTIFACT_DIR/forge-preview.png -f png" || log "warning: screenshot failed"
type_keys ret
sleep 8
monitor "screendump $ARTIFACT_DIR/forge-window.png -f png" || log "warning: screenshot failed"
type_keys esc esc
sleep 1

log "interactive: open the sandboxed example app from the command bar"
type_keys esc
type_keys meta_l-spc
sleep 2
type_keys t a s k s ret
sleep 8
monitor "screendump $ARTIFACT_DIR/forge-app.png -f png" || log "warning: screenshot failed"

log "interactive: open the installer (Calamares, D.Ai branding)"
type_keys esc
type_keys meta_l-spc
sleep 2
type_keys i n s t a l l spc d dot a i spc o s
sleep 2
type_keys ret
sleep 15
monitor "screendump $ARTIFACT_DIR/installer.png -f png" || log "warning: screenshot failed"

log "interactive: open D.Ai Welcome (first-run setup) from the command bar"
type_keys esc
sleep 2
type_keys meta_l-spc
sleep 2
type_keys w e l c o m e
sleep 2
type_keys ret
sleep 8
monitor "screendump $ARTIFACT_DIR/welcome.png -f png" || log "warning: screenshot failed"

log "interactive: D.Ai Quick (Super+N, next to the clock)"
type_keys esc
sleep 1
type_keys meta_l-n
sleep 4
monitor "screendump $ARTIFACT_DIR/quick.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 1

log "interactive: MOM, the task manager (Ctrl+Shift+Esc)"
type_keys ctrl-shift-esc
sleep 6
monitor "screendump $ARTIFACT_DIR/mom.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 1

log "interactive: clipboard history (Super+V, filled by the clip check)"
type_keys esc
sleep 2
type_keys meta_l-v
sleep 5
monitor "screendump $ARTIFACT_DIR/clip.png -f png" || log "warning: screenshot failed"
type_keys esc

# docs/I18N.md §11: the same windows in Arabic (right to left) and Russian, started from the command bar
# with "$ LANG=xx app" (the D.Ai apps read the language from LANG; the catalogs are on the image).
log "interactive: D.Ai Welcome in Arabic"
sleep 2
type_keys meta_l-spc
sleep 2
type_keys shift-4 spc shift-l shift-a shift-n shift-g equal a r spc d a i minus w e l c o m e ret
sleep 8
monitor "screendump $ARTIFACT_DIR/welcome-ar.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 2

log "interactive: MOM in Russian"
type_keys meta_l-spc
sleep 2
type_keys shift-4 spc shift-l shift-a shift-n shift-g equal r u spc d a i minus m o m ret
sleep 6
monitor "screendump $ARTIFACT_DIR/mom-ru.png -f png" || log "warning: screenshot failed"
type_keys esc

# More of D.Ai, for the screenshots branch (docs/BASICS.md): mail, Find, Doctor, Heal, the on-screen keyboard
# and the magnifier. Each one is closed again before the next.
command_bar() { # command_bar <keys>...: open D.Ai Command, type, wait for the answer
  type_keys meta_l-spc
  sleep 2
  type_keys "$@"
  sleep 4
}
log "interactive: J, the mail client"
sleep 1
command_bar shift-4 spc d a i minus j ret
sleep 6
monitor "screendump $ARTIFACT_DIR/j.png -f png" || log "warning: screenshot failed"
type_keys alt-f4
sleep 2
log "interactive: D.Ai Find in the command bar"
command_bar f i n d spc p h o t o s spc f r o m spc t o d a y
monitor "screendump $ARTIFACT_DIR/find.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 1
log "interactive: D.Ai Doctor in the command bar"
command_bar w h y spc i s spc m y spc c o m p u t e r spc s l o w shift-slash
sleep 4
monitor "screendump $ARTIFACT_DIR/doctor.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 1
log "interactive: D.Ai Heal (Super+F1)"
type_keys meta_l-f1
sleep 6
monitor "screendump $ARTIFACT_DIR/heal.png -f png" || log "warning: screenshot failed"
type_keys esc
sleep 2
log "interactive: D.Ai PDF with the checks' test file (the file's wants in the bar)"
command_bar shift-4 spc d a i minus p d f spc slash t m p slash w a n t s dot p d f ret
sleep 8
monitor "screendump $ARTIFACT_DIR/pdf.png -f png" || log "warning: screenshot failed"
type_keys alt-f4
sleep 2
log "interactive: D.Ai VM (no machine yet: the first-machine page)"
command_bar shift-4 spc d a i minus v m ret
sleep 8
monitor "screendump $ARTIFACT_DIR/vm.png -f png" || log "warning: screenshot failed"
type_keys alt-f4
sleep 2
log "interactive: the on-screen keyboard (Super+Alt+K)"
type_keys meta_l-alt-k
sleep 4
monitor "screendump $ARTIFACT_DIR/keyboard.png -f png" || log "warning: screenshot failed"
type_keys meta_l-alt-k
sleep 2
log "interactive: the magnifier (Super+=)"
type_keys meta_l-equal meta_l-equal
sleep 2
monitor "screendump $ARTIFACT_DIR/magnifier.png -f png" || log "warning: screenshot failed"
type_keys meta_l-minus meta_l-minus
sleep 1

# The login screen of an installed system (docs/V2.md D2): the live session logs in by itself, so the greeter
# is shown in its test mode, with the D.Ai theme, as a window of this session.
log "interactive: the D.Ai login screen (SDDM greeter, test mode)"
command_bar shift-4 spc s d d m minus g r e e t e r minus q t 6 spc minus minus t e s t minus m o d e spc \
  minus minus t h e m e spc slash u s r slash s h a r e slash s d d m slash t h e m e s slash d a i ret
sleep 6
monitor "screendump $ARTIFACT_DIR/login.png -f png" || log "warning: screenshot failed"
type_keys alt-f4
sleep 2

fi  # not the TV edition

if ((checks_ok == 0)); then
  log "last serial console lines:"
  tail -n 60 "$SERIAL_LOG" | sed 's/^/  | /' >&2
  die "system checks failed (see $REPORT)"
fi

# The boot menu with the languages (docs/I18N.md §9): the checks above boot the kernel directly, so boot the
# ISO once more through its own menu, open "Language" and take its picture. Only pictures: never a failure.
log "screenshots: the boot menu and its Language submenu"
kill "$QEMU_PID" 2>/dev/null || true
wait "$QEMU_PID" 2>/dev/null || true
MENU_SOCK="$ARTIFACT_DIR/qemu-menu.sock"
qemu-system-x86_64 "${ACCEL[@]}" -m 2048 -cdrom "$ISO" -boot d -vga std -display none \
  -monitor "unix:$MENU_SOCK,server,nowait" -no-reboot &
QEMU_PID=$!
sleep 8
MON="$MENU_SOCK" monitor "sendkey down" "sendkey up" || true  # stop the countdown
sleep 1
MON="$MENU_SOCK" monitor "screendump $ARTIFACT_DIR/boot-menu.png -f png" || log "warning: screenshot failed"
MON="$MENU_SOCK" monitor "sendkey down" "sendkey ret" || true
sleep 2
MON="$MENU_SOCK" monitor "screendump $ARTIFACT_DIR/boot-languages.png -f png" || log "warning: screenshot failed"
# Start the first language (English) from the submenu: its command line has "splash", so the D.Ai loading
# screen (Plymouth) shows while the live system starts. A few pictures, since its timing varies.
MON="$MENU_SOCK" monitor "sendkey ret" || true
for shot in 1 2 3; do
  sleep 6
  MON="$MENU_SOCK" monitor "screendump $ARTIFACT_DIR/boot-splash-$shot.png -f png" || log "warning: screenshot failed"
done
kill "$QEMU_PID" 2>/dev/null || true
wait "$QEMU_PID" 2>/dev/null || true
rm -f -- "$MENU_SOCK"

log "PASS"
