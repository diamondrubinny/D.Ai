# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""D.Ai Voice: local speech to text with whisper.cpp (no cloud, no network).

Push to talk: the first press starts recording, the second stops it; the
audio is transcribed inside a bubblewrap sandbox without network access and
deleted immediately. The text is typed into the active window, opened in
D.Ai Command, or returned to the caller.
"""

__version__ = "0.1.0"
__author__ = "Diamond Rubinny (d.Ai)"
__license__ = "Apache-2.0"
