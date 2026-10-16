#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build D.Ai OS's own .deb packages (docs/RELEASE.md).
#
# Usage: build-debs.sh <out-dir>
#
# Environment:
#   DAI_VERSION        e.g. 0.1.0-alpha+abc1234 (default: 0.1.0-alpha)
#   DAI_LLAMA_DIST     llama.cpp runtime (build-llama.sh) → dai-llama-runtime
#   DAI_WHISPER_DIST   whisper.cpp runtime (build-whisper.sh) → dai-whisper-runtime
#   DAI_PANEL_PLUGIN   lxqt-panel plugin (build-panel-plugin.sh) → dai-panel-plugin
#   DAI_APT_URL        update source base (".../releases/latest/"; apt then reads "download/InRelease")
#   DAI_KEYRING        public archive key (default: build/keys/dai-archive-keyring.asc)
#   DAI_MAINTAINER     Maintainer field
#   SOURCE_DATE_EPOCH  file timestamps (reproducible builds)
set -euo pipefail
umask 022

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUT_DIR="$(realpath -m "${1:-$REPO_ROOT/out/debs}")"
readonly SCRIPT_DIR REPO_ROOT OUT_DIR
readonly KEYRING="${DAI_KEYRING:-$REPO_ROOT/build/keys/dai-archive-keyring.asc}"
readonly APT_URL="${DAI_APT_URL:-https://github.com/diamondrubinny/D.Ai/releases/latest/}"
readonly MAINTAINER="${DAI_MAINTAINER:-Diamond Rubinny (d.Ai) <179243804+diamondrubinny@users.noreply.github.com>}"

log() { printf '[build-debs] %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

# Debian version: a pre-release suffix sorts before the release (0.1.0~alpha < 0.1.0).
deb_version() {
  local version="${DAI_VERSION:-0.1.0-alpha}"
  version="${version#v}"
  version="${version//-/\~}"
  [[ "$version" =~ ^[0-9][A-Za-z0-9.+~]*$ ]] || die "invalid version: ${DAI_VERSION:-}"
  printf '%s' "$version"
}
VERSION="$(deb_version)"
readonly VERSION
WORK="$(mktemp -d)"
readonly WORK
trap 'rm -rf -- "$WORK"' EXIT

copy_package() { # copy_package <python-package-dir> <root>
  install -d "$2/usr/lib/dai"
  cp -r "$1" "$2/usr/lib/dai/"
  find "$2/usr/lib/dai" -name '__pycache__' -prune -exec rm -rf {} +
}

# Write DEBIAN/control (+ conffiles) and build the package.
finish() { # finish <root> <name> <arch> <depends> <description> [recommends]
  local root="$1" name="$2" arch="$3" depends="$4" description="$5" recommends="${6:-}"
  install -d "$root/DEBIAN"
  {
    printf 'Package: %s\nVersion: %s\nArchitecture: %s\n' "$name" "$VERSION" "$arch"
    printf 'Maintainer: %s\n' "$MAINTAINER"
    printf 'Installed-Size: %s\n' "$(du -sk --exclude=DEBIAN "$root" | cut -f1)"
    printf 'Depends: %s\n' "$depends"
    [[ -n "$recommends" ]] && printf 'Recommends: %s\n' "$recommends"
    printf 'Section: misc\nPriority: optional\n'
    printf 'Homepage: https://github.com/diamondrubinny/D.Ai\n'
    printf 'Description: %s\n D.Ai OS by Diamond Rubinny (d.Ai). Apache-2.0.\n' "$description"
  } >"$root/DEBIAN/control"
  if [[ -d "$root/etc" ]]; then
    (cd "$root" && find etc -type f | sort | sed 's|^|/|') >"$root/DEBIAN/conffiles"
  fi
  find "$root" -path "$root/DEBIAN" -prune -o -type d -exec chmod 0755 {} +
  if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
    find "$root" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +
  fi
  local deb="$OUT_DIR/${name}_${VERSION}_${arch}.deb"
  dpkg-deb --root-owner-group -Zxz --build "$root" "$deb" >/dev/null
  log "built $(basename "$deb") ($(du -h "$deb" | cut -f1))"
}

build_apps() {
  local root="$WORK/dai-apps" bin
  install -d "$root/usr/bin" "$root/usr/share/applications" "$root/usr/share/dai" \
    "$root/usr/share/polkit-1/actions" "$root/usr/lib/systemd/user"

  local cmd="$REPO_ROOT/apps/dai-command"
  copy_package "$cmd/dai_command" "$root"
  for bin in dai-command dai-fixlayout dai-lang; do
    install -m 0755 "$cmd/data/$bin" "$root/usr/bin/$bin"
  done
  install -m 0644 "$cmd/data/dai-command.desktop" "$root/usr/share/applications/"

  local tune="$REPO_ROOT/apps/dai-tune"
  copy_package "$tune/dai_tune" "$root"
  install -m 0755 "$tune/data/dai-tune" "$root/usr/bin/dai-tune"
  install -m 0755 "$tune/data/dai-tune-helper" "$root/usr/lib/dai/dai-tune-helper"
  install -m 0644 "$tune/data/io.github.diamondrubinny.dai.tune.policy" "$root/usr/share/polkit-1/actions/"

  local ai="$REPO_ROOT/apps/dai-ai"
  copy_package "$ai/dai_ai" "$root"
  for bin in daid dai-ai dai-models; do
    install -m 0755 "$ai/data/$bin" "$root/usr/bin/$bin"
  done
  install -m 0644 "$ai/data/models.json" "$root/usr/share/dai/models.json"
  install -m 0644 "$ai/data/dai-daid.socket" "$ai/data/dai-daid.service" "$root/usr/lib/systemd/user/"

  local forge="$REPO_ROOT/apps/dai-forge"
  copy_package "$forge/dai_forge" "$root"
  install -m 0755 "$forge/data/dai-forge" "$forge/data/dai-forge-gui" "$root/usr/bin/"
  install -m 0644 "$forge/data/dai-forge.desktop" "$root/usr/share/applications/"
  install -d "$root/usr/share/dai/forge/recipes" "$root/usr/share/dai/forge/examples" "$root/etc/dai/forge/recipes"
  install -m 0644 "$forge"/data/recipes/*.json "$root/usr/share/dai/forge/recipes/"
  install -m 0644 "$forge"/examples/* "$root/usr/share/dai/forge/examples/"
  install -m 0644 "$forge/data/forge.json" "$root/etc/dai/forge.json"

  local code="$REPO_ROOT/apps/dai-code"
  copy_package "$code/dai_code" "$root"
  install -m 0755 "$code/data/dai-code" "$root/usr/bin/dai-code"

  local voice="$REPO_ROOT/apps/dai-voice"
  copy_package "$voice/dai_voice" "$root"
  install -m 0755 "$voice/data/dai-voice" "$root/usr/bin/dai-voice"

  # Update source, only with a real signing key: apt must never trust an unsigned source.
  if [[ -f "$KEYRING" ]]; then
    install -d "$root/usr/share/keyrings" "$root/etc/apt/sources.list.d" "$root/etc/apt/preferences.d"
    install -m 0644 "$KEYRING" "$root/usr/share/keyrings/dai-archive-keyring.asc"
    printf '%s\n' "# D.Ai OS updates (docs/RELEASE.md). Installed by dai-apps." \
      "Types: deb" "URIs: $APT_URL" "Suites: download/" \
      "Signed-By: /usr/share/keyrings/dai-archive-keyring.asc" >"$root/etc/apt/sources.list.d/dai.sources"
    install -m 0644 "$REPO_ROOT/build/keys/dai-archive.pref" "$root/etc/apt/preferences.d/dai-archive.pref"
  else
    log "no $KEYRING: dai-apps will not include the update source"
  fi

  install -d "$root/DEBIAN"
  cat >"$root/DEBIAN/postinst" <<'EOF'
#!/bin/sh
# D.Ai OS — Diamond Rubinny (d.Ai)
set -e
if [ "$1" = configure ]; then
  # Same as "systemctl --global enable dai-daid.socket" (works in a chroot too).
  install -d /etc/systemd/user/sockets.target.wants
  ln -sf /usr/lib/systemd/user/dai-daid.socket /etc/systemd/user/sockets.target.wants/dai-daid.socket
fi
exit 0
EOF
  cat >"$root/DEBIAN/prerm" <<'EOF'
#!/bin/sh
# D.Ai OS — Diamond Rubinny (d.Ai)
set -e
# Bytecode written at run time is not part of the package.
find /usr/lib/dai -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
if [ "$1" = remove ]; then
  rm -f /etc/systemd/user/sockets.target.wants/dai-daid.socket
fi
exit 0
EOF
  chmod 0755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm"

  finish "$root" dai-apps all \
    "python3 (>= 3.11), python3-pyqt6, bubblewrap, pkexec, polkitd, wl-clipboard, wtype, libnotify-bin, pipewire-bin" \
    "D.Ai OS apps: Command, Tune, local AI, Forge, Code and Voice" \
    "dai-llama-runtime, dai-whisper-runtime, git"
}

build_runtime() { # build_runtime <dist> <name> <dir> <check-binary> <description>
  local dist="$1" name="$2" dir="$3" check="$4" description="$5"
  if [[ -z "$dist" ]]; then
    log "skipping $name (no dist directory given)"
    return
  fi
  [[ -x "$dist/$check" ]] || die "$dist has no $check"
  local root="$WORK/$name"
  install -d "$root/opt/dai/$dir"
  cp -a "$dist/." "$root/opt/dai/$dir/"
  finish "$root" "$name" amd64 "libc6, libgcc-s1, libstdc++6, libgomp1" "$description"
}

build_panel_plugin() {
  local dist="${DAI_PANEL_PLUGIN:-}"
  if [[ -z "$dist" || ! -f "$dist/libdaicommand.so" ]]; then
    log "skipping dai-panel-plugin (no plugin build given)"
    return
  fi
  local root="$WORK/dai-panel-plugin"
  install -d "$root/usr/lib/x86_64-linux-gnu/lxqt-panel" "$root/usr/share/lxqt/lxqt-panel"
  install -m 0644 "$dist/libdaicommand.so" "$root/usr/lib/x86_64-linux-gnu/lxqt-panel/"
  install -m 0644 "$dist/daicommand.desktop" "$root/usr/share/lxqt/lxqt-panel/"
  finish "$root" dai-panel-plugin amd64 "lxqt-panel, dai-apps" "D.Ai command field for the LXQt panel"
}

main() {
  command -v dpkg-deb >/dev/null || die "dpkg-deb is required"
  install -d "$OUT_DIR"
  rm -f -- "$OUT_DIR"/dai-*.deb
  log "version $VERSION → $OUT_DIR"
  build_apps
  build_runtime "${DAI_LLAMA_DIST:-}" dai-llama-runtime llama llama-server "llama.cpp runtime for the D.Ai local AI"
  build_runtime "${DAI_WHISPER_DIST:-}" dai-whisper-runtime whisper whisper-cli "whisper.cpp runtime for D.Ai Voice"
  build_panel_plugin
}

main
