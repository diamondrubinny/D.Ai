"""Model catalog, download and verification (dai-models)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import CATALOG, config_file, models_dir

ALLOWED_HOSTS = ("huggingface.co", "cdn-lfs.hf.co", "cdn-lfs-us-1.hf.co", "cas-bridge.xethub.hf.co")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,48}$")
CHUNK = 1024 * 1024


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    url: str
    file: str
    sha256: str
    size: int
    license: str
    ram_mb: int
    purpose: str

    @property
    def path(self) -> Path:
        return models_dir() / self.file

    @property
    def pinned(self) -> bool:
        return bool(SHA256_RE.match(self.sha256))

    @property
    def installed(self) -> bool:
        return self.path.is_file()


def load_catalog(path: Path = CATALOG) -> dict[str, Model]:
    data = json.loads(path.read_text(encoding="utf-8"))
    models: dict[str, Model] = {}
    for raw in data["models"]:
        model = Model(**raw)
        if not ID_RE.match(model.id) or "/" in model.file or not model.file.endswith(".gguf"):
            raise ModelError(f"invalid catalog entry: {model.id}")
        if urllib.parse.urlparse(model.url).scheme != "https":
            raise ModelError(f"catalog URL must be https: {model.id}")
        models[model.id] = model
    return models


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(ALLOWED_HOSTS):
            raise ModelError(f"refusing redirect to {parsed.scheme}://{parsed.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    host = urllib.parse.urlparse(url).hostname or ""
    if not host.endswith(ALLOWED_HOSTS):
        raise ModelError(f"host not allowed: {host}")
    opener = urllib.request.build_opener(_HttpsOnlyRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "dai-models/0.1"})
    return opener.open(request, timeout=60)


def install(model: Model, progress: Callable[[int, int], None] | None = None, opener=_open) -> Path:
    """Download, verify the pinned SHA-256, then move into place atomically."""
    if not model.pinned:
        raise ModelError(f"{model.id} has no pinned SHA-256; refusing to install")
    target = model.path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.is_file() and sha256_file(target) == model.sha256:
        return target
    free = shutil.disk_usage(target.parent).free
    if free < model.size * 1.1:
        raise ModelError(f"not enough disk space: need {model.size // 2**20} MB, have {free // 2**20} MB")
    partial = target.with_suffix(".part")
    digest = hashlib.sha256()
    done = 0
    with opener(model.url) as response, partial.open("wb") as out:
        for block in iter(lambda: response.read(CHUNK), b""):
            out.write(block)
            digest.update(block)
            done += len(block)
            if done > model.size * 1.05:
                raise ModelError("download is larger than expected; aborting")
            if progress:
                progress(done, model.size)
    if digest.hexdigest() != model.sha256:
        partial.unlink(missing_ok=True)
        raise ModelError(f"SHA-256 mismatch for {model.id}; the download was discarded")
    os.chmod(partial, 0o600)
    os.replace(partial, target)
    return target


def default_model_id(models: dict[str, Model]) -> str | None:
    try:
        chosen = json.loads(config_file().read_text(encoding="utf-8")).get("model")
        if chosen in models and models[chosen].installed:
            return chosen
    except (OSError, json.JSONDecodeError):
        pass
    installed = [m for m in models.values() if m.installed]
    return min(installed, key=lambda m: m.ram_mb).id if installed else None


def set_default(model_id: str) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model_id}) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = argv[1:]
    try:
        models = load_catalog()
    except (OSError, ModelError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"dai-models: cannot read catalog: {exc}", file=sys.stderr)
        return 1
    command = args[0] if args else "list"
    if command == "list":
        default = default_model_id(models)
        for model in models.values():
            state = "installed" if model.installed else "available"
            mark = "*" if model.id == default else " "
            print(f"{mark} {model.id:22} {model.size / 2**30:5.1f} GB  RAM≥{model.ram_mb} MB  {model.license:12} {state}  {model.purpose}")
        return 0
    if command in ("install", "verify", "remove", "use") and len(args) == 2 and args[1] in models:
        model = models[args[1]]
        try:
            if command == "install":
                def show(done: int, total: int) -> None:
                    print(f"\r  {model.id}: {done * 100 // max(total, 1):3d}%", end="", flush=True)
                install(model, show)
                print(f"\n✓ {model.id} installed and verified (SHA-256)")
                if default_model_id(models) is None or len([m for m in models.values() if m.installed]) == 1:
                    set_default(model.id)
            elif command == "verify":
                ok = model.installed and sha256_file(model.path) == model.sha256
                print(("✓ verified: " if ok else "✗ missing or modified: ") + model.id)
                return 0 if ok else 1
            elif command == "remove":
                model.path.unlink(missing_ok=True)
                print(f"✓ removed {model.id}")
            else:
                if not model.installed:
                    raise ModelError(f"{model.id} is not installed")
                set_default(model.id)
                print(f"✓ default model: {model.id}")
        except (ModelError, OSError) as exc:
            print(f"\n✗ {exc}", file=sys.stderr)
            return 1
        return 0
    print("usage: dai-models [list | install <id> | verify <id> | use <id> | remove <id>]", file=sys.stderr)
    return 2
