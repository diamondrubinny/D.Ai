#!/usr/bin/env bash
# Build the D.Ai Command field plugin for lxqt-panel.
#
# Usage: build-panel-plugin.sh <output-dir>
#
# Runs in a Debian trixie container. The plugin interface headers come from
# the upstream lxqt-panel tag matching Debian's package, pinned by commit.
set -euo pipefail

readonly PANEL_TAG="2.1.4"
readonly PANEL_COMMIT="b094cc8fd560992eee096d3f28d0213c8b6a945f"
readonly PANEL_REPO="https://github.com/lxqt/lxqt-panel"

OUT_DIR="$(realpath -m "${1:?usage: build-panel-plugin.sh <output-dir>}")"
readonly OUT_DIR
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../apps/dai-panel-plugin" && pwd)"
readonly SRC_DIR
WORK="$(mktemp -d)"
readonly WORK

log() { printf '[build-panel-plugin] %s\n' "$*" >&2; }

if ! command -v cmake >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends cmake g++ make git ca-certificates qt6-base-dev
fi

git clone --quiet --depth 1 --branch "$PANEL_TAG" "$PANEL_REPO" "$WORK/lxqt-panel"
actual="$(git -C "$WORK/lxqt-panel" rev-parse HEAD)"
[[ "$actual" == "$PANEL_COMMIT" ]] || { log "commit mismatch: $actual != $PANEL_COMMIT"; exit 1; }

cmake -S "$SRC_DIR" -B "$WORK/build" -DCMAKE_BUILD_TYPE=Release -DLXQT_PANEL_SRC="$WORK/lxqt-panel"
cmake --build "$WORK/build" -j "$(nproc)"

mkdir -p "$OUT_DIR"
install -m 0644 "$WORK/build/libdaicommand.so" "$OUT_DIR/libdaicommand.so"
install -m 0644 "$SRC_DIR/daicommand.desktop" "$OUT_DIR/daicommand.desktop"
printf 'lxqt-panel %s %s\n' "$PANEL_TAG" "$PANEL_COMMIT" >"$OUT_DIR/VERSION"
ls -la "$OUT_DIR" >&2
rm -rf -- "$WORK"
