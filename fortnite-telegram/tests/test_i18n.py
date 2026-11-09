import os
import string
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import i18n

def test_every_game_language_has_a_window_language():
    assert set(config.LANGS) == set(i18n.LANG_CODES) == set(i18n.UI) == set(i18n.GUIDE)

def test_all_languages_define_the_same_ui_keys():
    keys = set(i18n.UI["en"])
    for lang in i18n.LANG_CODES:
        assert set(i18n.UI[lang]) == keys, lang
        assert all(i18n.UI[lang][k].strip() for k in keys), lang

def test_ui_texts_keep_their_format_placeholders():
    for key, en in i18n.UI["en"].items():
        names = {f for _, f, _, _ in string.Formatter().parse(en) if f}
        for lang in i18n.LANG_CODES:
            assert {f for _, f, _, _ in string.Formatter().parse(i18n.UI[lang][key]) if f} == names, (lang, key)

def test_every_mode_has_a_label_in_every_language():
    for lang in i18n.LANG_CODES:
        for code in config.MODES:
            assert i18n.t(lang, f"mode_{code}") != f"mode_{code}"

def test_guide_has_the_same_structure_in_every_language():
    ref = [kind for kind, _ in i18n.GUIDE["ja"]]
    for lang in i18n.LANG_CODES:
        assert [kind for kind, _ in i18n.GUIDE[lang]] == ref, lang
        assert all(text.strip() for _, text in i18n.GUIDE[lang]), lang
    assert {k for k in ref} == {"h1", "h2", "p", "n", "li"}

def test_guide_starts_with_troubleshooting_and_ends_with_contact():
    for lang in i18n.LANG_CODES:
        g = i18n.GUIDE[lang]
        assert g[0][0] == "h1" and [k for k, _ in g[1:6]] == ["n"] * 5, lang
        assert "@4z5pk" in g[-1][1], lang
        assert any("F8" in text for _, text in g), lang

def test_unknown_language_falls_back_to_english():
    assert i18n.t("xx", "start") == i18n.t("en", "start")
    assert i18n.guide("xx") is i18n.GUIDE["en"]
    assert i18n.norm("xx") == "en"
    assert i18n.t("en", "nonexistent-key") == "nonexistent-key"

def test_info_line_formats_in_every_language():
    for lang in i18n.LANG_CODES:
        s = i18n.t(lang, "info", state="IDLE", score=0.5, loops=3)
        assert "IDLE" in s and "0.50" in s and "3" in s
