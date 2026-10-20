# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The screen follows the tablet's orientation (docs/MOBILE.md A3).

iio-sensor-proxy reads the accelerometer and its `monitor-sensor` tool prints every change while it holds the
claim on the sensor; this module reads those lines and turns the screen with `wlr-randr --transform` (labwc maps
touch to the output, so fingers follow the picture). The person's choice lives in ~/.config/dai/rotate:

  auto      follow the sensor (the default)
  off       leave the screen as it is (rotation lock)
  normal | 90 | 180 | 270   a fixed orientation

Orientation names are iio-sensor-proxy's; transforms are wl_output's (counter-clockwise), as GNOME maps them:
left-up → 90, right-up → 270, bottom-up → 180 (requires a check on a real tablet: a vendor's sensor mount can be
off by 180°). Nothing here needs root, the network, or a daemon of its own beyond monitor-sensor.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Iterable

ORIENTATIONS = {"normal": "normal", "bottom-up": "180", "left-up": "90", "right-up": "270"}
TRANSFORMS = ("normal", "90", "180", "270")
MODES = ("auto", "off", *TRANSFORMS)
MODE_FILE = ".config/dai/rotate"
LINE = re.compile(r"(?:orientation changed: |Has accelerometer \(orientation: )([a-z-]+)")
Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def parse_line(line: str) -> str | None:
    """The orientation a monitor-sensor line reports, or None for every other line."""
    found = LINE.search(line)
    if not found:
        return None
    name = found.group(1)
    return name if name in ORIENTATIONS else None


def mode(home: Path | None = None) -> str:
    """The person's choice (auto when the file is missing or says something else)."""
    try:
        value = ((home or Path.home()) / MODE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return "auto"
    return value if value in MODES else "auto"


def set_mode(value: str, home: Path | None = None) -> Path:
    if value not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}")
    path = (home or Path.home()) / MODE_FILE
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def outputs(runner: Runner = run) -> list[str]:
    """The screens wlr-randr knows (their names start the unindented lines)."""
    result = runner(["wlr-randr"])
    if result.returncode != 0:
        return []
    return [line.split()[0] for line in result.stdout.splitlines() if line and not line[0].isspace()]


def current_transform(runner: Runner = run, output: str | None = None) -> str:
    result = runner(["wlr-randr"])
    name = None
    for line in result.stdout.splitlines():
        if line and not line[0].isspace():
            name = line.split()[0]
        elif "Transform:" in line and (output is None or name == output):
            return line.split(":", 1)[1].strip()
    return ""


def apply(transform: str, runner: Runner = run, output: str | None = None) -> bool:
    """Turn the screen (every screen, or the one named). False when wlr-randr failed or no screen is known."""
    if transform not in TRANSFORMS:
        raise ValueError("transform is normal, 90, 180 or 270")
    names = [output] if output else outputs(runner)
    ok = bool(names)
    for name in names:
        if runner(["wlr-randr", "--output", name, "--transform", transform]).returncode != 0:
            ok = False
    return ok


def wanted(orientation: str | None, choice: str) -> str | None:
    """What the screen should show for a sensor reading under the person's choice; None means leave it."""
    if choice == "off":
        return None
    if choice in TRANSFORMS:
        return choice
    return ORIENTATIONS.get(orientation or "", None)


def follow(lines: Iterable[str], runner: Runner = run, home: Path | None = None, output: str | None = None) -> list[str]:
    """Read monitor-sensor's lines until they end; turn the screen when the wanted transform changes. Returns
    the transforms applied, in order (for the tests and the status)."""
    applied: list[str] = []
    last_orientation: str | None = None
    last_applied: str | None = None
    for line in lines:
        orientation = parse_line(line)
        if orientation is not None:
            last_orientation = orientation
        elif "No accelerometer" in line or "vanished" in line:
            continue
        target = wanted(last_orientation, mode(home))
        if target is not None and target != last_applied and apply(target, runner, output):
            applied.append(target)
            last_applied = target
    return applied


def sensor_lines(monitor: str = "monitor-sensor") -> Iterable[str]:
    """monitor-sensor's output as it comes; it keeps the sensor claimed as long as it runs."""
    proc = subprocess.Popen([monitor], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    try:
        assert proc.stdout is not None
        yield from proc.stdout
    finally:
        proc.terminate()
