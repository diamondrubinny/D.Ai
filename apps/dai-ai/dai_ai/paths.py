# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Filesystem locations used by the local AI components."""

from __future__ import annotations

import os
from pathlib import Path

LLAMA_DIR = Path(os.environ.get("DAI_LLAMA_DIR", "/opt/dai/llama"))
CATALOG = Path(os.environ.get("DAI_MODELS_CATALOG", "/usr/share/dai/models.json"))


def runtime_dir() -> Path:
    """Per-user 0700 directory for sockets ($XDG_RUNTIME_DIR/dai)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/dai-{os.getuid()}"
    path = Path(base) / "dai"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def daid_socket() -> Path:
    return runtime_dir() / "daid.sock"


def models_dir() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(data) / "dai" / "models"


def config_file() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "dai" / "ai.json"
