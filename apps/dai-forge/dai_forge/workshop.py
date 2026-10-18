# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The Workshop: build → test → repair (docs/EVOLVE.md §2).

Every app the local AI writes is started once in the sandbox before the user
sees it: no network, no home, no real display (Qt offscreen), DAI_SELF_TEST=1,
a few seconds at most. If it crashes, the error goes back to the AI with a
request to fix it, at most MAX_REPAIRS times. Without bubblewrap nothing is
run: the result is "skipped", never an unsandboxed run.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .ai import ChatFn, generate_app

MAX_REPAIRS = 2
TEST_SECONDS = 8
MAX_DETAIL = 2000

REPAIR_REQUEST = (
    "The app crashed when it was started. Fix the cause so that it starts without errors, and keep all of its "
    "features and texts. Error output:\n{detail}"
)


@dataclass(frozen=True)
class TestResult:
    status: str  # passed | failed | skipped
    detail: str = ""


def test_argv(work: Path, entry: str) -> list[str]:
    """Stricter than running the app: no display, no data folder, nothing shared."""
    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/etc", "/etc",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        "--dir", "/tmp/home",
        "--ro-bind", str(work), "/app",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop", "ALL",
        "--hostname", "dai-selftest",
        "--clearenv",
        "--setenv", "HOME", "/tmp/home",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "QT_QPA_PLATFORM", "offscreen",
        "--setenv", "DAI_SELF_TEST", "1",
        "--chdir", "/tmp/home",
        "--", "/usr/bin/python3", "-I", f"/app/{entry}",
    ]


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-20:])[-MAX_DETAIL:]


def _check_web(code: str) -> TestResult:
    parser = HTMLParser()
    try:
        parser.feed(code)
        parser.close()
    except Exception as exc:  # html.parser is lenient; anything raised is a real problem
        return TestResult("failed", f"HTML could not be read: {exc}")
    if "<html" not in code.lower():
        return TestResult("failed", "the page has no <html> element")
    return TestResult("passed", "the page is valid HTML")


def smoke_test(code: str, kind: str, run: Callable[..., Any] = subprocess.run,
               seconds: float = TEST_SECONDS) -> TestResult:
    if kind == "web":
        return _check_web(code)
    if not shutil.which("bwrap"):
        return TestResult("skipped", "bubblewrap is missing, so the app was not started (it never runs unsandboxed)")
    with tempfile.TemporaryDirectory(prefix="dai-workshop-") as tmp:
        work = Path(tmp)
        (work / "app.py").write_text(code, encoding="utf-8")
        try:
            result = run(test_argv(work, "app.py"), stdin=subprocess.DEVNULL, capture_output=True, text=True,
                         timeout=seconds, check=False)
        except subprocess.TimeoutExpired:
            return TestResult("passed", f"started and was still running after {seconds:g} s")
    error = result.stderr or ""
    if result.returncode == 0:
        return TestResult("passed", "started and finished without errors")
    if kind == "cli" and ("EOFError" in error or (result.returncode == 2 and "usage:" in error)):
        return TestResult("passed", "started and waited for input")
    if "Traceback" in error or result.returncode != 0:
        return TestResult("failed", _tail(error) or f"exit code {result.returncode}")
    return TestResult("passed", "")


@dataclass
class Built:
    result: dict[str, Any]
    test: TestResult
    repairs: int


def build(request: str, kind: str, existing: str | None = None, chat: ChatFn | None = None,
          progress: Callable[[str], None] | None = None, tester: Callable[[str, str], TestResult] = smoke_test,
          status: Callable[[str, int, TestResult], None] | None = None) -> Built:
    """Generate, test, and repair up to MAX_REPAIRS times. status(stage, repair, test) reports progress."""
    result = generate_app(request, kind, existing, chat=chat, progress=progress)
    if status:
        status("testing", 0, TestResult("skipped"))
    test = tester(result["code"], kind)
    repairs = 0
    while test.status == "failed" and repairs < MAX_REPAIRS:
        repairs += 1
        if status:
            status("repairing", repairs, test)
        fixed = generate_app(REPAIR_REQUEST.format(detail=test.detail), kind, result["code"], chat=chat,
                             progress=progress)
        result["code"] = fixed["code"]
        # Permissions may only shrink in a repair: a fix never gains network or documents access.
        result["network"] = result["network"] and fixed["network"]
        result["documents"] = result["documents"] and fixed["documents"]
        if status:
            status("testing", repairs, test)
        test = tester(result["code"], kind)
    return Built(result, test, repairs)
