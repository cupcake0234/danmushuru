"""The folder users load into Chromium must contain browser assets only."""

from pathlib import Path
import json
import struct
import unittest

from windows_extension_setup import EXTENSION_FILES


PACKAGE = Path(__file__).resolve().parent.parent / "browser_extension_ready"


class BrowserExtensionPackageTests(unittest.TestCase):
    def test_loadable_folder_has_no_reserved_names_or_python_cache(self):
        expected = {
            "manifest.json", "service_worker.js", "generated",
            "generated/bilibili.js", "generated/douyu.js", "generated/douyin.js",
            "_locales", "_locales/zh_CN", "_locales/zh_CN/messages.json", "icons",
            "icons/icon16.png", "icons/icon32.png", "icons/icon48.png", "icons/icon128.png",
        }
        entries = {item.relative_to(PACKAGE).as_posix() for item in PACKAGE.rglob("*")}
        self.assertEqual(entries, expected)
        self.assertFalse(any(part.startswith("_") and part != "_locales" for entry in entries
                             for part in Path(entry).parts))

    def test_store_metadata_and_icons_are_available_to_installer(self):
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        locale_path = f"_locales/{manifest['default_locale']}/messages.json"
        self.assertIn(locale_path, EXTENSION_FILES)
        messages = json.loads((PACKAGE / locale_path).read_text(encoding="utf-8"))
        for field in ("name", "description"):
            self.assertTrue(messages[manifest[field][6:-2]]["message"])
        for size, relative in manifest["icons"].items():
            self.assertIn(relative, EXTENSION_FILES)
            data = (PACKAGE / relative).read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (int(size), int(size)))


if __name__ == "__main__":
    unittest.main()
