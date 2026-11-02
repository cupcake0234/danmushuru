"""The folder users load into Chromium must contain browser assets only."""

from pathlib import Path
import unittest


PACKAGE = Path(__file__).resolve().parent.parent / "browser_extension_ready"


class BrowserExtensionPackageTests(unittest.TestCase):
    def test_loadable_folder_has_no_reserved_names_or_python_cache(self):
        expected = {
            "manifest.json", "service_worker.js", "generated",
            "generated/bilibili.js", "generated/douyu.js", "generated/douyin.js",
        }
        entries = {item.relative_to(PACKAGE).as_posix() for item in PACKAGE.rglob("*")}
        self.assertEqual(entries, expected)
        self.assertFalse(any(part.startswith("_") for entry in entries
                             for part in Path(entry).parts))


if __name__ == "__main__":
    unittest.main()
