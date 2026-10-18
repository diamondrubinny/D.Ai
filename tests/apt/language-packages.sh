#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# Every package a language recipe installs exists in Debian 13 (docs/I18N.md §9).
# Runs in a debian:trixie container: docker run --rm -v "$PWD:/src:ro" -w /src debian:trixie bash tests/apt/language-packages.sh
set -euo pipefail

apt-get update -qq >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-minimal >/dev/null
mapfile -t packages < <(python3 - <<'PY'
import glob, json
for path in sorted(glob.glob("apps/dai-forge/data/recipes/language-*.json")):
    for step in json.load(open(path))["steps"]:
        if step["action"] == "packages.install":
            print("\n".join(step["params"]["names"]))
PY
)
[ "${#packages[@]}" -ge 6 ] || { echo "no language recipes found" >&2; exit 1; }
missing=()
for package in "${packages[@]}"; do
  if apt-cache show "$package" >/dev/null 2>&1; then
    echo "ok      $package"
  else
    echo "MISSING $package"
    missing+=("$package")
  fi
done
# The locales the recipes generate are known to glibc in Debian 13.
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq locales >/dev/null
for locale in ar_EG ru_RU es_ES fr_FR de_DE pt_BR; do
  if grep -qx "$locale.UTF-8 UTF-8" /usr/share/i18n/SUPPORTED; then
    echo "ok      locale $locale.UTF-8"
  else
    echo "MISSING locale $locale.UTF-8"
    missing+=("$locale.UTF-8")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "not in Debian 13: ${missing[*]}" >&2
  exit 1
fi
echo "all ${#packages[@]} language packages and 6 locales exist in Debian 13"
