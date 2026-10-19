# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Diamond Chat from D.Ai Command (dai_chat/quick.py and the command bar's "chat" action):
"send Dana: …" and "שלח לדנה: …" queue a message for a contact, and nothing else does."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if importlib.util.find_spec("nacl") is None:  # python3-nacl, in Debian
    raise unittest.SkipTest("PyNaCl is missing")

from dai_chat import keys, quick, store

COMMAND = Path(__file__).resolve().parents[2] / "dai-command"


class ParseTests(unittest.TestCase):
    def test_what_is_a_send(self):
        self.assertEqual(quick.parse("send Dana: see you at six"), (["Dana"], "see you at six"))
        self.assertEqual(quick.parse("Message to Noa Levi: hi: there"), (["Noa Levi"], "hi: there"))
        self.assertEqual(quick.parse("שלח לדנה: מגיעה בשש"), (["דנה", "לדנה"], "מגיעה בשש"))
        self.assertEqual(quick.parse("שלחי הודעה ללאה: היי"), (["לאה", "ללאה"], "היי"))
        self.assertEqual(quick.parse("כתוב אל דנה: בדרך"), (["דנה"], "בדרך"))

    def test_what_is_not(self):
        for text in ("send the report to Dana", "send Dana:", "send: hi", "find the pdf: last week", "שלח מייל",
                     "dana: hi"):
            self.assertIsNone(quick.parse(text), text)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "chat"
        self.dana = keys.Identity.generate().public
        self.leah = keys.Identity.generate().public
        db = store.Store(self.folder)
        db.add_contact(store.Contact(self.dana, "דנה"))
        db.add_contact(store.Contact(self.leah, "לאה"))
        db.close()

    def test_find_and_queue(self):
        self.assertEqual(quick.find_contact(["דנה", "לדנה"], self.folder).public, self.dana)
        self.assertEqual(quick.find_contact(["אה", "לאה"], self.folder).public, self.leah)  # a name with ל
        self.assertIsNone(quick.find_contact(["Mallory"], self.folder))
        with mock.patch("dai_chat.service.poke", return_value=None):
            self.assertFalse(quick.send_text(self.dana, "מגיעה בשש", self.folder))  # off: it waits
        db = store.Store(self.folder)
        self.assertEqual(db.conversation(self.dana)[0]["text"], "מגיעה בשש")
        self.assertEqual(len(db.queued(self.dana)), 1)
        db.set_blocked(self.dana)
        db.close()
        self.assertIsNone(quick.find_contact(["דנה"], self.folder))  # nothing to someone blocked

    def test_nothing_is_created_when_chat_was_never_used(self):
        empty = Path(self.tmp.name) / "never"
        self.assertIsNone(quick.find_contact(["Dana"], empty))
        self.assertFalse(empty.exists())

    def test_the_command_bar(self):
        if str(COMMAND) not in sys.path:
            sys.path.insert(0, str(COMMAND))
        try:
            from dai_command import core
        except ImportError as exc:
            self.skipTest(f"D.Ai Command is not importable here: {exc}")
        actions = core.chat_actions("שלח לדנה: מגיעה בשש", self.folder)
        self.assertEqual([a.kind for a in actions], ["chat"])
        self.assertEqual(actions[0].payload, (self.dana, "מגיעה בשש"))
        self.assertIn("דנה", actions[0].title)
        self.assertIsNone(core.chat_actions("send Mallory: hi", self.folder))  # not a contact: other meanings
        self.assertIsNone(core.chat_actions("calculate 2+2", self.folder))


if __name__ == "__main__":
    unittest.main()
