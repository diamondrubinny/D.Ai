# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from dai_find import cli, query, search as search_mod
from dai_find.query import is_find_request, parse
from dai_find.search import search, user_dirs

NOW = datetime(2026, 10, 16, 15, 0)  # a Friday


class ParseTests(unittest.TestCase):
    def test_english(self):
        q = parse("find the pdf I downloaded last week", NOW)
        self.assertEqual((q.kinds, q.folders, q.words), ({"pdf"}, ["downloads"], []))
        self.assertEqual((q.since, q.until), (datetime(2026, 10, 5), datetime(2026, 10, 12)))  # Monday weeks

    def test_hebrew_week_starts_on_sunday(self):
        q = parse("מצא את ה-PDF שהורדתי בשבוע שעבר", NOW)
        self.assertEqual((q.kinds, q.folders, q.words), ({"pdf"}, ["downloads"], []))
        self.assertEqual((q.since, q.until), (datetime(2026, 10, 4), datetime(2026, 10, 11)))

    def test_hebrew_prefixes_kinds_and_times(self):
        q = parse("התמונות מאתמול", NOW)
        self.assertEqual((q.kinds, q.since, q.until), ({"image"}, datetime(2026, 10, 15), datetime(2026, 10, 16)))
        q = parse("חפש מצגת על תקציב מהחודש שעבר", NOW)
        self.assertEqual((q.kinds, q.words, q.since), ({"presentation"}, ["תקציב"], datetime(2026, 9, 1)))
        q = parse("תמצא צילומי מסך מהיום", NOW)
        self.assertEqual((q.kinds, q.since, q.until), ({"image"}, datetime(2026, 10, 16), None))
        q = parse("איפה השירים מ־3 הימים האחרונים", NOW)
        self.assertEqual((q.kinds, q.since), ({"audio"}, datetime(2026, 10, 14)))

    def test_month_names_are_never_in_the_future(self):
        self.assertEqual(parse("where is my invoice from March", NOW).since, datetime(2026, 3, 1))
        q = parse("find photos from december", NOW)
        self.assertEqual((q.since, q.until), (datetime(2025, 12, 1), datetime(2026, 1, 1)))
        self.assertEqual(parse("חפש חשבונית ממרץ", NOW).words, ["חשבונית"])
        self.assertEqual(parse("חפש חשבונית ממרץ", NOW).since, datetime(2026, 3, 1))

    def test_other_windows(self):
        self.assertEqual(parse("find files from 2 days ago", NOW).since, datetime(2026, 10, 14))
        self.assertEqual(parse("find files from 2 days ago", NOW).until, datetime(2026, 10, 15))
        self.assertEqual(parse("find documents from last year", NOW).since, datetime(2025, 1, 1))
        jan = datetime(2026, 1, 10)
        self.assertEqual(parse("find pdf from last month", jan).since, datetime(2025, 12, 1))

    def test_trigger_words(self):
        for text in ("find x", "search for x", "where is x", "show me x", "מצא x", "חפש x", "איפה x", "תראה לי x"):
            self.assertTrue(is_find_request(text), text)
        for text in ("firefox", "2+2", "!block usb", "findings"):
            self.assertFalse(is_find_request(text), text)

    def test_unspecific(self):
        self.assertFalse(parse("find", NOW).specific)
        self.assertFalse(parse("מצא את הקובץ שלי", NOW).specific)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        (self.home / ".config").mkdir()
        (self.home / ".config" / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/הורדות"\n')
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()
        search_mod._CACHE.clear()

    def make(self, rel: str, days_ago: float, size: int = 10) -> Path:
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        stamp = self.now - days_ago * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_kind_time_folder_and_name(self):
        recent = self.make("הורדות/invoice-march.pdf", 1)
        self.make("הורדות/old.pdf", 40)
        self.make("Documents/invoice-copy.pdf", 1)
        self.make("הורדות/photo.jpg", 1)
        query = parse("find the pdf I downloaded in the last 3 days")
        self.assertEqual([h.path for h in search(query, self.home)], [recent])
        everywhere = parse("find invoice pdf")
        self.assertEqual(len(search(everywhere, self.home)), 2)

    def test_newest_first_and_limit(self):
        paths = [self.make(f"Pictures/p{i}.png", i) for i in range(5)]
        hits = search(parse("find images"), self.home, limit=3)
        self.assertEqual([h.path for h in hits], paths[:3])

    def test_skips_hidden_vendor_and_symlinks(self):
        self.make(".ssh/id_backup.pdf", 1)
        self.make("project/node_modules/doc.pdf", 1)
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "secret.pdf").write_text("x")
        (self.home / "link").symlink_to(outside.name)
        self.assertEqual(search(parse("find pdf"), self.home), [])

    def test_unspecific_returns_nothing(self):
        self.make("a.txt", 0)
        self.assertEqual(search(parse("find"), self.home), [])

    def test_xdg_and_fallback_dirs(self):
        (self.home / "Desktop").mkdir()
        dirs = user_dirs(self.home)
        self.assertEqual(dirs["downloads"], self.home / "הורדות")
        self.assertEqual(dirs["desktop"], self.home / "Desktop")

    def test_cache_is_memory_only_and_expires(self):
        self.make("a.pdf", 0)
        query = parse("find pdf")
        self.assertEqual(len(search(query, self.home, ttl=30)), 1)
        self.make("b.pdf", 0)
        self.assertEqual(len(search(query, self.home, ttl=30)), 1)  # cached listing
        self.assertEqual(len(search(query, self.home, ttl=0)), 2)   # fresh walk
        self.assertFalse(any(p.name.startswith(".dai") for p in self.home.rglob("*")))

    def test_cli_json(self):
        self.make("הורדות/report.pdf", 0)
        out = io.StringIO()
        with mock.patch.object(Path, "home", return_value=self.home), redirect_stdout(out), \
                mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            code = cli.main(["dai-find", "--json", "find the pdf I downloaded today"])
        data = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(data["query"]["kinds"], ["pdf"])
        self.assertTrue(data["results"][0]["path"].endswith("report.pdf"))


class CommandTests(unittest.TestCase):
    def test_command_bar_rows(self):
        try:
            from dai_command.core import build_actions, find_actions
        except ImportError:
            self.skipTest("dai_command not on the path")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            target = home / "Downloads" / "ticket.pdf"
            target.parent.mkdir()
            target.write_text("x")
            with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
                rows = find_actions("find the pdf I downloaded today", home)
                self.assertEqual((rows[0].kind, rows[0].title, rows[0].payload), ("file", "ticket.pdf", str(target)))
                self.assertIn("~/Downloads", rows[0].subtitle)
                self.assertIsNone(find_actions("firefox", home))
                hint = find_actions("find", home)
                self.assertIsNone(hint[0].payload)
                self.assertTrue(build_actions("find something", []))
        search_mod._CACHE.clear()


class LanguageTests(unittest.TestCase):
    """Find in the six other languages (docs/I18N.md §10)."""
    NOW = datetime(2026, 10, 18, 12, 0)
    SENTENCES = {
        "найди фото со вчера": ({"image"}, "yesterday", []),
        "где мой pdf, который я скачал на прошлой неделе": ({"pdf"}, "last_week", ["downloads"]),
        "покажи документы в загрузках за последние 3 дня": ({"document"}, "last_n_days", ["downloads"]),
        "busca las fotos de ayer": ({"image"}, "yesterday", []),
        "dónde está el pdf que descargué la semana pasada": ({"pdf"}, "last_week", ["downloads"]),
        "muéstrame documentos de hace 3 días": ({"document"}, "days_ago", []),
        "trouve les photos d'hier": ({"image"}, "yesterday", []),
        "cherche les documents des 3 derniers jours": ({"document"}, "last_n_days", []),
        "trouve les vidéos de mars": ({"video"}, "month:3", []),
        "finde die Fotos von gestern": ({"image"}, "yesterday", []),
        "wo ist das PDF, das ich letzte Woche heruntergeladen habe": ({"pdf"}, "last_week", ["downloads"]),
        "suche Dokumente von vor 3 Tagen": ({"document"}, "days_ago", []),
        "encontre as fotos de ontem": ({"image"}, "yesterday", []),
        "onde está o pdf que baixei semana passada": ({"pdf"}, "last_week", ["downloads"]),
        "procure documentos de 3 dias atrás": ({"document"}, "days_ago", []),
        "ابحث عن الصور من أمس": ({"image"}, "yesterday", []),
        "أين ملف pdf الذي نزلتها الأسبوع الماضي": ({"pdf"}, "last_week", ["downloads"]),
        "ابحث عن المستندات منذ 3 أيام": ({"document"}, "days_ago", []),
    }

    def test_every_sentence(self):
        for text, (kinds, label, folders) in self.SENTENCES.items():
            with self.subTest(text):
                self.assertTrue(query.is_find_request(text))
                found = query.parse(text, self.NOW)
                self.assertEqual((found.kinds, found.time_label, found.folders, found.words), (kinds, label, folders, []))
                self.assertEqual(found.text, text)

    def test_names_stay_and_english_is_not_translated(self):
        self.assertEqual(query.parse("найди отчет 2025", self.NOW).words, ["отчет", "2025"])
        found = query.parse("find mars rover photos", self.NOW)  # "mars" is French for March, not here
        self.assertEqual((found.kinds, found.words, found.time_label), ({"image"}, ["mars", "rover"], ""))
        self.assertFalse(query.is_find_request("заблокируй флешки"))


if __name__ == "__main__":
    unittest.main()
