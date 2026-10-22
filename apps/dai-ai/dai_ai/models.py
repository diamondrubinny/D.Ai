# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
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

# Hugging Face and its CDN subdomains (the CDN host names change over time).
# Integrity does not depend on the host: every file must match a pinned SHA-256.
ALLOWED_DOMAINS = ("huggingface.co", "hf.co")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,48}$")
CHUNK = 1024 * 1024
TASKS = ("general", "code", "speech")  # speech: whisper.cpp models for D.Ai Voice


class ModelError(RuntimeError):
    pass


def host_allowed(host: str | None) -> bool:
    """Exact domain or a real subdomain of it ("evilhf.co" is not "hf.co")."""
    host = (host or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS)


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
    tasks: tuple[str, ...] = ("general",)

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
        if not isinstance(raw.get("tasks", []), list) or not all(t in TASKS for t in raw.get("tasks", [])):
            raise ModelError(f"invalid tasks in catalog entry: {raw.get('id')}")
        model = Model(**{**raw, "tasks": tuple(raw.get("tasks", ["general"]))})
        suffix = ".bin" if "speech" in model.tasks else ".gguf"  # whisper.cpp uses ggml .bin files
        if not ID_RE.match(model.id) or "/" in model.file or not model.file.endswith(suffix):
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
        if parsed.scheme != "https" or not host_allowed(parsed.hostname):
            raise ModelError(f"refusing redirect to {parsed.scheme}://{parsed.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host_allowed(host):
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


def default_model_id(models: dict[str, Model], task: str = "general") -> str | None:
    """The model to use for a task: chat ("general"), code, or speech.

    Speech models are never used for chat and vice versa; code falls back to
    the general model when no coding model is installed.
    """
    if task != "general":
        suited = [m for m in models.values() if m.installed and task in m.tasks]
        if task == "speech":
            chosen = _configured("speech_model")
            if chosen in models and models[chosen].installed and "speech" in models[chosen].tasks:
                return chosen
            return min(suited, key=lambda m: m.size).id if suited else None
        if suited:
            return min(suited, key=lambda m: m.ram_mb).id
    chat_models = {k: m for k, m in models.items() if "general" in m.tasks}
    installed = [m for m in chat_models.values() if m.installed]
    if _configured_flag("prefer_small"):  # memory saver (docs/BEYOND.md §14): the smallest, whatever was chosen
        return min(installed, key=lambda m: m.ram_mb).id if installed else None
    chosen = _configured("model")
    if chosen in chat_models and chat_models[chosen].installed:
        return chosen
    return min(installed, key=lambda m: m.ram_mb).id if installed else None


def _configured(key: str) -> str | None:
    try:
        value = json.loads(config_file().read_text(encoding="utf-8")).get(key)
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _configured_flag(key: str) -> bool:
    try:
        return json.loads(config_file().read_text(encoding="utf-8")).get(key) is True
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def set_default(model_id: str, key: str = "model") -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[key] = model_id
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args[:1] == ["--version"]:
        from . import __author__, __version__

        print(f"dai-models {__version__} — {__author__}")
        return 0
    try:
        models = load_catalog()
    except (OSError, ModelError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"dai-models: cannot read catalog: {exc}", file=sys.stderr)
        return 1
    command = args[0] if args else "list"
    if command == "provider":
        from .providers_cli import main as provider_main

        return provider_main(args[1:])
    if command == "list":
        defaults = {default_model_id(models), default_model_id(models, "speech")}
        for model in models.values():
            state = "installed" if model.installed else "available"
            mark = "*" if model.id in defaults else " "
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
                key = "speech_model" if "speech" in model.tasks else "model"
                same_kind = [m for m in models.values() if m.installed and ("speech" in m.tasks) == ("speech" in model.tasks)]
                if len(same_kind) == 1:
                    set_default(model.id, key)
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
                set_default(model.id, "speech_model" if "speech" in model.tasks else "model")
                print(f"✓ default model: {model.id}")
        except (ModelError, OSError) as exc:
            print(f"\n✗ {exc}", file=sys.stderr)
            return 1
        return 0
    print("usage: dai-models [list | install <id> | verify <id> | use <id> | remove <id> | provider …]", file=sys.stderr)
    return 2
