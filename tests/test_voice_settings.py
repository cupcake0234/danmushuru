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

    def test_frozen_app_saves_to_user_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "dist" / "config.local.json"
            legacy_path.parent.mkdir()
            legacy_path.write_text(json.dumps({"dashscope_api_key": "old-key"}), encoding="utf-8")
            with patch.object(voice, "CONFIG_PATH", legacy_path), patch.object(
                sys, "frozen", True, create=True
            ), patch.dict(os.environ, {
                "LOCALAPPDATA": temp_dir, "DASHSCOPE_API_KEY": "",
                "DASHSCOPE_WEBSOCKET_URL": "",
            }):
                self.assertEqual(voice.load_settings()[0], "old-key")
                saved_path = voice.save_settings("new-key", voice.DEFAULT_WS_URL)
                self.assertEqual(saved_path, Path(temp_dir) / "DanmuLive" / "config.local.json")
                self.assertEqual(voice.load_settings()[0], "new-key")
                self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))
                                 ["dashscope_api_key"], "old-key")


if __name__ == "__main__":
    unittest.main()
