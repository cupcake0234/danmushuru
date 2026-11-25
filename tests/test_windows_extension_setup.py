"""The packaged extension is copied to a stable browser load directory."""

from pathlib import Path
import gc
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from windows_app import WindowsControlPanel
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


class ExtensionSetupDialogTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.app = object.__new__(WindowsControlPanel)
        self.app.root = self.root
        self.app._append_log = Mock()
        self.app._show_dialog = Mock()

    def tearDown(self):
        self.root.destroy()
        self.app = None
        self.root = None
        gc.collect()

    def widgets(self, parent):
        for widget in parent.winfo_children():
            yield widget
            yield from self.widgets(widget)

    def test_folder_remains_visible_and_copyable_after_dialog_opens(self):
        folder = Path("C:/Users/Test User/AppData/Local/DanmuLive/browser_extension_ready")
        with patch("windows_extension_setup.prepare_extension", return_value=folder):
            self.app.show_extension_setup()
        dialog = self.app._show_dialog.call_args.args[0]
        gc.collect()
        self.root.update()
        widgets = list(self.widgets(dialog))
        entry = next(widget for widget in widgets if isinstance(widget, ttk.Entry))
        self.assertEqual(entry.get(), str(folder))
        self.assertTrue(entry.instate(["readonly"]))
        copy = next(widget for widget in widgets if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "复制路径")
        with patch.object(dialog, "clipboard_clear") as clear, patch.object(
            dialog, "clipboard_append"
        ) as append:
            copy.invoke()
        clear.assert_called_once_with()
        append.assert_called_once_with(str(folder))
        dialog.destroy()


if __name__ == "__main__":
    unittest.main()
