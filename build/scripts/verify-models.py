#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Verify (or, for unpinned entries, compute) model SHA-256 values.

Usage: verify-models.py <models.json>

For every catalog entry: download over HTTPS, hash the bytes, and compare with
(1) the pinned sha256 and (2) the sha256 Hugging Face publishes for the file
(LFS metadata). Prints the values to pin for unpinned entries and exits
non-zero until every entry is pinned and matches.
"""

import hashlib
import json
import sys
import urllib.parse
import urllib.request


def hf_published_sha256(url: str) -> str:
    # https://huggingface.co/<org>/<repo>/resolve/<rev>/<file>
    parts = urllib.parse.urlparse(url).path.strip("/").split("/")
    org, repo, rev, filename = parts[0], parts[1], parts[3], "/".join(parts[4:])
    api = f"https://huggingface.co/api/models/{org}/{repo}/tree/{rev}"
    with urllib.request.urlopen(api, timeout=60) as response:
        for entry in json.load(response):
            if entry.get("path") == filename:
                return (entry.get("lfs") or {}).get("oid", "")
    return ""


def main() -> int:
    catalog = json.load(open(sys.argv[1], encoding="utf-8"))
    ok = True
    for model in catalog["models"]:
        digest, size = hashlib.sha256(), 0
        with urllib.request.urlopen(model["url"], timeout=120) as response:
            for block in iter(lambda: response.read(1 << 20), b""):
                digest.update(block)
                size += len(block)
        computed = digest.hexdigest()
        published = hf_published_sha256(model["url"])
        print(f"{model['id']}: size={size} computed={computed} published={published} pinned={model['sha256'] or '-'}")
        if computed != published:
            print(f"  ✗ downloaded bytes do not match the published hash")
            ok = False
        if model["sha256"] != computed or model["size"] != size:
            print(f'  ✗ pin with: "sha256": "{computed}", "size": {size}')
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
