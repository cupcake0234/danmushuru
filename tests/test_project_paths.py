"""Data, caches and temp files remain local, including frozen portable builds."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import model_store
import project_paths
import windows_extension_setup


class ProjectPathsTests(unittest.TestCase):
    def test_source_model_and_extension_do_not_use_user_profile(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/unused-appdata"}):
            root = project_paths.project_root()
            self.assertEqual(model_store.managed_model_dir(),
                             root / "data" / "models" / model_store.MODEL_NAME)
            self.assertEqual(windows_extension_setup.extension_folder(),
                             root / "data" / "browser_extension_ready")

    def test_frozen_build_uses_project_root_and_shared_folder_uses_exe_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "dist").mkdir()
            (root / "windows_app.py").touch()
            (root / "build_windows_exe.bat").touch()
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(root / "dist" / "DanmuLive.exe")
            ):
                self.assertEqual(project_paths.project_root(), root)
            portable = root / "shared"
            portable.mkdir()
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(portable / "DanmuLive.exe")
            ):
                self.assertEqual(project_paths.project_root(), portable)

    def test_temp_and_dependency_caches_override_external_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(project_paths, "project_root", return_value=root), patch.dict(
                os.environ, {"TEMP": "C:/unused-temp", "HF_HOME": "C:/unused-models"}
            ), patch.object(tempfile, "tempdir"):
                project_paths.configure_runtime_paths()
                self.assertEqual(Path(tempfile.gettempdir()), root / ".tools" / "tmp")
                for name in ("TEMP", "TMP", "TMPDIR", "HF_HOME", "HF_HUB_CACHE",
                             "MODELSCOPE_CACHE", "PIP_CACHE_DIR", "UV_CACHE_DIR",
                             "PYINSTALLER_CONFIG_DIR", "XDG_CACHE_HOME"):
                    self.assertTrue(Path(os.environ[name]).is_relative_to(root), name)


if __name__ == "__main__":
    unittest.main()
