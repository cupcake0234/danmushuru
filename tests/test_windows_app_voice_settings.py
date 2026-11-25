"""Exercise both settings panels without starting a browser or opening a visible window."""

import tkinter as tk
from tkinter import ttk
import gc
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

from model_store import ModelInstallCancelled
from windows_app import WindowsControlPanel


class VoiceSettingsDialogTests(unittest.TestCase):
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

    def open_settings(self, config):
        with patch("windows_app.read_settings_file", return_value=config):
            self.app.show_api_settings()
        dialog = self.app._show_dialog.call_args.args[0]
        widgets = list(self.widgets(dialog))
        provider = next(widget for widget in widgets if isinstance(widget, ttk.Combobox))
        return dialog, provider, widgets

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(predicate(), "settings dialog did not receive the worker result")

    def test_local_settings_switch_to_cloud_and_back(self):
        dialog, provider, widgets = self.open_settings({"voice_provider": "sensevoice"})
        local_entry = next(widget for widget in widgets if isinstance(widget, ttk.Spinbox))
        key_entry = next(widget for widget in widgets if isinstance(widget, ttk.Entry)
                         and str(widget.cget("show")) == "*")
        self.assertEqual(local_entry.master.winfo_manager(), "grid")
        self.assertEqual(key_entry.master.winfo_manager(), "")
        provider.current(1)
        provider.event_generate("<<ComboboxSelected>>")
        self.assertEqual(local_entry.master.winfo_manager(), "")
        self.assertEqual(key_entry.master.winfo_manager(), "grid")
        provider.current(0)
        provider.event_generate("<<ComboboxSelected>>")
        self.assertEqual(local_entry.master.winfo_manager(), "grid")
        dialog.destroy()

    def test_local_save_uses_local_fields_without_requiring_api_key(self):
        dialog, provider, widgets = self.open_settings({"voice_provider": "sensevoice"})
        save_button = next(widget for widget in widgets if isinstance(widget, ttk.Button)
                           and widget.cget("text") == "保存配置")
        with patch("windows_app.save_settings") as save:
            save_button.invoke()
        self.assertEqual(save.call_args.args[0], "")
        self.assertEqual(save.call_args.kwargs["provider"], "sensevoice")
        self.assertEqual(save.call_args.kwargs["local_threshold_db"], -42)
        self.assertEqual(dialog.winfo_exists(), 0)

    def test_one_click_installs_off_ui_thread_and_saves_local_settings(self):
        dialog, provider, widgets = self.open_settings({"voice_provider": "sensevoice"})
        install = next(w for w in widgets if isinstance(w, ttk.Button)
                       and w.cget("text") == "一键安装模型")
        save = next(w for w in widgets if isinstance(w, ttk.Button)
                    and w.cget("text") == "保存配置")
        installed = Path("C:/test/model")
        ui_thread = threading.get_ident()
        worker_threads = []

        def download(target, **options):
            worker_threads.append(threading.get_ident())
            options["on_progress"](10, 10, "verified")
            return installed

        with patch("windows_app.install_model", side_effect=download), patch(
            "windows_app.save_settings"
        ) as save_settings:
            install.invoke()
            self.assertTrue(save.instate(["disabled"]))
            self.wait_for(lambda: save_settings.called)
            self.assertTrue(save.instate(["!disabled"]))
        self.assertNotEqual(worker_threads[0], ui_thread)
        self.assertEqual(save_settings.call_args.kwargs["provider"], "sensevoice")
        self.assertEqual(save_settings.call_args.kwargs["local_model_dir"], str(installed))
        self.assertEqual(dialog.winfo_exists(), 1)
        dialog.destroy()

    def test_cancel_download_keeps_settings_unchanged_and_allows_retry(self):
        dialog, provider, widgets = self.open_settings({"voice_provider": "sensevoice"})
        install = next(w for w in widgets if isinstance(w, ttk.Button)
                       and w.cget("text") == "一键安装模型")
        cancel = next(w for w in widgets if isinstance(w, ttk.Button)
                      and w.cget("text") == "取消下载")

        def download(target, **options):
            options["cancel"].wait(2)
            raise ModelInstallCancelled("cancelled")

        with patch("windows_app.install_model", side_effect=download), patch(
            "windows_app.save_settings"
        ) as save_settings:
            install.invoke()
            cancel.invoke()
            self.wait_for(lambda: install.instate(["!disabled"]))
            save_settings.assert_not_called()
        dialog.destroy()

    def test_closing_dialog_cancels_download_without_saving(self):
        dialog, provider, widgets = self.open_settings({"voice_provider": "sensevoice"})
        install = next(w for w in widgets if isinstance(w, ttk.Button)
                       and w.cget("text") == "一键安装模型")
        finished = threading.Event()

        def download(target, **options):
            options["cancel"].wait(2)
            finished.set()
            raise ModelInstallCancelled("cancelled")

        with patch("windows_app.install_model", side_effect=download), patch(
            "windows_app.save_settings"
        ) as save_settings:
            install.invoke()
            dialog.destroy()
            self.assertTrue(finished.wait(1))
            self.root.update()
            save_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
