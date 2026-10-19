# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""What a file wants (dai_pdf/findings.py): every kind of active content is counted, a plain file is clean."""
import tempfile
import unittest
from pathlib import Path

from . import fixtures

fixtures.need_libraries()

import pikepdf  # noqa: E402

from dai_pdf import findings  # noqa: E402


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def scan(self, path):
        with pikepdf.open(path) as pdf:
            return findings.scan(pdf)

    def test_a_plain_file_is_clean(self):
        found = self.scan(fixtures.plain(self.dir / "plain.pdf"))
        self.assertFalse(found.active())
        self.assertEqual((found.javascript, found.launch, found.remote, found.submit, found.links), (0, 0, 0, 0, 0))
        self.assertEqual(found.attachments, [])
        self.assertFalse(found.xfa)
        self.assertFalse(found.encrypted)

    def test_everything_active_is_counted_and_nothing_is_run(self):
        found = self.scan(fixtures.active(self.dir / "active.pdf"))
        self.assertTrue(found.active())
        self.assertEqual(found.javascript, 2)   # the document-level script and the annotation's
        self.assertEqual(found.launch, 1)       # the open action
        self.assertEqual(found.remote, 1)
        self.assertEqual(found.submit, 1)
        self.assertEqual(found.links, 1)
        self.assertEqual([a["name"] for a in found.attachments], ["evil.exe", "notes.txt"])
        self.assertEqual(found.attachments[0]["size"], len(b"MZ not really"))
        self.assertTrue(found.xfa)
        self.assertFalse(found.truncated)

    def test_a_locked_file_is_marked_encrypted(self):
        path = fixtures.locked(self.dir / "locked.pdf")
        with pikepdf.open(path, password="secret") as pdf:
            found = findings.scan(pdf)
        self.assertTrue(found.encrypted)
        self.assertFalse(found.active())  # encryption is a fact about the file, not something it does

    def test_round_trip_through_json(self):
        found = self.scan(fixtures.active(self.dir / "active.pdf"))
        again = findings.Findings.from_dict({**found.to_dict(), "unknown_key": 1})
        self.assertEqual(again, found)

    def test_a_next_chain_of_actions_is_followed_but_not_run(self):
        pdf = pikepdf.new()
        pdf.pages.append(pikepdf.Page(pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, 100, 100])))
        pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://a",
                                                 Next=pikepdf.Dictionary(S=pikepdf.Name.Launch, F="x"))
        found = findings.scan(pdf)
        self.assertEqual((found.links, found.launch), (1, 1))


if __name__ == "__main__":
    unittest.main()
