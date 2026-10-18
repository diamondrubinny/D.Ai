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
write_legal() { # write_legal <root> <name>: copyright (Debian format), NOTICE, trademarks, terms
  local root="$1" name="$2" doc="$1/usr/share/doc/$2" dir
  install -d "$doc"
  {
    printf '%s\n' "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/" \
      "Upstream-Name: D.Ai OS" "Upstream-Contact: https://github.com/diamondrubinny/D.Ai/issues" \
      "Source: https://github.com/diamondrubinny/D.Ai" "" \
      "Files: *" "Copyright: 2026 Diamond Rubinny (d.Ai)" "License: Apache-2.0" \
      " On Debian systems the full text of the Apache License 2.0 is in /usr/share/common-licenses/Apache-2.0." \
      "Comment: \"D.Ai\", \"D.Ai OS\" and the diamond logo are trademarks of Diamond Rubinny (d.Ai)." \
      " The license grants no rights to them (Apache-2.0 section 6); see TRADEMARKS.md in this folder." \
      " Copies must keep these copyright notices (Apache-2.0 section 4)."
    for dir in "$root"/opt/dai/*/; do
      [[ -f "$dir/LICENSE" ]] || continue
      dir="${dir#"$root"/}"
      printf '%s\n' "" "Files: ${dir}*" "Copyright: the ggml authors" "License: MIT" " See /${dir}LICENSE."
    done
  } >"$doc/copyright"
  install -m 0644 "$REPO_ROOT/NOTICE" "$REPO_ROOT/TRADEMARKS.md" "$doc/"
  install -m 0644 "$REPO_ROOT/docs/legal/TERMS.md" "$doc/TERMS.md"
}

finish() { # finish <root> <name> <arch> <depends> <description> [recommends]
  local root="$1" name="$2" arch="$3" depends="$4" description="$5" recommends="${6:-}"
  write_legal "$root" "$name"
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

  # Languages (docs/I18N.md): shared by every app; catalogs for languages other than he/en.
  copy_package "$REPO_ROOT/apps/dai-i18n/dai_i18n" "$root"
  # The Living Diamond's state file (docs/TASKBAR.md §2.1), written by Heal, Privacy and Evolve.
  copy_package "$REPO_ROOT/apps/dai-status/dai_status" "$root"
  if compgen -G "$REPO_ROOT/i18n/po/*.po" >/dev/null; then
    PYTHONPATH="$REPO_ROOT/apps/dai-i18n" python3 -m dai_i18n.tool compile "$root/usr/share/locale"
  fi

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
  # Organization policies (docs/EDU.md): applied at boot and when /etc/dai/policy.d changes.
  install -d "$root/usr/lib/systemd/system" "$root/usr/share/dai/policy-examples"
  install -m 0644 "$tune/data/dai-policy.service" "$tune/data/dai-policy.path" "$root/usr/lib/systemd/system/"
  install -m 0644 "$tune/data/policy-examples/"* "$root/usr/share/dai/policy-examples/"

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

  local find="$REPO_ROOT/apps/dai-find"
  copy_package "$find/dai_find" "$root"
  install -m 0755 "$find/data/dai-find" "$root/usr/bin/dai-find"

  local doctor="$REPO_ROOT/apps/dai-doctor"
  copy_package "$doctor/dai_doctor" "$root"
  install -m 0755 "$doctor/data/dai-doctor" "$root/usr/bin/dai-doctor"

  local privacy="$REPO_ROOT/apps/dai-privacy"
  copy_package "$privacy/dai_privacy" "$root"
  install -m 0755 "$privacy/data/dai-privacy" "$root/usr/bin/dai-privacy"
  install -d "$root/etc/xdg/autostart"
  install -m 0644 "$privacy/data/dai-privacy-autostart.desktop" "$root/etc/xdg/autostart/dai-privacy.desktop"

  local backup="$REPO_ROOT/apps/dai-backup"
  copy_package "$backup/dai_backup" "$root"
  install -m 0755 "$backup/data/dai-backup" "$root/usr/bin/dai-backup"
  # Enabled per user by "dai-backup setup", never globally.
  install -m 0644 "$backup/data/dai-backup.service" "$backup/data/dai-backup.timer" "$root/usr/lib/systemd/user/"

  local move="$REPO_ROOT/apps/dai-move"
  copy_package "$move/dai_move" "$root"
  install -m 0755 "$move/data/dai-move" "$root/usr/bin/dai-move"

  local clip="$REPO_ROOT/apps/dai-clip"
  copy_package "$clip/dai_clip" "$root"
  install -m 0755 "$clip/data/dai-clip" "$root/usr/bin/dai-clip"
  install -m 0644 "$clip/data/dai-clip.desktop" "$root/usr/share/applications/"
  install -d "$root/etc/xdg/autostart"
  install -m 0644 "$clip/data/dai-clip-autostart.desktop" "$root/etc/xdg/autostart/dai-clip.desktop"

  # D.Ai Heal (docs/EVOLVE.md §4): help & repair chat, crash watcher, metadata-only core dumps.
  local heal="$REPO_ROOT/apps/dai-heal"
  copy_package "$heal/dai_heal" "$root"
  install -m 0755 "$heal/data/dai-heal" "$root/usr/bin/dai-heal"
  install -m 0644 "$heal/data/dai-heal.desktop" "$root/usr/share/applications/"
  install -d "$root/etc/xdg/autostart" "$root/usr/lib/systemd/coredump.conf.d"
  install -m 0644 "$heal/data/dai-heal-autostart.desktop" "$root/etc/xdg/autostart/dai-heal.desktop"
  install -m 0644 "$heal/data/50-dai-coredump.conf" "$root/usr/lib/systemd/coredump.conf.d/50-dai.conf"

  # D.Ai Quick (docs/TASKBAR.md §2.4): quick settings from the clock or Super+N.
  local quick="$REPO_ROOT/apps/dai-quick"
  copy_package "$quick/dai_quick" "$root"
  install -m 0755 "$quick/data/dai-quick" "$root/usr/bin/dai-quick"

  # MOM (docs/MOM.md): the task manager, Ctrl+Shift+Esc.
  local mom="$REPO_ROOT/apps/dai-mom"
  copy_package "$mom/dai_mom" "$root"
  install -m 0755 "$mom/data/dai-mom" "$root/usr/bin/dai-mom"
  install -m 0644 "$mom/data/dai-mom.desktop" "$root/usr/share/applications/"

  # J (docs/MAIL.md): the mail client, and the handler for mailto: links.
  local j="$REPO_ROOT/apps/dai-j"
  copy_package "$j/dai_j" "$root"
  install -m 0755 "$j/data/dai-j" "$root/usr/bin/dai-j"
  install -m 0644 "$j/data/dai-j.desktop" "$root/usr/share/applications/"
  install -D -m 0644 "$j/data/dai-j.svg" "$root/usr/share/icons/hicolor/scalable/apps/dai-j.svg"

  # D.Ai Evolve (docs/EVOLVE.md §3): notices what is missing, suggests it in D.Ai Command.
  local evolve="$REPO_ROOT/apps/dai-evolve"
  copy_package "$evolve/dai_evolve" "$root"
  install -m 0755 "$evolve/data/dai-evolve" "$root/usr/bin/dai-evolve"
  install -m 0644 "$evolve/data/dai-evolve.service" "$evolve/data/dai-evolve.timer" "$root/usr/lib/systemd/user/"

  # D.Ai OEM (docs/OEM.md): prepare a computer for its new owner; first-boot wizard.
  local oem="$REPO_ROOT/apps/dai-oem"
  copy_package "$oem/dai_oem" "$root"
  install -m 0755 "$oem/data/dai-oem" "$root/usr/bin/dai-oem"
  install -m 0755 "$oem/data/dai-oem-helper" "$oem/data/dai-oem-setup" "$root/usr/lib/dai/"
  install -d "$root/usr/share/dai/oem/labwc" "$root/usr/share/polkit-1/rules.d"
  install -m 0644 "$oem/data/dai-oem.desktop" "$root/usr/share/dai/oem/"
  install -m 0644 "$oem/data/labwc/rc.xml" "$oem/data/labwc/menu.xml" "$oem/data/labwc/autostart" "$root/usr/share/dai/oem/labwc/"
  install -m 0644 "$oem/data/io.github.diamondrubinny.dai.oem.policy" "$root/usr/share/polkit-1/actions/"
  install -m 0644 "$oem/data/50-dai-oem.rules" "$root/usr/share/polkit-1/rules.d/"
  install -m 0644 "$oem/data/dai-oem-cleanup.service" "$root/usr/lib/systemd/system/"

  local welcome="$REPO_ROOT/apps/dai-welcome"
  copy_package "$welcome/dai_welcome" "$root"
  install -m 0755 "$welcome/data/dai-welcome" "$root/usr/bin/dai-welcome"
  install -m 0644 "$welcome/data/dai-welcome.desktop" "$root/usr/share/applications/"
  install -d "$root/etc/xdg/autostart"
  install -m 0644 "$welcome/data/dai-welcome-autostart.desktop" "$root/etc/xdg/autostart/dai-welcome.desktop"

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
  # Organization policies: the folder (root only can write) and the units that watch it.
  install -d -m 0755 /etc/dai/policy.d
  install -d /etc/systemd/system/multi-user.target.wants /etc/systemd/system/paths.target.wants
  ln -sf /usr/lib/systemd/system/dai-policy.service /etc/systemd/system/multi-user.target.wants/dai-policy.service
  ln -sf /usr/lib/systemd/system/dai-policy.path /etc/systemd/system/paths.target.wants/dai-policy.path
  # D.Ai Evolve's daily scan, for every user (each can stop it: dai-evolve off).
  install -d /etc/systemd/user/timers.target.wants
  ln -sf /usr/lib/systemd/user/dai-evolve.timer /etc/systemd/user/timers.target.wants/dai-evolve.timer
  # D.Ai OEM: does nothing unless a first-boot setup was just finished.
  ln -sf /usr/lib/systemd/system/dai-oem-cleanup.service /etc/systemd/system/multi-user.target.wants/dai-oem-cleanup.service
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
  rm -f /etc/systemd/system/multi-user.target.wants/dai-policy.service /etc/systemd/system/paths.target.wants/dai-policy.path
  rm -f /etc/systemd/system/multi-user.target.wants/dai-oem-cleanup.service
  rm -f /etc/systemd/user/timers.target.wants/dai-evolve.timer
fi
exit 0
EOF
  chmod 0755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm"

  finish "$root" dai-apps all \
    "python3 (>= 3.11), python3-pyqt6, bubblewrap, pkexec, polkitd, wl-clipboard, wtype, libnotify-bin, pipewire-bin" \
    "D.Ai OS apps: Command, Tune, Find, Doctor, Privacy, Backup, Move, Diamond (local AI), Forge, Code, Voice, Welcome, MOM and J" \
    "dai-llama-runtime, dai-whisper-runtime, git, power-profiles-daemon, restic, libsecret-tools, python3-dnspython"
}

build_ruby() { # Ruby (docs/BROWSER.md): D.Ai's browsing experience on Debian's Firefox ESR, unmodified.
  local root="$WORK/dai-ruby" ruby="$REPO_ROOT/apps/dai-ruby/data"
  install -d "$root/etc/firefox/policies" "$root/usr/share/applications" "$root/usr/share/dai/ruby" \
    "$root/usr/share/icons/hicolor/scalable/apps"
  # Firefox reads /etc/firefox/policies/policies.json on Linux; root-owned, 0644.
  install -m 0644 "$ruby/policies.json" "$root/etc/firefox/policies/policies.json"
  install -m 0644 "$ruby/firefox-esr.desktop" "$root/usr/share/applications/firefox-esr.desktop"
  install -m 0644 "$ruby/start.html" "$root/usr/share/dai/ruby/start.html"
  install -m 0644 "$ruby/dai-ruby.svg" "$root/usr/share/icons/hicolor/scalable/apps/dai-ruby.svg"
  install -d "$root/DEBIAN"
  # One browser in the menu: Debian's entry moves aside (not deleted) while dai-ruby is installed.
  cat >"$root/DEBIAN/preinst" <<'EOF2'
#!/bin/sh
# D.Ai OS — Diamond Rubinny (d.Ai)
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
  dpkg-divert --package dai-ruby --add --rename \
    --divert /usr/share/applications/firefox-esr.desktop.debian /usr/share/applications/firefox-esr.desktop
fi
exit 0
EOF2
  cat >"$root/DEBIAN/postrm" <<'EOF2'
#!/bin/sh
# D.Ai OS — Diamond Rubinny (d.Ai)
set -e
if [ "$1" = remove ] || [ "$1" = abort-install ] || [ "$1" = disappear ]; then
  dpkg-divert --package dai-ruby --remove --rename \
    --divert /usr/share/applications/firefox-esr.desktop.debian /usr/share/applications/firefox-esr.desktop
fi
exit 0
EOF2
  chmod 0755 "$root/DEBIAN/preinst" "$root/DEBIAN/postrm"
  finish "$root" dai-ruby all "firefox-esr" \
    "Ruby: private browsing on Firefox ESR (ad and pop-up blocking, automatic cookie cleaning)" \
    "firefox-esr-l10n-he"
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
  install -m 0644 "$dist/libdaicommand.so" "$dist/libdaistatus.so" "$dist/libdaiclock.so" \
    "$root/usr/lib/x86_64-linux-gnu/lxqt-panel/"
  install -m 0644 "$dist/daicommand.desktop" "$dist/daistatus.desktop" "$dist/daiclock.desktop" \
    "$root/usr/share/lxqt/lxqt-panel/"
  finish "$root" dai-panel-plugin amd64 "lxqt-panel, dai-apps" "D.Ai command field, Living Diamond and clock for the LXQt panel"
}

main() {
  command -v dpkg-deb >/dev/null || die "dpkg-deb is required"
  install -d "$OUT_DIR"
  rm -f -- "$OUT_DIR"/dai-*.deb
  log "version $VERSION → $OUT_DIR"
  build_apps
  build_ruby
  build_runtime "${DAI_LLAMA_DIST:-}" dai-llama-runtime llama llama-server "llama.cpp runtime for the D.Ai local AI"
  build_runtime "${DAI_WHISPER_DIST:-}" dai-whisper-runtime whisper whisper-cli "whisper.cpp runtime for D.Ai Voice"
  build_panel_plugin
}

main
