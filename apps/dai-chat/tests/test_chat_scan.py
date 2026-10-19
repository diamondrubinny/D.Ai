# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""The checks on received messages (dai_chat/scan.py): the signs of phishing in Hebrew and English, ClamAV
when installed, and no warning on ordinary messages."""
import subprocess
import unittest
from unittest import mock

from dai_chat import scan


class TextTests(unittest.TestCase):
    def test_signs_of_phishing(self):
        cases = {
            "Your PayPal account will be suspended: https://paypal-login.example.com/verify": {"lookalike", "asks"},
            "בנק לאומי: החשבון שלך ייחסם, היכנסו ל-https://leumi-secure.xyz/login": {"lookalike", "asks"},
            "שלחו לי את קוד האימות שקיבלתם ב-SMS": {"asks"},
            "look at this http://192.168.4.20/pics": {"ip_link", "plain_http"},
            "photos: https://bit.ly/3abcd": {"shortener"},
            "https://" + "pаypal.com".encode("idna").decode() + "/": {"punycode", "lookalike"},  # Cyrillic а
            "open the invoice, invoice_2026.exe": {"risky_file"},
            "harmless‮txt.exe": {"hidden_direction", "risky_file"},
            "זכית בפרס! כרטיס מתנה מחכה לך": {"asks"},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertTrue(expected <= set(scan.check_text(text)), scan.check_text(text))

    def test_ordinary_messages_are_quiet(self):
        for text in ("היי! מגיעה הערב?", "see you at six", "the recipe is on https://www.paypal.com/il/home",
                     "https://www.gov.il/he/departments", "קניתי 3 עגבניות ב-12.50", "meet at 10.30 near the park",
                     "👍", "מה קורה? שלחתי לך את הקובץ במייל"):
            with self.subTest(text=text):
                self.assertEqual(scan.check_text(text), [])

    def test_described_in_hebrew_and_english(self):
        self.assertIn("IP", scan.describe(["ip_link"], "en"))
        self.assertIn("קישור מקוצר", scan.describe(["shortener"], "he"))


class ClamTests(unittest.TestCase):
    def test_clamav_when_its_daemon_is_installed(self):
        found = subprocess.CompletedProcess([], 1, b"stream: Heuristics.Phishing FOUND", b"")
        with mock.patch("shutil.which", return_value="/usr/bin/clamdscan"):
            verdict = scan.check(1, b"hello", run=lambda *a, **k: found)
        self.assertTrue(verdict.malware and verdict.suspicious)
        self.assertEqual(verdict.reasons[0], "malware")
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(scan.check(1, b"hello", run=mock.Mock(side_effect=AssertionError)).suspicious)
        with mock.patch("shutil.which", return_value="/usr/bin/clamdscan"):
            stuck = mock.Mock(side_effect=subprocess.TimeoutExpired("clamdscan", 60))
            self.assertFalse(scan.check(1, b"hello", run=stuck).malware)  # no answer is not a verdict


if __name__ == "__main__":
    unittest.main()
