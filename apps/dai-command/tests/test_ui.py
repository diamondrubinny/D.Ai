# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The command window passes Raz's accessibility audit (docs/RAZ.md §13)."""
import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from dai_command import ui
except ImportError:  # PyQt6 is not installed on every developer machine
    ui = None


@unittest.skipIf(ui is None, "PyQt6 is not installed")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_control_is_accessible(self):
        from dai_raz.a11y import assert_accessible
        for lang in ("he_IL.UTF-8", "en_US.UTF-8"):
            with mock.patch.dict(os.environ, {"LANG": lang}), mock.patch.object(ui, "load_apps", return_value=[]):
                window = ui.CommandWindow()
            self.addCleanup(window.close)
            assert_accessible(self, window)


if __name__ == "__main__":
    unittest.main()
