# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Diamond Rubinny (d.Ai)
import ast
import gettext
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dai_i18n as i18n
from dai_i18n import catalog, tool

REPO = Path(__file__).resolve().parents[3]

RU_PO = '''# test catalog
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Nothing to fix"
msgstr "Нечего исправлять"

msgid "Saved: {saved}"
msgstr "Сохранено: {saved}"

msgid "Line one\\n"
"line two"
msgstr "Строка один\\n"
"строка два"

#, fuzzy
msgid "Fuzzy text"
msgstr "Не использовать"

msgid "Broken {name}"
msgstr "Сломано {other.__class__}"

msgid "Untranslated"
msgstr ""
'''


class Languages(unittest.TestCase):
    def test_normalize(self):
        cases = {"he_IL.UTF-8": "he", "en_US.UTF-8": "en", "pt_BR.UTF-8": "pt", "ar_EG": "ar", "ru_RU.UTF-8@x": "ru",
                 "C.UTF-8": "en", "POSIX": "en", "ja_JP.UTF-8": "en", "iw_IL": "en", "de-DE": "de"}
        for value, code in cases.items():
            self.assertEqual(i18n.normalize(value), code, value)

    def test_ui_lang_reads_the_same_variables_in_the_same_order(self):
        self.assertEqual(i18n.ui_lang({"LC_ALL": "ru_RU.UTF-8", "LANG": "he_IL.UTF-8"}), "ru")
        self.assertEqual(i18n.ui_lang({"LC_ALL": "", "LC_MESSAGES": "he_IL.UTF-8", "LANG": "en_US.UTF-8"}), "he")
        self.assertEqual(i18n.ui_lang({}), "en")

    def test_rtl_and_names(self):
        self.assertTrue(i18n.is_rtl("he") and i18n.is_rtl("ar"))
        self.assertFalse(i18n.is_rtl("ru") or i18n.is_rtl("en"))
        self.assertEqual(i18n.embed("ok", "ar"), "‫ok‬")
        self.assertEqual(i18n.embed("ok", "fr"), "ok")
        self.assertEqual(i18n.english_name("ar"), "Arabic")
        self.assertEqual(i18n.english_name("xx"), "English")

    def test_hebrew_and_english_never_touch_a_catalog(self):
        with mock.patch.object(i18n, "_catalog", side_effect=AssertionError("no catalog for he/en")):
            self.assertEqual(i18n.pick("he", "Hi", "שלום"), "שלום")
            self.assertEqual(i18n.pick("en", "Hi", "שלום"), "Hi")
            self.assertEqual(i18n.text("he", "Hi {n}", "שלום {n}", n=3), "שלום 3")

    def test_without_a_catalog_other_languages_get_english(self):
        with mock.patch.dict("os.environ", {"DAI_LOCALEDIR": "/nonexistent"}), mock.patch("os.geteuid", return_value=1000):
            i18n._catalog.cache_clear()
            self.assertEqual(i18n.pick("ru", "Nothing to fix", "אין מה לתקן"), "Nothing to fix")


class WithCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        target = Path(self.tmp.name) / "ru" / "LC_MESSAGES" / "dai-os.mo"
        target.parent.mkdir(parents=True)
        target.write_bytes(catalog.write_mo(catalog.parse_po(RU_PO), "ru"))
        for patcher in (mock.patch.dict("os.environ", {"DAI_LOCALEDIR": self.tmp.name}),
                        mock.patch("os.geteuid", return_value=1000)):  # the override is ignored for root
            patcher.start()
            self.addCleanup(patcher.stop)
        i18n._catalog.cache_clear()
        self.addCleanup(i18n._catalog.cache_clear)

    def test_po_is_read_like_msgfmt(self):
        messages = catalog.parse_po(RU_PO)
        self.assertEqual(messages["Line one\nline two"], "Строка один\nстрока два")
        self.assertNotIn("Fuzzy text", messages)
        self.assertNotIn("Untranslated", messages)
        self.assertNotIn("", messages)

    def test_the_mo_file_is_read_by_python_gettext(self):
        translation = gettext.translation("dai-os", self.tmp.name, languages=["ru"])
        self.assertEqual(translation.gettext("Nothing to fix"), "Нечего исправлять")

    def test_translated(self):
        self.assertEqual(i18n.pick("ru", "Nothing to fix", "אין מה לתקן"), "Нечего исправлять")
        self.assertEqual(i18n.text("ru", "Saved: {saved}", "נשמר: {saved}", saved="/tmp/x"), "Сохранено: /tmp/x")
        self.assertEqual(i18n.pick("ru", "Not in the catalog", "לא קיים"), "Not in the catalog")
        self.assertEqual(i18n.pick("de", "Nothing to fix", "אין מה לתקן"), "Nothing to fix")

    def test_a_translation_with_other_placeholders_is_never_used(self):
        class Secret:
            token = "s3cret"

        self.assertEqual(i18n.text("ru", "Broken {name}", "שבור {name}", name=Secret()).startswith("Broken "), True)
        self.assertEqual(catalog.problems({"Broken {name}": "Сломано {other.__class__}"}, {"Broken {name}"}),
                         ["placeholders differ from the English text: 'Broken {name}'"])

    def test_root_ignores_the_override(self):
        with mock.patch("os.geteuid", return_value=0):
            self.assertEqual(i18n.localedir(), i18n.SYSTEM_LOCALEDIR)

    def test_an_app_speaks_russian(self):
        """D.Ai Heal's strings, end to end, through the catalog."""
        po = RU_PO + '\nmsgid "No problems noticed."\nmsgstr "Проблем не найдено."\n'
        target = Path(self.tmp.name) / "ru" / "LC_MESSAGES" / "dai-os.mo"
        target.write_bytes(catalog.write_mo(catalog.parse_po(po), "ru"))
        i18n._catalog.cache_clear()
        try:
            from dai_heal.text import STRINGS, t
        except ImportError:
            self.skipTest("dai_heal is not on PYTHONPATH")
        self.assertEqual(t("status_none", "ru"), "Проблем не найдено.")
        self.assertEqual(t("status_none", "he"), STRINGS["status_none"][1])
        self.assertEqual(t("status_none", "en"), "No problems noticed.")


class Extraction(unittest.TestCase):
    SOURCE = '''
STRINGS = {"a": ("Hello {name}", "שלום {name}"), "b": ("Same", "Same"), "c": [("List item", "פריט")]}
ICONS = {"he": [("🛡", "אנטי וירוס")]}
x = _l(lang, "Called", "נקרא")
y = "עברית" if lang == "he" else "Inline"
z = "Reversed" if lang == "en" else "הפוך"
w = "סגור פורט 22" if lang == "he" else "close port 22"  # i18n: command
v = _l(lang, f"Formatted {n}", f"מעוצב {n}")
PARSER = [("il", r"(?:hebrew|עברית)")]
'''

    def test_pairs(self):
        found = {en: he for en, he, _ in catalog.pairs_in_source(self.SOURCE, "x.py")}
        self.assertEqual(found, {"Hello {name}": "שלום {name}", "List item": "פריט", "Called": "נקרא",
                                 "Inline": "עברית", "Reversed": "הפוך"})

    def test_pot(self):
        entries = [catalog.Entry("Hello {name}", "שלום {name}", ["x.py:2"]), catalog.Entry('Say "hi"\n', "אמור", ["x.py:3"])]
        pot = catalog.render_pot(entries)
        self.assertIn("#. he: שלום {name}\n#: x.py:2\n#, python-brace-format\nmsgid \"Hello {name}\"", pot)
        self.assertIn('msgid "Say \\"hi\\"\\n"', pot)
        self.assertEqual(set(catalog.parse_po(pot.replace('msgstr ""\n\n#. he: אמור', 'msgstr "X"\n\n#. he: אמור'))),
                         {"Hello {name}"})

    def test_the_committed_pot_is_up_to_date(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            code = tool.main(["tool", "extract", "--check"])
        self.assertEqual(code, 0, err.getvalue())


class Routing(unittest.TestCase):
    """Every app text goes through dai_i18n; a raw language test must say why it is there."""

    def test_no_raw_hebrew_branches(self):
        offenders = []
        for path in sorted((REPO / "apps").glob("*/dai_*/*.py")):
            if path.parent.name == "dai_i18n":
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, 1):
                if re.search(r"""\b(lang|language|self\.lang|self\.language)\s*==\s*["'](he|en)["']""", line) \
                        and "i18n:" not in line:
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "use dai_i18n.pick/text/is_rtl, or mark the line '# i18n: command' / '# i18n: ok (why)'")

    def test_no_language_function_of_its_own(self):
        offenders = []
        for path in sorted((REPO / "apps").glob("*/dai_*/*.py")):
            if path.parent.name == "dai_i18n":
                continue
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Constant) and node.value == "LC_MESSAGES" and "i18n:" not in lines[node.lineno - 1]:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
        self.assertEqual(offenders, [], "read the language with dai_i18n.ui_lang()")


class KeywordPackTests(unittest.TestCase):
    def test_longest_phrase_whole_words_and_only_safe_english(self):
        import json
        import tempfile
        from pathlib import Path

        from dai_i18n import keywords

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "ru.json").write_text(json.dumps({"format": 1, "lang": "ru", "phrases": {
                "каждый": "every", "каждый день": "every day", "день": "day", "злой": "x; rm -rf /",
                "плохой": "<b>", "Фото": "photos"}}), encoding="utf-8")
            (folder / "xx.json").write_text("{not json", encoding="utf-8")
            (folder / "yy.json").write_text(json.dumps({"format": 2, "phrases": {"a": "b"}}), encoding="utf-8")
            self.assertEqual(keywords.translate("каждый день", folder), "every day")
            self.assertEqual(keywords.translate("каждыйдень злой плохой", folder), "каждыйдень злой плохой")
            self.assertEqual(keywords.translate(keywords.normalize("ФОТО  со  вчера"), folder), "photos со вчера")
            self.assertEqual(len(keywords.load(str(folder))), 4)  # the unsafe ones and the broken files are skipped


if __name__ == "__main__":
    unittest.main()
