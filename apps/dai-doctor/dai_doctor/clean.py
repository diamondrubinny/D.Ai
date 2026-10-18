# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""User-level cleanup: the trash and picture previews, nothing else.

Both are recreated as needed; nothing outside these two folders is touched,
and symlinks are removed as links, never followed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .facts import dir_size

TARGETS = (".local/share/Trash/files", ".local/share/Trash/info", ".cache/thumbnails")


def clean_user(home: Path) -> int:
    """Delete the contents of the trash and thumbnail folders; return bytes freed."""
    import time

    freed = 0
    for rel in TARGETS:
        folder = home / rel
        if not folder.is_dir() or folder.is_symlink():
            continue
        freed += dir_size(folder, time.monotonic() + 30)
        for entry in os.scandir(folder):
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return freed
