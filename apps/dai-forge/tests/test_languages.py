# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
"""Forge in the six other languages (docs/I18N.md §10): recipes, removal, apps and schedules."""
import json
import re
import unittest
from pathlib import Path

from dai_forge import intent, recipes

BUILTIN = Path(__file__).resolve().parents[1] / "data" / "recipes"
# text → (kind, recipe id or "", systemd calendar or schedule kind or "")
SENTENCES = {
    "установи антивирус": ("recipe", "antivirus", ""), "удали телеграм": ("remove", "telegram", ""),
    "создай приложение для заметок": ("app", "", ""), "установи видеоплеер": ("recipe", "video-player", ""),
    "каждый день в 18:00 очищай загрузки": ("automation", "", "*-*-* 18:00:00"),
    "каждый понедельник в 9 напомни мне": ("automation", "", "Mon *-*-* 09:00:00"),
    "каждые 30 минут проверяй диск": ("automation", "", "minutes"),
    "instala un antivirus": ("recipe", "antivirus", ""), "elimina telegram": ("remove", "telegram", ""),
    "crea una aplicación de notas": ("app", "", ""), "instala un reproductor de video": ("recipe", "video-player", ""),
    "todos los días a las 8 limpia descargas": ("automation", "", "*-*-* 08:00:00"),
    "cada lunes a las 9 dime el espacio libre": ("automation", "", "Mon *-*-* 09:00:00"),
    "installe un antivirus": ("recipe", "antivirus", ""), "supprime telegram": ("remove", "telegram", ""),
    "crée une application pour mes notes": ("app", "", ""), "installe une imprimante": ("recipe", "printer", ""),
    "tous les jours à 8h nettoie les téléchargements": ("automation", "", "*-*-* 08:00:00"),
    "chaque lundi à 9 donne l'espace libre": ("automation", "", "Mon *-*-* 09:00:00"),
    "installiere einen Virenschutz": ("recipe", "antivirus", ""), "entferne telegram": ("remove", "telegram", ""),
    "erstelle eine App für Notizen": ("app", "", ""), "installiere einen Videoplayer": ("recipe", "video-player", ""),
    "jeden Tag um 8 Downloads aufräumen": ("automation", "", "*-*-* 08:00:00"),
    "jeden Montag um 9 freien Speicher melden": ("automation", "", "Mon *-*-* 09:00:00"),
    "alle 30 Minuten den Datenträger prüfen": ("automation", "", "minutes"),
    "instale um antivírus": ("recipe", "antivirus", ""), "remova o telegram": ("remove", "telegram", ""),
    "crie um aplicativo de notas": ("app", "", ""), "instale um reprodutor de vídeo": ("recipe", "video-player", ""),
    "todos os dias às 8 limpe os downloads": ("automation", "", "*-*-* 08:00:00"),
    "toda segunda às 9 diga o espaço livre": ("automation", "", "Mon *-*-* 09:00:00"),
    "ثبت مضاد فيروسات": ("recipe", "antivirus", ""), "احذف تيليجرام": ("remove", "telegram", ""),
    "أنشئ تطبيق للملاحظات": ("app", "", ""), "ثبت مشغل فيديو": ("recipe", "video-player", ""),
    "كل يوم الساعة 8 نظف التنزيلات": ("automation", "", "*-*-* 08:00:00"),
    "كل يوم اثنين الساعة 9 أخبرني بالمساحة": ("automation", "", "Mon *-*-* 09:00:00"),
    "كل 30 دقيقة افحص القرص": ("automation", "", "minutes"),
}


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = recipes.load_library({"builtin": BUILTIN})

    def test_every_sentence(self):
        for text, (kind, recipe, when) in SENTENCES.items():
            with self.subTest(text):
                found = intent.classify(text, self.library)
                self.assertEqual(found.kind, kind)
                self.assertEqual(found.recipe.id if found.recipe else "", recipe)
                schedule = found.schedule
                self.assertEqual("" if schedule is None else (schedule.calendar or schedule.kind), when)
                self.assertEqual(found.text, text)  # what Diamond and the person see stays as written

    def test_english_and_hebrew_do_not_change(self):
        for text, kind in (("install antivirus", "recipe"), ("+ תתקין אנטי וירוס", "recipe"),
                           ("build a todo app", "app"), ("כל יום ב־18:00 תנקה את ההורדות", "automation"),
                           ("remove telegram", "remove"), ("tag my photos every day at 9", "automation")):
            with self.subTest(text):
                self.assertEqual(intent.classify(text, self.library).kind, kind)

    def test_packs_are_data_in_the_expected_shape(self):
        packs = sorted(intent.LANG_DIR.glob("*.json"))
        self.assertEqual([p.stem for p in packs], ["ar", "de", "es", "fr", "pt", "ru"])
        for path in packs:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((data["format"], data["lang"]), (1, path.stem))
            for foreign, english in data["phrases"].items():
                self.assertRegex(english, r"^[a-z0-9 .:'-]+$", f"{path.name}: {foreign}")
                self.assertTrue(foreign.strip() and not re.search(r"[A-Z]", foreign), f"{path.name}: {foreign}")


if __name__ == "__main__":
    unittest.main()
