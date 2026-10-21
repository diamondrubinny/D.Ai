#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build a D.Ai OS live ISO with Debian live-build.
#
# Usage: build-iso.sh <user|dev|edu|tv|server|phone> [output-dir]
#
# Must run as root inside a disposable Debian trixie container or VM,
# because live-build creates chroots and mounts /proc, /sys and /dev.
#
# Environment:
#   DAI_VERSION        Version string embedded in the ISO name (default: 0.1.0-alpha)
#   DAI_ARCH           amd64 (default) or arm64 (built on an amd64 host through QEMU user emulation;
#                      the phone edition is arm64 whatever this says)
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
readonly ARCHIVE_AREAS="main non-free-firmware"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"

log() { printf '[build-iso] %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

case "$EDITION" in
  user | dev | edu | tv | server) ;;
  phone) ;;
  *) die "usage: $(basename "$0") <user|dev|edu|tv|server|phone> [output-dir]" ;;
esac
# arm64 (the phone edition, docs/MOBILE.md C1; the tv edition for ARM boxes, docs/TV.md §14) is built on an
# amd64 host through QEMU user emulation.
ARCH="${DAI_ARCH:-amd64}"
[[ "$EDITION" == phone ]] && ARCH=arm64
readonly ARCH
case "$ARCH" in
  amd64 | arm64) ;;
  *) die "DAI_ARCH must be amd64 or arm64, not $ARCH" ;;
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
    isolinux syslinux-common grub-efi-amd64-bin grub-pc-bin python3
  if [[ "$ARCH" == arm64 ]]; then
    # The arm64 chroot runs through qemu-aarch64-static (binfmt_misc on the host must know it: the runner
    # installs qemu-user-static, which registers the handler with the fix-binary flag). GRUB for arm64 is an
    # arm64-only package: live-build installs it inside the chroot for the binary stage, not on this host.
    # mmdebstrap makes the chroot (see bootstrap_foreign); arch-test is how it confirms the emulation works.
    apt-get install -y --no-install-recommends qemu-user-static binfmt-support mmdebstrap arch-test
  fi
}

# live-build's own bootstrap stage runs debootstrap's second stage inside the chroot, so debootstrap's Perl
# parsing of the package index runs under QEMU emulation too: 53 of the 58 minutes that stage took in CI
# (dpkg's real work was 5). mmdebstrap resolves and downloads with the host's apt and only runs dpkg under
# emulation. The result goes to cache/bootstrap, which live-build restores (lb bootstrap_cache) and then
# skips its own bootstrap stage, --bootstrap-qemu-* of lb config included.
bootstrap_foreign() {
  local mirror="${DEBIAN_MIRROR:-http://deb.debian.org/debian}" root=cache/bootstrap
  log "bootstrapping $ARCH with mmdebstrap (apt on the host, dpkg under emulation)"
  rm -rf -- "$root"
  mkdir -p cache
  # --variant=debootstrap is debootstrap's default package set (required + important).
  mmdebstrap --mode=root --format=directory --architectures="$ARCH" --variant=debootstrap \
    --components="${ARCHIVE_AREAS// /,}" trixie "$root" "$mirror"
  # The marks live-build's bootstrap stage leaves in /etc/os-release of a live image (bootstrap_debootstrap).
  chroot "$root" dpkg-divert --quiet --local --add --no-rename --divert /etc/os-release.debootstrap /etc/os-release
  rm -f -- "$root/etc/os-release"
  cp -- "$root/usr/lib/os-release" "$root/etc/os-release"
  printf 'IMAGE_ID=live\nBUILD_ID=%s\n' "$(date --utc -d "@$SOURCE_DATE_EPOCH" +%Y%m%dT%H%M%SZ)" >>"$root/etc/os-release"
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

  local arch_args=(--architectures "$ARCH" --linux-flavours "$ARCH" --uefi-secure-boot enable)
  if [[ "$ARCH" == arm64 ]]; then
    # No syslinux on arm64 (GRUB EFI only); the chroot's binaries run through qemu-aarch64-static (the
    # bootstrap itself comes from mmdebstrap, see bootstrap_foreign; these options are the fallback when
    # cache/bootstrap is missing); Secure Boot on arm64 phones is a per-device matter (docs/MOBILE.md C1), so
    # the shim is left out here.
    # mksquashfs runs inside the chroot (live-build's default), i.e. under emulation too: with xz it took 72
    # minutes in CI for this image; zstd compresses several times faster for a somewhat larger file.
    arch_args=(--architectures arm64 --linux-flavours arm64 --bootloaders grub-efi
      --bootstrap-qemu-arch arm64 --bootstrap-qemu-static /usr/bin/qemu-aarch64-static --uefi-secure-boot disable
      --chroot-squashfs-compression-type zstd)
  fi
  lb config \
    --mode debian \
    --distribution trixie \
    "${arch_args[@]}" \
    --archive-areas "$ARCHIVE_AREAS" \
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
    --bootappend-live "boot=live components quiet splash hostname=dai-os username=dai locales=en_US.UTF-8,he_IL.UTF-8 keyboard-layouts=us,il keyboard-options=grp:alt_shift_toggle timezone=Asia/Jerusalem" \
    "${mirror_args[@]}"

  # Layer the shared config first, then the edition-specific overrides.
  cp -a "$LB_SRC/common/." config/
  # The server edition has no desktop: remove what the shared layer adds for it (docs/SERVER.md §2).
  if [[ "$EDITION" == server ]]; then
    python3 -I "$REPO_ROOT/build/scripts/server-prune.py" config
  fi
  cp -a "$LB_SRC/editions/$EDITION/." config/
  chmod 0755 config/hooks/normal/*.hook.chroot config/hooks/normal/*.hook.binary
  if [[ "$ARCH" == arm64 ]]; then
    # The shared lists name the amd64 kernel and the x86 microcode; the rest is architecture-neutral.
    sed -i -e 's/^linux-image-amd64$/linux-image-arm64/' -e '/^\(intel\|amd64\)-microcode$/d' config/package-lists/*.chroot
  fi
  # Qt draws SVG files (the D.Ai diamond on Start, in D.Ai Command and Forge)
  # through its SVG plugins. Newer Debian Qt packages ship them separately
  # from libqt6svg6; recommends are not installed, so add them explicitly.
  # *.list.optional: packages that are welcome but must not break the build if
  # Debian dropped them (e.g. some education apps); only available ones are kept.
  local optional name kept missing
  local skipped_optional=()
  for optional in config/package-lists/*.list.optional; do
    [[ -e "$optional" ]] || continue
    kept=() missing=()
    while read -r name; do
      [[ -z "$name" || "$name" == \#* ]] && continue
      if apt-cache show "$name" >/dev/null 2>&1; then kept+=("$name"); else missing+=("$name"); fi
    done <"$optional"
    printf '%s\n' "# from $(basename "$optional") (filtered by build-iso.sh)" "${kept[@]}" >"${optional%.optional}.chroot"
    ((${#missing[@]} == 0)) || log "not in this Debian release, skipped: ${missing[*]}"
    skipped_optional+=("${missing[@]}")
    rm -f -- "$optional"
  done
  # Build facts inside the image (/usr/share/dai/build-info), printed by the boot test:
  # what this Debian release offered when the image was built (docs/SNAPSHOTS.md).
  local info=config/includes.chroot_after_packages/usr/share/dai/build-info grub_btrfs=no
  if apt-cache show grub-btrfs >/dev/null 2>&1; then grub_btrfs=yes; fi
  mkdir -p "$(dirname "$info")"
  printf '%s\n' "edition=$EDITION" "version=$VERSION" "grub-btrfs-available=$grub_btrfs" \
    "optional-skipped=${skipped_optional[*]:-none}" >"$info"
  log "build facts: $(tr '\n' ' ' <"$info")"
  if apt-cache show qt6-svg-plugins >/dev/null 2>&1; then
    printf '%s\n' '# Qt SVG image/icon plugins (added by build-iso.sh)' qt6-svg-plugins >config/package-lists/dai-qt-svg.list.chroot
  fi
  stage_apps config/includes.chroot_after_packages
}

# D.Ai's own applications are installed as .deb packages (docs/RELEASE.md), so
# dpkg knows which files belong to D.Ai and they can be updated or removed.
stage_apps() {
  local root="$1" debs="config/packages.chroot" deb name
  install -d "$debs"
  DAI_VERSION="$VERSION" bash "$SCRIPT_DIR/build-debs.sh" "$OUT_DIR/debs"
  # Only packages for this architecture (D.Ai's apps are "all"; the runtimes and the panel plugin are amd64).
  for deb in "$OUT_DIR"/debs/dai-*.deb; do
    case "$(basename "$deb")" in
      *_all.deb | *_"$ARCH".deb) cp -- "$deb" "$debs/" ;;
      *) log "not for $ARCH, left out: $(basename "$deb")" ;;
    esac
  done
  # Listing them makes the build fail loudly if one cannot be installed.
  {
    echo '# D.Ai packages built by build-debs.sh (added by build-iso.sh)'
    for deb in "$debs"/dai-*.deb; do
      name="$(basename "$deb")"
      echo "${name%%_*}"
    done
  } >config/package-lists/dai-packages.list.chroot

  # Without the panel plugin, fall back to the button that opens D.Ai Command.
  if ! compgen -G "$debs/dai-panel-plugin_*.deb" >/dev/null; then
    log "warning: no panel plugin; using the command button instead of the panel field"
    sed -i 's/^plugins=fancymenu,daicommand,/plugins=fancymenu,command,/' "$root/etc/xdg/lxqt/panel.conf"
  fi
  compgen -G "$debs/dai-llama-runtime_*.deb" >/dev/null \
    || log "warning: DAI_LLAMA_DIST not set; the image will not include the local AI runtime"
  compgen -G "$debs/dai-whisper-runtime_*.deb" >/dev/null \
    || log "warning: DAI_WHISPER_DIST not set; the image will not include speech recognition"
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
  [[ "$ARCH" == "$(dpkg --print-architecture)" ]] || bootstrap_foreign
  lb build 2>&1 | tee build.log

  local iso="$WORK_DIR/dai-os-$EDITION-$ARCH.hybrid.iso"
  [[ -f "$iso" ]] || iso="$WORK_DIR/dai-os-$EDITION-$ARCH.iso"
  [[ -f "$iso" ]] || die "live-build finished without producing $iso (see $WORK_DIR/build.log)"

  local name="dai-os-$EDITION-$VERSION-$ARCH"
  mv -- "$iso" "$OUT_DIR/$name.iso"
  if [[ -f "dai-os-$EDITION-$ARCH.packages" ]]; then
    cp -- "dai-os-$EDITION-$ARCH.packages" "$OUT_DIR/$name.packages"
  fi
  (cd "$OUT_DIR" && sha256sum "$name.iso" >"$name.iso.sha256")

  log "done: $OUT_DIR/$name.iso ($(du -h "$OUT_DIR/$name.iso" | cut -f1))"
}

main
