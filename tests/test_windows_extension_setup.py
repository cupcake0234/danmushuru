"""The packaged extension is copied to a stable browser load directory."""

from pathlib import Path
import tempfile
import unittest

from windows_extension_setup import EXTENSION_FILES, prepare_extension


class WindowsExtensionSetupTests(unittest.TestCase):
    def test_prepares_only_browser_assets_and_updates_changed_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source"
            destination = Path(temp_dir) / "installed"
            for relative_path in EXTENSION_FILES:
                source_file = source / relative_path
                source_file.parent.mkdir(parents=True, exist_ok=True)
                source_file.write_text("old", encoding="utf-8")
            (source / "__pycache__").mkdir()
            (source / "__pycache__" / "bad.pyc").write_bytes(b"cache")

            self.assertEqual(prepare_extension(source, destination), destination)
            self.assertEqual({path.relative_to(destination).as_posix()
                              for path in destination.rglob("*") if path.is_file()},
                             set(EXTENSION_FILES))

            (source / "manifest.json").write_text("new", encoding="utf-8")
            prepare_extension(source, destination)
            self.assertEqual((destination / "manifest.json").read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
