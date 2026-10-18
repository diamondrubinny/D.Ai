# D.Ai OS translations

- `dai-os.pot`: every interface text (English), with the Hebrew text as a note. Generated, do not edit:
  `PYTHONPATH=apps/dai-i18n python3 -m dai_i18n.tool extract`
- `po/<lang>.po`: one file per language (ar, ru, es, fr, de, pt). Hebrew lives in the code.

How to translate and test: [docs/I18N.md §7](../docs/I18N.md). Keep every `{placeholder}` exactly as it is;
a translation with different placeholders is ignored. Translations are reviewed by native speakers before a
language is marked stable.

© 2026 Diamond Rubinny (d.Ai) · Apache-2.0
