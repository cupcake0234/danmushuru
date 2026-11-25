"""Configuration saved from the Windows control panel stays available to voice mode."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import voice


class VoiceSettingsTests(unittest.TestCase):
    def make_model(self, base):
        path = Path(base) / voice.LOCAL_MODEL_NAME
        path.mkdir()
        for name in ("model.int8.onnx", "tokens.txt"):
            (path / name).write_bytes(b"test fixture")
        return path

    def test_save_and_load_source_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.local.json"
            with patch.object(voice, "CONFIG_PATH", config_path), patch.dict(
                os.environ, {"DASHSCOPE_API_KEY": "", "DASHSCOPE_WEBSOCKET_URL": ""}
            ):
                voice.save_settings(" new-key ", " wss://example.com/ws ")
                self.assertEqual(voice.load_settings(),
                                 ("new-key", voice.DEFAULT_MODEL, "wss://example.com/ws"))
                self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), {
                    "dashscope_api_key": "new-key", "model": voice.DEFAULT_MODEL,
                    "websocket_url": "wss://example.com/ws",
                })

    def test_frozen_app_saves_in_project_and_ignores_appdata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "dist" / "config.local.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(json.dumps({"dashscope_api_key": "old-key"}), encoding="utf-8")
            config_path = Path(temp_dir) / "data" / "config.local.json"
            appdata = Path(temp_dir) / "appdata"
            user_config = appdata / "DanmuLive" / "config.local.json"
            user_config.parent.mkdir(parents=True)
            user_config.write_text(json.dumps({"dashscope_api_key": "unrelated-key"}), encoding="utf-8")
            with patch.object(voice, "CONFIG_PATH", config_path), patch.object(
                sys, "frozen", True, create=True
            ), patch.dict(os.environ, {
                "LOCALAPPDATA": str(appdata), "DASHSCOPE_API_KEY": "",
                "DASHSCOPE_WEBSOCKET_URL": "",
            }):
                self.assertEqual(voice.load_settings()[0], "old-key")
                saved_path = voice.save_settings("new-key", voice.DEFAULT_WS_URL)
                self.assertEqual(saved_path, config_path)
                self.assertEqual(voice.load_settings()[0], "new-key")
                self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))
                                 ["dashscope_api_key"], "old-key")
                self.assertEqual(json.loads(user_config.read_text(encoding="utf-8"))
                                 ["dashscope_api_key"], "unrelated-key")

    def test_local_mode_needs_no_key_and_accepts_parent_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model = self.make_model(temp_dir)
            with patch.object(voice, "CONFIG_PATH", Path(temp_dir) / "config.local.json"), patch.dict(
                os.environ, {"DASHSCOPE_API_KEY": "cloud-key"}
            ):
                voice.save_settings("", "", provider="sensevoice", local_model_dir=temp_dir)
                provider, config = voice.recognition_settings()
                self.assertEqual(provider, "sensevoice")
                self.assertEqual(Path(config["local_model_dir"]), model)

    def test_switching_providers_preserves_other_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model = self.make_model(temp_dir)
            config_path = Path(temp_dir) / "config.local.json"
            config_path.write_text(json.dumps({"extra": {"keep": True}}), encoding="utf-8")
            with patch.object(voice, "CONFIG_PATH", config_path):
                voice.save_settings("saved-key", voice.DEFAULT_WS_URL, provider="sensevoice",
                                    local_model_dir=str(model), local_language="zh")
                voice.save_settings("saved-key", voice.DEFAULT_WS_URL, provider="dashscope")
                config = voice.read_settings_file()
                self.assertEqual(config["local_language"], "zh")
                self.assertEqual(config["local_model_dir"], model.name)
                self.assertEqual(config["extra"], {"keep": True})
                self.assertEqual(config["dashscope_api_key"], "saved-key")

    def test_missing_model_and_invalid_options_fail_before_saving(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.local.json"
            with patch.object(voice, "CONFIG_PATH", config_path):
                with self.assertRaisesRegex(voice.VoiceError, "缺少"):
                    voice.save_settings("", "", provider="sensevoice", local_model_dir=temp_dir)
                model = self.make_model(temp_dir)
                for options in ({"local_language": "invalid"}, {"local_num_threads": 0},
                                {"local_threshold_db": float("nan")}):
                    with self.subTest(options=options), self.assertRaises(voice.VoiceError):
                        voice.save_settings("", "", provider="sensevoice",
                                            local_model_dir=str(model), **options)
                self.assertFalse(config_path.exists())

    def test_old_configuration_still_selects_dashscope(self):
        with patch.object(voice, "read_settings_file", return_value={"dashscope_api_key": "key"}):
            self.assertEqual(voice.recognition_settings()[0], "dashscope")

    def test_relative_model_directory_uses_config_location(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model = self.make_model(temp_dir)
            with patch.object(voice, "CONFIG_PATH", Path(temp_dir) / "config.local.json"):
                self.assertEqual(voice.local_model_path(voice.LOCAL_MODEL_NAME), model)

    def test_saved_local_model_moves_with_portable_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            portable = base / "original"
            data = portable / "data"
            models = data / "models"
            models.mkdir(parents=True)
            model = self.make_model(models)
            with patch.object(voice, "CONFIG_PATH", data / "config.local.json"):
                voice.save_settings("", "", provider="sensevoice", local_model_dir=str(model))
                self.assertEqual(voice.read_settings_file()["local_model_dir"],
                                 "models/" + model.name)
            moved = base / "moved folder"
            portable.rename(moved)
            with patch.object(voice, "CONFIG_PATH", moved / "data/config.local.json"):
                _, config = voice.recognition_settings()
                self.assertEqual(Path(config["local_model_dir"]),
                                 moved / "data/models" / model.name)

    def test_managed_install_is_preferred_over_existing_coopanion_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model = self.make_model(temp_dir)
            with patch.object(voice, "managed_model_dir", return_value=model):
                self.assertEqual(voice.default_local_model_dir(), model)

    def test_clean_computer_defaults_to_own_install_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            managed = Path(temp_dir) / "managed" / voice.LOCAL_MODEL_NAME
            with patch.object(voice, "managed_model_dir", return_value=managed), patch.object(
                voice, "COOPANION_MODEL_DIR", Path(temp_dir) / "missing-coopanion"
            ), patch.object(voice, "__file__", str(Path(temp_dir) / "voice.py")):
                self.assertEqual(voice.default_local_model_dir(), managed)


if __name__ == "__main__":
    unittest.main()
