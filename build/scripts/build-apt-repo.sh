#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Build the flat, signed apt repository that ships inside each GitHub Release
# (docs/RELEASE.md §2).
#
# Usage: build-apt-repo.sh <debs-dir> <out-dir>
#
# Clients use "URIs: .../releases/latest/" with "Suites: download/": apt reads
# download/InRelease and resolves Filename against the URI, hence "download/".
#
# Environment:
#   DAI_APT_KEY_ID  gpg key (already in the keyring) that signs the repository.
#                   Without it the repository is not signed and must not be published.
set -euo pipefail
umask 022

readonly DEBS="${1:-}" OUT="${2:-}"
log() { printf '[build-apt-repo] %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

[[ -d "$DEBS" && -n "$OUT" ]] || die "usage: $(basename "$0") <debs-dir> <out-dir>"
command -v apt-ftparchive >/dev/null || die "apt-ftparchive is required (apt-utils)"
install -d "$OUT"

# Simple file names: release assets cannot hold "~" or "+" reliably.
shopt -s nullglob
debs=("$DEBS"/*.deb)
((${#debs[@]})) || die "no .deb files in $DEBS"
for deb in "${debs[@]}"; do
  package="$(dpkg-deb -f "$deb" Package)"
  arch="$(dpkg-deb -f "$deb" Architecture)"
  [[ "$package" =~ ^[a-z0-9][a-z0-9.+-]*$ && "$arch" =~ ^[a-z0-9]+$ ]] || die "unexpected package fields in $deb"
  cp -- "$deb" "$OUT/${package}_${arch}.deb"
done

cd "$OUT"
apt-ftparchive packages . | sed 's|^Filename: \./|Filename: download/|' >Packages
gzip -9nc Packages >Packages.gz
apt-ftparchive \
  -o APT::FTPArchive::Release::Origin="D.Ai" \
  -o APT::FTPArchive::Release::Label="D.Ai OS" \
  -o APT::FTPArchive::Release::Suite="download/" \
  -o APT::FTPArchive::Release::Description="D.Ai OS packages by Diamond Rubinny (d.Ai)" \
  release . >Release

if [[ -n "${DAI_APT_KEY_ID:-}" ]]; then
  gpg --batch --yes --local-user "$DAI_APT_KEY_ID" --clearsign -o InRelease Release
  gpg --batch --yes --local-user "$DAI_APT_KEY_ID" --armor --detach-sign -o Release.gpg Release
  log "signed with $DAI_APT_KEY_ID"
else
  log "warning: DAI_APT_KEY_ID not set; the repository is NOT signed"
fi
log "repository: $OUT ($(find . -maxdepth 1 -type f | wc -l) files)"
