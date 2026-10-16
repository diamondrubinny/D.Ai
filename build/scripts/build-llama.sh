#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build llama-server (llama.cpp) for D.Ai OS's local AI service.
#
# Usage: build-llama.sh <output-dir>
#
# Runs in a Debian trixie container (glibc must match the image). Produces a
# self-contained directory (llama-server + shared libraries + one CPU backend
# per instruction-set level, picked at runtime) to be installed in
# /opt/dai/llama. The source is pinned to a tag AND its commit hash.
set -euo pipefail

readonly LLAMA_TAG="b11400"
readonly LLAMA_COMMIT="0bb496dbd3af0add77ff82c406a915b41e839d56"
readonly LLAMA_REPO="https://github.com/ggml-org/llama.cpp"
readonly INSTALL_DIR="/opt/dai/llama"

OUT_DIR="$(realpath -m "${1:?usage: build-llama.sh <output-dir>}")"
readonly OUT_DIR
WORK="$(mktemp -d)"
readonly WORK

log() { printf '[build-llama] %s\n' "$*" >&2; }

if ! command -v cmake >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends build-essential cmake git ca-certificates
fi

log "fetching $LLAMA_TAG"
git clone --quiet --depth 1 --branch "$LLAMA_TAG" "$LLAMA_REPO" "$WORK/src"
actual="$(git -C "$WORK/src" rev-parse HEAD)"
[[ "$actual" == "$LLAMA_COMMIT" ]] || { log "commit mismatch: $actual != $LLAMA_COMMIT"; exit 1; }

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
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_APP=OFF \
  -DLLAMA_BUILD_UI=OFF \
  -DLLAMA_USE_PREBUILT_UI=OFF \
  -DLLAMA_OPENSSL=OFF

log "building llama-server"
cmake --build "$WORK/build" --target llama-server -j "$(nproc)"
# CPU backend variants are loaded at runtime (not link dependencies of the
# server), so build each ggml-cpu-* target explicitly.
mapfile -t cpu_targets < <(cmake --build "$WORK/build" --target help | awk '/ggml-cpu-/{print $2}')
((${#cpu_targets[@]} > 0)) || { log "no ggml-cpu-* targets found"; exit 1; }
log "CPU variants: ${cpu_targets[*]}"
cmake --build "$WORK/build" -j "$(nproc)" --target "${cpu_targets[@]}"

mkdir -p "$OUT_DIR"
cp -a "$WORK/build/bin/llama-server" "$OUT_DIR/"
find "$WORK/build/bin" -maxdepth 1 -name '*.so*' -exec cp -a {} "$OUT_DIR/" \;
printf '%s %s\n' "$LLAMA_TAG" "$LLAMA_COMMIT" >"$OUT_DIR/VERSION"
cp "$WORK/src/LICENSE" "$OUT_DIR/LICENSE"

log "contents:"
ls -la "$OUT_DIR" >&2
"$OUT_DIR/llama-server" --version >&2 || true
rm -rf -- "$WORK"
