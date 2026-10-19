# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The VirtIO drivers for Windows (docs/VM.md §2, "Drivers"): Fedora's virtio-win ISO, one pinned release with
its SHA-256 in data/drivers.json, downloaded once with the person's OK, verified before use, kept under
~/.local/share/dai/vm/drivers. It is attached to a machine as a second CD, so Windows setup finds the disk and
the network, and the guest tools can be installed from it afterwards.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# The catalog: next to the package in the repository, or where the image installs it.
CATALOG_CANDIDATES = (Path(__file__).resolve().parent.parent / "data" / "drivers.json",
                      Path("/usr/share/dai/vm/drivers.json"))
CATALOG = next((p for p in CATALOG_CANDIDATES if p.is_file()), CATALOG_CANDIDATES[0])
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Driver:
    id: str
    version: str
    url: str
    file: str
    sha256: str
    size: int
    license: str

    @property
    def pinned(self) -> bool:
        return bool(SHA256_RE.match(self.sha256))


class DriverError(RuntimeError):
    pass


def catalog(path: Path = CATALOG) -> dict[str, Driver]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in data.get("drivers", []):
        out[item["id"]] = Driver(item["id"], item["version"], item["url"], item["file"], item["sha256"].lower(),
                                 int(item["size"]), item.get("license", ""))
    return out


def drivers_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".local" / "share" / "dai" / "vm" / "drivers"


def iso_path(driver: Driver, home: Path | None = None) -> Path:
    return drivers_dir(home) / driver.file


def present(driver: Driver, home: Path | None = None) -> bool:
    """Downloaded and verified before: the file is there with the right size, and its verification marker says
    the SHA-256 matched (hashing 900 MB again at every start would be slow for nothing)."""
    path = iso_path(driver, home)
    marker = path.with_suffix(path.suffix + ".sha256")
    try:
        return path.stat().st_size == driver.size and marker.read_text(encoding="utf-8").strip() == driver.sha256
    except OSError:
        return False


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise DriverError("the download was redirected away from https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_https(url: str):
    if urllib.parse.urlparse(url).scheme != "https":
        raise DriverError("drivers are downloaded over https only")
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "dai-vm/0.1"}), timeout=60)


def download(driver: Driver, home: Path | None = None, fetch: Callable[[str], object] = _open_https,
             progress: Callable[[int, int], None] | None = None) -> Path:
    """The ISO, downloaded to a .part file, hashed as it arrives, moved into place only when the hash matches."""
    if not driver.pinned:
        raise DriverError(f"{driver.id} has no pinned SHA-256; it is not downloaded")
    target = iso_path(driver, home)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    done = 0
    with fetch(driver.url) as source, open(part, "wb") as sink:
        while True:
            chunk = source.read(CHUNK)
            if not chunk:
                break
            done += len(chunk)
            if done > driver.size:
                part.unlink(missing_ok=True)
                raise DriverError("the download is larger than the catalog says")
            digest.update(chunk)
            sink.write(chunk)
            if progress:
                progress(done, driver.size)
    if done != driver.size or digest.hexdigest() != driver.sha256:
        part.unlink(missing_ok=True)
        raise DriverError("the download does not match the catalog's size or SHA-256; nothing was kept")
    part.replace(target)
    target.with_suffix(target.suffix + ".sha256").write_text(driver.sha256 + "\n", encoding="utf-8")
    return target
