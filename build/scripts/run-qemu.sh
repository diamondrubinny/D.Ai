#!/usr/bin/env bash
# Boot a D.Ai OS ISO interactively in QEMU for manual testing.
#
# Usage: run-qemu.sh <path-to-iso> [--uefi]
#
# --uefi boots with OVMF firmware (Debian/Ubuntu package: ovmf).
set -euo pipefail

readonly ISO="${1:-}"
readonly MODE="${2:-}"

[[ -f "$ISO" ]] || { echo "usage: $(basename "$0") <iso> [--uefi]" >&2; exit 2; }

# shellcheck disable=SC2054 # commas are QEMU option syntax
args=(-m 4096 -smp 2 -cdrom "$ISO" -boot d -vga virtio -display gtk
  -nic user,model=virtio-net-pci -audiodev pa,id=snd -device intel-hda -device hda-duplex,audiodev=snd)

if [[ -r /dev/kvm && -w /dev/kvm ]]; then
  args=(-accel kvm -cpu host "${args[@]}")
fi

if [[ "$MODE" == "--uefi" ]]; then
  readonly OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
  readonly OVMF_VARS_TEMPLATE=/usr/share/OVMF/OVMF_VARS_4M.fd
  [[ -f "$OVMF_CODE" && -f "$OVMF_VARS_TEMPLATE" ]] || { echo "OVMF not found; install the 'ovmf' package" >&2; exit 1; }
  vars="$(mktemp --suffix=.fd)"
  trap 'rm -f -- "$vars"' EXIT
  cp -- "$OVMF_VARS_TEMPLATE" "$vars"
  args+=(-drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" -drive "if=pflash,format=raw,file=$vars")
fi

exec qemu-system-x86_64 "${args[@]}"
