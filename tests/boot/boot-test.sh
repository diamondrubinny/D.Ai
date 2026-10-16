#!/usr/bin/env bash
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
set -euo pipefail

readonly ISO="${1:-}"
ARTIFACT_DIR="$(realpath -m "${2:-boot-artifacts}")"
readonly BOOT_TIMEOUT="${BOOT_TIMEOUT:-600}"
readonly DESKTOP_WAIT="${DESKTOP_WAIT:-60}"
readonly LOGIN_PATTERN='dai-os login:'
readonly PANIC_PATTERN='Kernel panic|end Kernel panic|Unable to find a medium containing a live file system'

log() { printf '[boot-test] %s\n' "$*" >&2; }
die() { log "FAIL: $*"; exit 1; }

[[ -f "$ISO" ]] || die "usage: $(basename "$0") <iso> [artifact-dir]"
for tool in qemu-system-x86_64 xorriso python3; do
  command -v "$tool" >/dev/null 2>&1 || die "missing required tool: $tool"
done

mkdir -p "$ARTIFACT_DIR"
readonly SERIAL_LOG="$ARTIFACT_DIR/serial.log"
readonly MONITOR_SOCK="$ARTIFACT_DIR/qemu-monitor.sock"
readonly SERIAL_SOCK="$ARTIFACT_DIR/qemu-serial.sock"
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

# Send one command to the QEMU human monitor.
monitor() {
  python3 - "$MONITOR_SOCK" "$1" <<'PY'
import socket, sys, time
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.settimeout(10)
sock.connect(sys.argv[1])
time.sleep(0.5)
sock.recv(65536)
sock.sendall((sys.argv[2] + "\n").encode())
time.sleep(2)
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
if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  ACCEL=(-accel kvm -cpu host)
  log "using KVM acceleration"
else
  log "KVM unavailable, using TCG (slow)"
fi

readonly CMDLINE="boot=live components hostname=dai-os username=dai locales=en_US.UTF-8,he_IL.UTF-8 keyboard-layouts=us,il timezone=Asia/Jerusalem console=tty0 console=ttyS0,115200"

: >"$SERIAL_LOG"
qemu-system-x86_64 \
  "${ACCEL[@]}" \
  -m 4096 -smp 2 \
  -cdrom "$ISO" \
  -kernel "$KERNEL" -initrd "$INITRD" -append "$CMDLINE" \
  -vga std -display none \
  -chardev "socket,id=ser0,path=$SERIAL_SOCK,server=on,wait=off,logfile=$SERIAL_LOG" \
  -serial chardev:ser0 \
  -monitor "unix:$MONITOR_SOCK,server,nowait" \
  -nic user,model=virtio-net-pci \
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
    log "login prompt reached after $((SECONDS - start))s"
    break
  fi
  sleep 5
done
grep -q "$LOGIN_PATTERN" "$SERIAL_LOG" || die "timed out after ${BOOT_TIMEOUT}s (see $SERIAL_LOG)"

if grep -q 'FAILED' "$SERIAL_LOG"; then
  log "warning: some units failed to start:"
  grep 'FAILED' "$SERIAL_LOG" | sed 's/^/  /' >&2
fi

log "waiting ${DESKTOP_WAIT}s for the graphical session"
sleep "$DESKTOP_WAIT"

monitor "screendump $ARTIFACT_DIR/desktop.png -f png" || log "warning: screenshot failed"
[[ -s "$ARTIFACT_DIR/desktop.png" ]] && log "screenshot: $ARTIFACT_DIR/desktop.png"

log "running in-guest system checks over the serial console"
python3 "$SCRIPT_DIR/serial_check.py" "$SERIAL_SOCK" "$REPORT" || die "system checks failed (see $REPORT)"

log "PASS"
