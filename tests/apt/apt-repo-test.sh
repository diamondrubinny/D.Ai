#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
# End-to-end test of D.Ai OS updates (docs/RELEASE.md §5), as root in a
# disposable Debian trixie container:
#   - the signed flat repository is accepted, also behind a 302 redirect (like GitHub Releases)
#   - only dai-* packages can come from it (a fake "sudo 99" is never a candidate)
#   - a repository signed by another key, or not signed at all, is rejected
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT
WORK="$(mktemp -d)"
readonly WORK
export GNUPGHOME="$WORK/gnupg"
PIDS=()
cleanup() {
  kill "${PIDS[@]}" 2>/dev/null || true
  rm -f /etc/apt/sources.list.d/dai.sources /etc/apt/preferences.d/dai-archive.pref \
    /usr/share/keyrings/dai-archive-keyring.asc
  rm -rf -- "$WORK" /var/lib/apt/lists/127.0.0.1*
}
trap cleanup EXIT

pass() { printf '[PASS] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*"; exit 1; }

[[ "$(id -u)" == 0 ]] || fail "run as root in a disposable container"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends apt-utils gnupg python3 ca-certificates >/dev/null

# Two keys: the archive key and an attacker's key.
install -d -m 0700 "$GNUPGHOME"
for name in archive attacker; do
  gpg --batch --quiet --passphrase '' --quick-gen-key "D.Ai test $name <$name@example.invalid>" ed25519 sign 1d
done
key_id() { gpg --batch --list-keys --with-colons "$1@example.invalid" | awk -F: '/^fpr/ {print $10; exit}'; }
ARCHIVE="$(key_id archive)" ATTACKER="$(key_id attacker)"
gpg --batch --armor --export "$ARCHIVE" >"$WORK/dai-archive-keyring.asc"

# The packages, as CI builds them, with the update source pointing at the redirector.
DAI_VERSION=0.1.0-alpha+test DAI_KEYRING="$WORK/dai-archive-keyring.asc" DAI_APT_URL="http://127.0.0.1:8081/o/r/releases/latest/" \
  bash "$REPO_ROOT/build/scripts/build-debs.sh" "$WORK/debs"

# A malicious package that tries to replace a Debian package.
install -d "$WORK/evil/DEBIAN"
printf 'Package: sudo\nVersion: 99\nArchitecture: all\nMaintainer: x <x@example.invalid>\nDescription: evil\n' \
  >"$WORK/evil/DEBIAN/control"
dpkg-deb --root-owner-group --build "$WORK/evil" "$WORK/debs/sudo_99_all.deb" >/dev/null

DAI_APT_KEY_ID="$ARCHIVE" bash "$REPO_ROOT/build/scripts/build-apt-repo.sh" "$WORK/debs" "$WORK/repo"
grep -q '^Origin: D.Ai$' "$WORK/repo/Release" || fail "Release has no D.Ai origin"
pass "repository built and signed"

# Static file server laid out like GitHub (.../releases/latest/download/<asset>)
# and a redirector on another port (GitHub sends release downloads elsewhere).
install -d "$WORK/srv/o/r/releases/latest"
ln -s "$WORK/repo" "$WORK/srv/o/r/releases/latest/download"
python3 -m http.server 8082 --bind 127.0.0.1 --directory "$WORK/srv" >/dev/null 2>&1 &
PIDS+=($!)
python3 - <<'PY' >/dev/null 2>&1 &
import http.server
class Redirect(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:8082" + self.path)
        self.end_headers()
    do_HEAD = do_GET
http.server.HTTPServer(("127.0.0.1", 8081), Redirect).serve_forever()
PY
PIDS+=($!)
sleep 1

# Install the update source and pinning exactly as dai-apps ships them.
dpkg-deb -x "$WORK"/debs/dai-apps_*_all.deb "$WORK/apps"
cp "$WORK/apps/etc/apt/sources.list.d/dai.sources" /etc/apt/sources.list.d/
cp "$WORK/apps/etc/apt/preferences.d/dai-archive.pref" /etc/apt/preferences.d/
install -D -m 0644 "$WORK/apps/usr/share/keyrings/dai-archive-keyring.asc" /usr/share/keyrings/dai-archive-keyring.asc
grep -q 'Signed-By: /usr/share/keyrings/dai-archive-keyring.asc' /etc/apt/sources.list.d/dai.sources \
  || fail "the update source is not bound to the archive key"

apt-get update 2>&1 | tee "$WORK/update.log"
grep -Eq 'NO_PUBKEY|not signed|BADSIG|Err:|Conflicting' "$WORK/update.log" && fail "signed repository rejected or misconfigured"
# Commands are captured first: "cmd | grep -q" can fail under pipefail (SIGPIPE).
has() { grep -q -- "$2" <<<"$1"; }
has "$(apt-cache policy dai-apps)" 'Candidate: 0.1.0~alpha+test' || fail "dai-apps not offered"
pass "signed repository accepted through a redirect"

(cd "$WORK" && apt-get download dai-apps >/dev/null) || fail "dai-apps download/hash check failed"
compgen -G "$WORK/dai-apps_*_all.deb" >/dev/null || fail "dai-apps was not downloaded"
has "$(apt-get install -s -y dai-apps)" '^Inst dai-apps' || fail "dai-apps cannot be installed"
pass "dai-apps downloads (hash verified) and resolves its dependencies"

policy="$(apt-cache policy sudo)"
printf '%s\n' "$policy"
has "$policy" ' 99 ' || fail "the fake sudo 99 is not in the archive index (test is not meaningful)"
has "$policy" 'Candidate: 99' && fail "pinning: the D.Ai archive could replace sudo"
has "$(apt-get install -s -y sudo)" 'Inst sudo (99' && fail "pinning: sudo 99 would be installed"
pass "pinning: a non-dai package from the D.Ai archive is never installed"

expect_rejected() { # expect_rejected <label>
  rm -rf /var/lib/apt/lists/127.0.0.1*
  apt-get update >"$WORK/bad.log" 2>&1 || true
  grep -Eq 'NO_PUBKEY|not signed|BADSIG|is not signed|EXPKEYSIG|Err:' "$WORK/bad.log" || {
    cat "$WORK/bad.log"; fail "$1 was not rejected"; }
  has "$(apt-cache policy dai-apps)" 'Candidate: 0.1.0~alpha+test' && fail "$1: packages still offered"
  pass "$1 is rejected"
}

gpg --batch --yes --local-user "$ATTACKER" --clearsign -o "$WORK/repo/InRelease" "$WORK/repo/Release"
gpg --batch --yes --local-user "$ATTACKER" --armor --detach-sign -o "$WORK/repo/Release.gpg" "$WORK/repo/Release"
expect_rejected "a repository signed by another key"

rm -f "$WORK/repo/InRelease" "$WORK/repo/Release.gpg"
expect_rejected "an unsigned repository"

echo "apt repository tests: all passed — D.Ai OS by Diamond Rubinny (d.Ai)"
