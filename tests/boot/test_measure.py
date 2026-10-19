# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""measure.py with a fake serial console: the JSON it writes, the desktop detection, and a failed login.
The real measurement runs in CI (boot-test.sh with MEASURE_JSON); these tests check the logic without a VM."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure  # noqa: E402


class FakeSerial:
    def __init__(self, sock, panel_after=3, login_fails=False):
        self.panel_after, self.login_fails = panel_after, login_fails
        self.panel_checks = 0
        self.sent = []

    def send(self, text):
        self.sent.append(text)

    def expect(self, pattern, timeout):
        return b"Login incorrect" if self.login_fails else b"dai@dai-os:~$ "

    def run(self, command, timeout=30):
        if "pgrep -x lxqt-panel" in command:
            self.panel_checks += 1
            return "PANEL_UP" if self.panel_checks >= self.panel_after else "PANEL_NO"
        if "/proc/meminfo" in command:
            return "MemTotal:        4000000 kB\nMemAvailable:    3000000 kB"
        if "loadavg" in command:
            return "0.52 0.40 0.31 1/300 4242"
        return ""


class Clock:
    """time.time() that moves only when measure.py sleeps; it starts at the login (measure.py runs after it)."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class MeasureTests(unittest.TestCase):
    def run_measure(self, serial, idle="5"):
        clock = Clock(1_000_042.0)  # the login, 42 s after QEMU started at 1_000_000
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "measure.json"
            argv = ["measure.py", "/unused.sock", "1000000", "1000042", str(out), "2048", "1", "tcg", idle]
            with mock.patch.object(measure, "Serial", return_value=serial), \
                    mock.patch.object(measure, "time", clock), \
                    mock.patch.object(sys, "argv", argv):
                code = measure.main()
            return code, json.loads(out.read_text()) if out.exists() else None

    def test_writes_the_numbers(self):
        code, data = self.run_measure(FakeSerial("x", panel_after=3))
        self.assertEqual(code, 0)
        self.assertEqual(data["memory_mb"], 2048)
        self.assertEqual(data["cpus"], 1)
        self.assertEqual(data["accel"], "tcg")
        self.assertEqual(data["login_s"], 42.0)  # the login came 42 s after QEMU started
        self.assertIsNotNone(data["desktop_s"])
        self.assertGreater(data["desktop_s"], data["login_s"])  # the desktop comes after the login
        self.assertEqual(data["memory_used_mb"], (4000000 - 3000000) // 1024)
        self.assertEqual(data["memory_total_mb"], 4000000 // 1024)
        self.assertEqual(data["load_1_5_15"], [0.52, 0.4, 0.31])
        self.assertEqual(data["idle_after_s"], 5)

    def test_no_desktop_is_reported_not_invented(self):
        serial = FakeSerial("x", panel_after=10**9)
        with mock.patch.object(measure, "DESKTOP_TIMEOUT", 30):
            code, data = self.run_measure(serial)
        self.assertEqual(code, 1)
        self.assertIsNone(data["desktop_s"])

    def test_a_failed_login_writes_nothing(self):
        code, data = self.run_measure(FakeSerial("x", login_fails=True))
        self.assertEqual(code, 1)
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
