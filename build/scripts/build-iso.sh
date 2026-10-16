#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build a D.Ai OS live ISO with Debian live-build.
#
# Usage: build-iso.sh <user|dev> [output-dir]
#
# Must run as root inside a disposable Debian trixie container or VM,
# because live-build creates chroots and mounts /proc, /sys and /dev.
#
# Environment:
#   DAI_VERSION        Version string embedded in the ISO name (default: 0.1.0-alpha)
#   SOURCE_DATE_EPOCH  Fixed timestamp for reproducible output (default: now)
#   WORK_DIR           live-build working directory (default: <repo>/.work/<edition>)
#   DEBIAN_MIRROR      Optional Debian mirror URL override
#   DAI_LLAMA_DIST     Directory produced by build-llama.sh (local AI runtime)
#   DAI_PANEL_PLUGIN   Directory produced by build-panel-plugin.sh (panel command field)
set -euo pipefail

readonly EDITION="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
readonly LB_SRC="$REPO_ROOT/build/live-build"
OUT_DIR="$(realpath -m "${2:-$REPO_ROOT/out}")"
WORK_DIR="$(realpath -m "${WORK_DIR:-$REPO_ROOT/.work/$EDITION}")"
readonly SCRIPT_DIR REPO_ROOT OUT_DIR WORK_DIR
readonly VERSION="${DAI_VERSION:-0.1.0-alpha}"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"

log() { printf '[build-iso] %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

case "$EDITION" in
  user | dev) ;;
  *) die "usage: $(basename "$0") <user|dev> [output-dir]" ;;
esac

[[ $EUID -eq 0 ]] || die "must run as root inside a disposable container or VM"
# live-build from other distributions (e.g. Ubuntu) is too old for this config.
# shellcheck disable=SC2016 # expanded by the inner shell
host_os="$(env -i sh -c '. /etc/os-release && echo "${ID:-}:${VERSION_CODENAME:-}"')"
[[ "$host_os" == "debian:trixie" ]] \
  || die "build host must be Debian trixie (use: docker run --privileged debian:trixie ...)"
[[ "$VERSION" =~ ^[0-9A-Za-z.+~-]+$ ]] || die "invalid DAI_VERSION: $VERSION"
[[ -d "$LB_SRC/common" && -d "$LB_SRC/editions/$EDITION" ]] || die "live-build config not found under $LB_SRC"

# Refuse to wipe anything that is not a dedicated work directory.
case "$WORK_DIR" in
  / | "$REPO_ROOT" | "$HOME" | "") die "refusing to use WORK_DIR=$WORK_DIR" ;;
esac

install_build_deps() {
  if command -v lb >/dev/null 2>&1; then
    return
  fi
  log "installing live-build and image tooling"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    live-build debootstrap ca-certificates \
    xorriso squashfs-tools mtools dosfstools cpio \
    isolinux syslinux-common grub-efi-amd64-bin grub-pc-bin
}

configure() {
  local mirror_args=()
  if [[ -n "${DEBIAN_MIRROR:-}" ]]; then
    mirror_args=(
      --mirror-bootstrap "$DEBIAN_MIRROR"
      --mirror-chroot "$DEBIAN_MIRROR"
      --mirror-binary "$DEBIAN_MIRROR"
    )
  fi

  local volume="DAI_OS_${EDITION^^}"

  lb config \
    --mode debian \
    --distribution trixie \
    --architectures amd64 \
    --linux-flavours amd64 \
    --archive-areas "main non-free-firmware" \
    --apt-recommends false \
    --security true \
    --updates true \
    --debian-installer none \
    --firmware-chroot false \
    --firmware-binary false \
    --memtest none \
    --image-name "dai-os-$EDITION" \
    --iso-application "D.Ai OS" \
    --iso-publisher "Diamond Rubinny (d.Ai)" \
    --iso-volume "$volume" \
    --bootappend-live "boot=live components quiet hostname=dai-os username=dai locales=en_US.UTF-8,he_IL.UTF-8 keyboard-layouts=us,il keyboard-options=grp:alt_shift_toggle timezone=Asia/Jerusalem" \
    "${mirror_args[@]}"

  # Layer the shared config first, then the edition-specific overrides.
  cp -a "$LB_SRC/common/." config/
  cp -a "$LB_SRC/editions/$EDITION/." config/
  chmod 0755 config/hooks/normal/*.hook.chroot
  stage_apps config/includes.chroot_after_packages
}

# Copy D.Ai's own applications from apps/ into the image tree.
stage_apps() {
  local root="$1"
  local cmd="$REPO_ROOT/apps/dai-command"
  install -d "$root/usr/lib/dai" "$root/usr/bin" "$root/usr/share/applications"
  cp -r "$cmd/dai_command" "$root/usr/lib/dai/"
  find "$root/usr/lib/dai" -name '__pycache__' -prune -exec rm -rf {} +
  install -m 0755 "$cmd/data/dai-command" "$root/usr/bin/dai-command"
  install -m 0755 "$cmd/data/dai-fixlayout" "$root/usr/bin/dai-fixlayout"
  install -m 0755 "$cmd/data/dai-lang" "$root/usr/bin/dai-lang"
  install -m 0644 "$cmd/data/dai-command.desktop" "$root/usr/share/applications/dai-command.desktop"

  local tune="$REPO_ROOT/apps/dai-tune"
  install -d "$root/usr/share/polkit-1/actions"
  cp -r "$tune/dai_tune" "$root/usr/lib/dai/"
  find "$root/usr/lib/dai" -name '__pycache__' -prune -exec rm -rf {} +
  install -m 0755 "$tune/data/dai-tune" "$root/usr/bin/dai-tune"
  install -m 0755 "$tune/data/dai-tune-helper" "$root/usr/lib/dai/dai-tune-helper"
  install -m 0644 "$tune/data/io.github.diamondrubinny.dai.tune.policy" \
    "$root/usr/share/polkit-1/actions/io.github.diamondrubinny.dai.tune.policy"

  local ai="$REPO_ROOT/apps/dai-ai"
  cp -r "$ai/dai_ai" "$root/usr/lib/dai/"
  find "$root/usr/lib/dai" -name '__pycache__' -prune -exec rm -rf {} +
  local bin
  for bin in daid dai-ai dai-models; do
    install -m 0755 "$ai/data/$bin" "$root/usr/bin/$bin"
  done
  install -d "$root/usr/share/dai" "$root/usr/lib/systemd/user" "$root/etc/systemd/user/sockets.target.wants"
  install -m 0644 "$ai/data/models.json" "$root/usr/share/dai/models.json"
  install -m 0644 "$ai/data/dai-daid.socket" "$ai/data/dai-daid.service" "$root/usr/lib/systemd/user/"
  # Same as "systemctl --global enable dai-daid.socket".
  ln -sf /usr/lib/systemd/user/dai-daid.socket "$root/etc/systemd/user/sockets.target.wants/dai-daid.socket"

  # D.Ai Forge: recipes, the app builder and its sandbox runner.
  local forge="$REPO_ROOT/apps/dai-forge"
  cp -r "$forge/dai_forge" "$root/usr/lib/dai/"
  find "$root/usr/lib/dai" -name '__pycache__' -prune -exec rm -rf {} +
  install -m 0755 "$forge/data/dai-forge" "$root/usr/bin/dai-forge"
  install -d "$root/usr/share/dai/forge/recipes" "$root/usr/share/dai/forge/examples" "$root/etc/dai/forge/recipes"
  install -m 0644 "$forge"/data/recipes/*.json "$root/usr/share/dai/forge/recipes/"
  install -m 0644 "$forge"/examples/* "$root/usr/share/dai/forge/examples/"
  install -m 0644 "$forge/data/forge.json" "$root/etc/dai/forge.json"

  # Command field in the panel (build-panel-plugin.sh). Without it, fall back
  # to the button that opens D.Ai Command.
  if [[ -n "${DAI_PANEL_PLUGIN:-}" && -f "$DAI_PANEL_PLUGIN/libdaicommand.so" ]]; then
    install -d "$root/usr/lib/x86_64-linux-gnu/lxqt-panel" "$root/usr/share/lxqt/lxqt-panel"
    install -m 0644 "$DAI_PANEL_PLUGIN/libdaicommand.so" "$root/usr/lib/x86_64-linux-gnu/lxqt-panel/libdaicommand.so"
    install -m 0644 "$DAI_PANEL_PLUGIN/daicommand.desktop" "$root/usr/share/lxqt/lxqt-panel/daicommand.desktop"
  else
    log "warning: DAI_PANEL_PLUGIN not set; using the command button instead of the panel field"
    sed -i 's/^plugins=fancymenu,daicommand,/plugins=fancymenu,command,/' "$root/etc/xdg/lxqt/panel.conf"
  fi

  # llama.cpp runtime, built separately by build-llama.sh (optional for local builds).
  if [[ -n "${DAI_LLAMA_DIST:-}" ]]; then
    [[ -x "$DAI_LLAMA_DIST/llama-server" ]] || die "DAI_LLAMA_DIST has no llama-server: $DAI_LLAMA_DIST"
    install -d "$root/opt/dai/llama"
    cp -a "$DAI_LLAMA_DIST/." "$root/opt/dai/llama/"
  else
    log "warning: DAI_LLAMA_DIST not set; the image will not include the local AI runtime"
  fi
}

main() {
  install_build_deps

  log "edition=$EDITION version=$VERSION work=$WORK_DIR out=$OUT_DIR"
  if [[ -d "$WORK_DIR" ]]; then
    (cd "$WORK_DIR" && lb clean --purge >/dev/null 2>&1) || true
    rm -rf -- "$WORK_DIR"
  fi
  mkdir -p "$WORK_DIR" "$OUT_DIR"
  cd "$WORK_DIR"

  configure
  lb build 2>&1 | tee build.log

  local iso="$WORK_DIR/dai-os-$EDITION-amd64.hybrid.iso"
  [[ -f "$iso" ]] || die "live-build finished without producing $iso (see $WORK_DIR/build.log)"

  local name="dai-os-$EDITION-$VERSION-amd64"
  mv -- "$iso" "$OUT_DIR/$name.iso"
  if [[ -f "dai-os-$EDITION-amd64.packages" ]]; then
    cp -- "dai-os-$EDITION-amd64.packages" "$OUT_DIR/$name.packages"
  fi
  (cd "$OUT_DIR" && sha256sum "$name.iso" >"$name.iso.sha256")

  log "done: $OUT_DIR/$name.iso ($(du -h "$OUT_DIR/$name.iso" | cut -f1))"
}

main
