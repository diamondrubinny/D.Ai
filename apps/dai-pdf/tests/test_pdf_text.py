# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Hebrew made readable (dai_pdf/text.py): mirrored lines are put right, correct lines and other languages are
left alone, and the search finds every hit."""
import unittest

from dai_pdf import text


class HebrewTests(unittest.TestCase):
    def test_a_mirrored_line_is_recognised_and_put_right(self):
        mirrored = "םולש"  # "שלום" stored as drawn, right to left
        self.assertTrue(text.is_mirrored(mirrored))
        self.assertEqual(text.unmirror_line(mirrored), "שלום")

    def test_a_correct_line_is_left_alone(self):
        line = "שלום לכולם, זה מסמך של ישראל"
        self.assertFalse(text.is_mirrored(line))
        self.assertEqual(text.readable(line), line)

    def test_runs_and_their_order(self):
        # "תודה רבה" drawn right to left and extracted visually: runs reversed, and in reverse order.
        mirrored = "הבר הדות"
        self.assertEqual(text.readable(mirrored), "תודה רבה")

    def test_final_letters_decide(self):
        self.assertTrue(text.is_mirrored("ןוכנ"))      # final nun at the start: mirrored
        self.assertFalse(text.is_mirrored("נכון"))

    def test_mixed_lines_and_other_languages(self):
        self.assertEqual(text.readable("Hello world"), "Hello world")
        self.assertEqual(text.readable("Total: 42"), "Total: 42")
        doc = "English line\nםולש\nlast line"
        self.assertEqual(text.readable(doc), "English line\nשלום\nlast line")

    def test_find_all_is_case_insensitive_and_complete(self):
        self.assertEqual(text.find_all("D.Ai and d.ai and D.AI", "d.ai"), [0, 9, 18])
        self.assertEqual(text.find_all("שלום שלום", "שלום"), [0, 5])
        self.assertEqual(text.find_all("anything", ""), [])


if __name__ == "__main__":
    unittest.main()
