# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Filesystem locations used by D.Ai Forge (overridable for tests)."""

from __future__ import annotations

import os
from pathlib import Path

BUILTIN_RECIPES = Path(os.environ.get("DAI_FORGE_BUILTIN", "/usr/share/dai/forge/recipes"))
ADMIN_RECIPES = Path(os.environ.get("DAI_FORGE_ADMIN", "/etc/dai/forge/recipes"))
POLICY_FILE = Path(os.environ.get("DAI_FORGE_POLICY", "/etc/dai/forge.json"))


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def user_recipes() -> Path:
    return _data_home() / "dai" / "forge" / "recipes"


def apps_dir() -> Path:
    """Source of the apps the user built: visible, editable, theirs."""
    return Path(os.environ.get("DAI_APPS_DIR") or Path.home() / "Apps")


def app_data_dir(name: str) -> Path:
    """The only writable place an app sees; mounted as its home in the sandbox."""
    return _data_home() / "dai" / "apps" / name


def desktop_dir() -> Path:
    return _data_home() / "applications"
