# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Copyright notices, license and trademark files stay in place (TRADEMARKS.md, docs/legal/TERMS.md)."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTICE = "Copyright (c) 2026 Diamond Rubinny (d.Ai)"
# Source files that can hold a comment; JSON and binary assets are covered by NOTICE.
SOURCE = re.compile(r"\.(?:py|sh|cpp|h|css|html|desktop|service|timer|path|policy|rules|conf|xml|qml|svg)$|"
                    r"(?:^|/)apps/[^/]+/data/[a-z0-9-]+$|/labwc/autostart$|\.hook\.chroot$")


# Third-party files bundled verbatim keep their own license and notices (listed in NOTICE), never ours.
THIRD_PARTY = ("build/live-build/editions/tv/includes.chroot_after_packages/etc/skel/.kodi/addons/",)


def tracked() -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


class LegalTests(unittest.TestCase):
    def test_every_source_file_keeps_the_notice(self):
        missing = [f for f in tracked() if SOURCE.search(f) and (ROOT / f).is_file() and not f.startswith(THIRD_PARTY)
                   and NOTICE not in (ROOT / f).read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(missing, [], "add the SPDX line and the copyright notice to these files")

    def test_python_and_shell_say_which_license(self):
        missing = [f for f in tracked() if f.endswith((".py", ".sh")) and (ROOT / f).is_file()
                   and "SPDX-License-Identifier: Apache-2.0" not in (ROOT / f).read_text(encoding="utf-8")]
        self.assertEqual(missing, [])

    def test_license_notice_trademarks_terms(self):
        self.assertIn("Apache License", (ROOT / "LICENSE").read_text()[:200])
        self.assertIn(NOTICE, (ROOT / "NOTICE").read_text())
        trademarks = (ROOT / "TRADEMARKS.md").read_text()
        self.assertIn("section 6", trademarks)
        self.assertIn("Diamond Rubinny (d.Ai)", trademarks)
        terms = (ROOT / "docs/legal/TERMS.md").read_text()
        self.assertIn("טיוטה", terms)  # stays marked as a draft until a lawyer has reviewed it

    def test_site_footers(self):
        for page in sorted((ROOT / "site").glob("*.html")):
            with self.subTest(page=page.name):
                html = page.read_text()
                self.assertIn("© 2026 Diamond Rubinny (d.Ai)", html)
                self.assertIn('href="terms.html"', html)


if __name__ == "__main__":
    unittest.main()
