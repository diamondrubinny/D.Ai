#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build whisper-cli (whisper.cpp) for D.Ai Voice: local speech-to-text.
#
# Usage: build-whisper.sh <output-dir>
#
# Runs in a Debian trixie container (glibc must match the image). Produces a
# self-contained directory (whisper-cli + shared libraries + one CPU backend
# per instruction-set level, picked at runtime) to be installed in
# /opt/dai/whisper. The source is pinned to a tag AND its commit hash.
set -euo pipefail

readonly WHISPER_TAG="v1.9.5"
readonly WHISPER_COMMIT="d1be6fde11ac6e0407606b4e42fe72d34add8037"
readonly WHISPER_REPO="https://github.com/ggml-org/whisper.cpp"
readonly INSTALL_DIR="/opt/dai/whisper"

OUT_DIR="$(realpath -m "${1:?usage: build-whisper.sh <output-dir>}")"
readonly OUT_DIR
WORK="$(mktemp -d)"
readonly WORK

log() { printf '[build-whisper] %s\n' "$*" >&2; }

if ! command -v cmake >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends build-essential cmake git ca-certificates
fi

log "fetching $WHISPER_TAG"
git clone --quiet --depth 1 --branch "$WHISPER_TAG" "$WHISPER_REPO" "$WORK/src"
actual="$(git -C "$WORK/src" rev-parse HEAD)"
[[ "$actual" == "$WHISPER_COMMIT" ]] || { log "commit mismatch: $actual != $WHISPER_COMMIT"; exit 1; }

log "configuring"
cmake -S "$WORK/src" -B "$WORK/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DGGML_NATIVE=OFF \
  -DGGML_BACKEND_DL=ON \
  -DGGML_CPU_ALL_VARIANTS=ON \
  -DGGML_BACKEND_DIR="$INSTALL_DIR" \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
  -DCMAKE_BUILD_RPATH="\$ORIGIN" \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_EXAMPLES=ON \
  -DWHISPER_BUILD_SERVER=OFF \
  -DWHISPER_SDL2=OFF \
  -DWHISPER_CURL=OFF \
  -DWHISPER_FFMPEG=OFF

log "building whisper-cli"
cmake --build "$WORK/build" --target whisper-cli -j "$(nproc)"
mapfile -t cpu_targets < <(cmake --build "$WORK/build" --target help | awk '/ggml-cpu-/{print $2}')
((${#cpu_targets[@]} > 0)) || { log "no ggml-cpu-* targets found"; exit 1; }
log "CPU variants: ${cpu_targets[*]}"
cmake --build "$WORK/build" -j "$(nproc)" --target "${cpu_targets[@]}"

mkdir -p "$OUT_DIR"
cp -a "$WORK/build/bin/whisper-cli" "$OUT_DIR/"
find "$WORK/build/bin" "$WORK/build/src" "$WORK/build/ggml/src" -maxdepth 1 -name '*.so*' -exec cp -a {} "$OUT_DIR/" \;
printf '%s %s\n' "$WHISPER_TAG" "$WHISPER_COMMIT" >"$OUT_DIR/VERSION"
cp "$WORK/src/LICENSE" "$OUT_DIR/LICENSE"
# A short public-domain test clip (JFK, 1961) used by the boot test.
cp "$WORK/src/samples/jfk.wav" "$OUT_DIR/test-jfk.wav"

log "contents:"
ls -la "$OUT_DIR" >&2
"$OUT_DIR/whisper-cli" --help >/dev/null 2>&1 && log "whisper-cli runs"
rm -rf -- "$WORK"
