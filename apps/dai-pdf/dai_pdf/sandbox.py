# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The sandbox every PDF is opened in (docs/PDF.md §2, §3).

The window never parses a PDF. A helper process does, inside bubblewrap: no network, no home folder, no
devices beyond /dev/null and friends, read-only /usr, the one file read-only, its own empty /tmp, and limits on
memory and CPU time. A bug in the renderer (PDFium), the parser (qpdf), or a font library stays inside.

The arguments are the same as Diamond Chat's picture sandbox (dai_chat.pictures), with the file bound in.
"""
from __future__ import annotations

import shutil
from pathlib import Path

CPU_SECONDS = 120          # for the whole helper process, not per page: a page is asked for again after a restart
# Bytes of writable memory (RLIMIT_DATA). Not the address space: PDFium reserves enormous address ranges it never
# touches, so an --as limit kills it at startup; --data limits what it can really fill, and a page that does not
# fit is answered with "could not draw" (checked by tests/test_pdf_reader.py).
MEMORY = 1536 * 1024 * 1024

# The helper's entry: `python3 -I -c BOOT <package dir> ...` so -I can ignore PYTHONPATH and still find us.
BOOT = "import sys; sys.path.insert(0, sys.argv[1]); from dai_pdf.helper import main; sys.exit(main())"
# The editor's entry (docs/PDF.md stage 2): one request on stdin, one answer on stdout, the result in /tmp/out.
BOOT_EDIT = "import sys; sys.path.insert(0, sys.argv[1]); from dai_pdf.edit import main; sys.exit(main())"
IN_DIR, OUT_DIR = "/tmp/in", "/tmp/out"


def available() -> bool:
    return shutil.which("bwrap") is not None


def package_dir() -> str:
    """The directory that holds the dai_pdf package (so the helper imports the same code)."""
    return str(Path(__file__).resolve().parents[1])


def _common(extra: list[str], mounts: list[str]) -> list[str]:
    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind-try", "/etc/fonts", "/etc/fonts",
        "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        *extra,
        *mounts,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "QT_QPA_PLATFORM", "offscreen",
        "--setenv", "XDG_RUNTIME_DIR", "/tmp",
        "--setenv", "LANG", "C.UTF-8",
        "--",
        "prlimit", f"--data={MEMORY}", f"--cpu={CPU_SECONDS}", "--nofile=256", "--",
    ]


def _extra(binds: tuple[str, ...]) -> list[str]:
    return [arg for path in (package_dir(), *binds) for arg in ("--ro-bind", path, path)]


def argv(pdf_path: str, python: str = "/usr/bin/python3", binds: tuple[str, ...] = ()) -> list[str]:
    """The sandboxed helper's command line. `python` and `binds` (read-only) are for tests with another
    Python; D.Ai uses Debian's, already under /usr."""
    return _common(_extra(binds), ["--ro-bind", pdf_path, "/tmp/document.pdf"]) + \
        [python, "-I", "-c", BOOT, package_dir(), "/tmp/document.pdf"]


def edit_argv(inputs: list[str], out_dir: str, python: str = "/usr/bin/python3", binds: tuple[str, ...] = ()) -> list[str]:
    """The sandboxed editor's command line: every input read-only under /tmp/in, the output folder writable as
    /tmp/out (an empty folder the window made), nothing else of the person's files."""
    mounts = [arg for i, path in enumerate(inputs) for arg in ("--ro-bind", path, f"{IN_DIR}/{i}.pdf")]
    mounts += ["--bind", out_dir, OUT_DIR]
    return _common(_extra(binds), mounts) + [python, "-I", "-c", BOOT_EDIT, package_dir(), IN_DIR, OUT_DIR, str(len(inputs))]


def direct_argv(pdf_path: str, python: str = "/usr/bin/python3") -> list[str]:
    """The helper without the sandbox: only for tests, never used by the window."""
    return [python, "-I", "-c", BOOT, package_dir(), pdf_path]


def direct_edit_argv(inputs: list[str], out_dir: str, python: str = "/usr/bin/python3") -> list[str]:
    """The editor without the sandbox: only for tests. The inputs are read from where they are."""
    return [python, "-I", "-c", BOOT_EDIT, package_dir(), "", out_dir, str(len(inputs)), *inputs]
