import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config

def freeze(monkeypatch, exe_dir, bundle_dir):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "pk-auto.exe"))

def test_uses_bundled_template_when_no_external_folder(tmp_path, monkeypatch):
    exe_dir, bundle = tmp_path / "app", tmp_path / "bundle"
    (bundle / "assets_default").mkdir(parents=True)
    exe_dir.mkdir()
    (bundle / "assets_default" / "play_btn.png").write_bytes(b"x")
    freeze(monkeypatch, exe_dir, bundle)
    assert config.template_path("play") == str(bundle / "assets_default" / "play_btn.png")

def test_external_template_overrides_bundled(tmp_path, monkeypatch):
    exe_dir, bundle = tmp_path / "app", tmp_path / "bundle"
    (bundle / "assets_default").mkdir(parents=True)
    (exe_dir / "assets").mkdir(parents=True)
    (bundle / "assets_default" / "play_btn.png").write_bytes(b"bundled")
    (exe_dir / "assets" / "play_btn.png").write_bytes(b"mine")
    freeze(monkeypatch, exe_dir, bundle)
    assert config.template_path("play") == str(exe_dir / "assets" / "play_btn.png")

def test_cropper_always_saves_next_to_exe(tmp_path, monkeypatch):
    exe_dir, bundle = tmp_path / "app", tmp_path / "bundle"
    (bundle / "assets_default").mkdir(parents=True)
    exe_dir.mkdir()
    (bundle / "assets_default" / "play_btn.png").write_bytes(b"x")
    freeze(monkeypatch, exe_dir, bundle)
    assert config.external_template_path("play") == str(exe_dir / "assets" / "play_btn.png")

def test_template_filename_per_language():
    assert config.template_filename("play", "ja") == "play_btn.png"
    assert config.template_filename("play", "en") == "play_btn_en.png"
    assert config.template_filename("return_lobby", "en") == "return_lobby_btn_en.png"

def test_language_specific_external_override(tmp_path, monkeypatch):
    exe_dir, bundle = tmp_path / "app", tmp_path / "bundle"
    (bundle / "assets_default").mkdir(parents=True)
    (exe_dir / "assets").mkdir(parents=True)
    (bundle / "assets_default" / "play_btn_en.png").write_bytes(b"bundled-en")
    (exe_dir / "assets" / "play_btn.png").write_bytes(b"mine-ja")
    freeze(monkeypatch, exe_dir, bundle)

    assert config.template_path("play", "ja") == str(exe_dir / "assets" / "play_btn.png")
    assert config.template_path("play", "en") == str(bundle / "assets_default" / "play_btn_en.png")
    assert config.external_template_path("play", "en") == str(exe_dir / "assets" / "play_btn_en.png")

def test_core_templates_exist_for_every_language():
    for lang in config.LANGS:
        for key in ("play", "continue", "skip", "return_lobby"):
            assert os.path.isfile(config.template_path(key, lang)), (lang, key)

def test_claim_single_template_exists_for_every_language():
    for lang in config.LANGS:
        assert os.path.isfile(config.template_path("claim_single", lang)), lang
        assert os.path.isfile(config.template_path("claim", lang)), lang
