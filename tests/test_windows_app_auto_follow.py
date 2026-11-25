"""Automatic selection follows viewed tabs while keeping speech tied to its room."""

from collections import deque
import gc
import queue
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from windows_app import WindowsControlPanel
from windows_theme import ModeButton
from windows_browser import BrowserTarget, WindowsBrowser, supported_platform
from windows_extension_bridge import ExtensionBridge


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def room(number, tab="7", ready=True):
    return BrowserTarget(tab, 0, "", "bilibili", number,
                         "https://live.bilibili.com/" + number, "直播", ready, None,
                         source="extension", tab_id=tab, client_id="edge")


class AutoFollowTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(WindowsControlPanel)
        app = self.app
        app.target_mode = Value("auto")
        app.selected_key = None
        app.rooms = []
        app.auto_target_identity = None
        app.auto_listen_requested = False
        app.auto_follow_busy = False
        app.auto_follow_generation = 0
        app.auto_hint = ""
        app.voice = None
        app.listening = False
        app.voice_session = 1
        app.listening_target_key = None
        app.target_missing_since = None
        app.voice_pending = deque()
        app.voice_send_busy = False
        app.voice_send_timer = None
        app.voice_waiting_for_room = False
        app.voice_inflight = None
        app.stop_voice = threading.Event()
        app.interval_var = Value("1")
        app.status = Mock()
        app.listen_button = Mock()
        app.table = Mock()
        app.table.selection.return_value = ()
        app.root = Mock()
        app._append_log = Mock()
        app._update_room_summary = Mock()
        app.jobs = queue.Queue()
        app.browser = Mock()

        def render(rooms, error):
            app.rooms = rooms

        app._render_rooms = Mock(side_effect=render)

    def start_fake_voice(self):
        self.app.voice = Mock()
        self.app.listening = True
        self.app.listening_target_key = self.app.selected_key

    def test_selects_current_room_without_starting_listening(self):
        target = room("123")
        self.app._apply_auto_room(target, "")
        self.assertEqual(self.app.selected_key, target.key)
        self.assertEqual(self.app._selected(), target)
        self.assertIsNone(self.app.voice)

    def test_switching_rooms_clears_old_queue_and_restarts_recording(self):
        self.app._apply_auto_room(room("123"), "")
        self.app.auto_listen_requested = True
        self.start_fake_voice()
        self.app.voice_pending.append("旧房间的话")
        old_voice = self.app.voice
        with patch.object(self.app, "start_listening") as start:
            self.app._apply_auto_room(room("456", tab="8"), "")
        old_voice.close.assert_called_once()
        self.assertEqual(list(self.app.voice_pending), [])
        self.assertTrue(self.app.auto_listen_requested)
        self.assertEqual(self.app._selected().room_number, "456")
        start.assert_called_once()

    def test_navigation_in_same_tab_also_starts_a_new_voice_session(self):
        self.app._apply_auto_room(room("123"), "")
        self.app.auto_listen_requested = True
        self.start_fake_voice()
        old_session = self.app.voice_session
        with patch.object(self.app, "start_listening"):
            self.app._apply_auto_room(room("456"), "")
        self.assertGreater(self.app.voice_session, old_session)

    def test_non_live_page_pauses_then_live_page_resumes(self):
        self.app._apply_auto_room(room("123"), "")
        self.app.auto_listen_requested = True
        self.start_fake_voice()
        self.app._apply_auto_room(None, "当前不是直播页")
        self.assertIsNone(self.app.selected_key)
        self.assertIsNone(self.app.voice)
        self.assertTrue(self.app.auto_listen_requested)
        with patch.object(self.app, "start_listening") as start:
            self.app._apply_auto_room(room("456"), "")
        start.assert_called_once()

    def test_unchanged_room_does_not_restart_or_log_repeatedly(self):
        target = room("123")
        self.app._apply_auto_room(target, "")
        self.start_fake_voice()
        self.app._append_log.reset_mock()
        old_voice = self.app.voice
        self.app._apply_auto_room(target, "")
        old_voice.close.assert_not_called()
        self.app._append_log.assert_not_called()

    def test_start_in_auto_mode_waits_for_room_and_can_be_stopped(self):
        self.app.start_listening()
        self.assertTrue(self.app.auto_listen_requested)
        self.assertIsNone(self.app.voice)
        self.app.toggle_listening()
        self.assertFalse(self.app.auto_listen_requested)

    def test_clicking_a_different_row_switches_to_manual(self):
        first, second = room("123"), room("456", tab="8")
        self.app.rooms = [first, second]
        self.app.selected_key = first.key
        self.app.rendering_rooms = False
        self.app.table.selection.return_value = ("1",)
        self.app._manual_room_choice()
        self.assertEqual(self.app.target_mode.get(), "manual")
        self.assertEqual(self.app.selected_key, second.key)

    def test_sentence_for_previous_view_is_discarded(self):
        target = room("123")
        self.app.rooms = [target]
        self.app.selected_key = target.key
        self.app.listening = True
        self.app.browser.viewing_room.return_value = (room("456", tab="8"), "")
        with patch.object(self.app, "_request_auto_room") as request:
            self.app._send_voice_sentence("旧房间的话")
        self.assertFalse(self.app.voice_pending)
        request.assert_called_once()
        self.app.browser.send.assert_not_called()

    def test_programmatic_selection_events_do_not_exit_auto_mode(self):
        first, second = room("123"), room("456", tab="8")
        self.app.rooms = [first, second]
        self.app.selected_key = first.key
        self.app.rendering_rooms = False
        self.app.table.selection.return_value = ("1",)
        self.app._select_room()
        self.assertEqual(self.app.target_mode.get(), "auto")
        self.assertEqual(self.app.selected_key, first.key)


class AutoFollowInterfaceTests(unittest.TestCase):
    def setUp(self):
        # Tk interpreters must be collected on the thread that created them,
        # before subsequent HTTP bridge tests start allocating on worker threads.
        self.addCleanup(gc.collect)

    def test_old_extension_without_view_reports_switches_the_real_room_table(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        bridge = ExtensionBridge(supported_platform, port=0)
        browser = WindowsBrowser(ports=[])
        browser.extension_bridge = bridge
        bridge.publish({"clientId": "edge", "tabs": [
            {"tabId": 7, "url": "https://live.bilibili.com/123", "title": "直播甲", "ready": True},
            {"tabId": 8, "url": "https://www.douyu.com/456", "title": "直播乙", "ready": True},
        ]})
        try:
            with patch("windows_app.WindowsBrowser", return_value=browser), patch("windows_browser.os.name", "nt"), patch(
                "windows_native_browser.frontmost_browser_window",
                return_value=(123, "直播甲 和另外 17 个页面 - 个人 - Microsoft Edge")
            ) as front, patch("windows_native_browser.NativeWindowsBrowser") as native:
                app = WindowsControlPanel(root)
                app.target_mode.set("auto")
                # Use the actual bridge -> browser -> worker -> UI job -> Treeview path.
                for title, expected in (("直播甲", "123"), ("直播乙", "456")):
                    front.return_value = (123, title + " 和另外 17 个页面 - 个人 - Microsoft Edge")
                    app._request_auto_room()
                    job = app.jobs.get(timeout=2)
                    app.jobs.put(job)
                    app._drain_jobs()
                    self.assertEqual(app._selected().room_number, expected)
                    values = app.table.item(app.table.selection()[0], "values")
                    self.assertEqual(values[1], expected)
                    self.assertTrue(app._auto_mode())
                native.assert_not_called()
        finally:
            bridge.close()
            root.destroy()

    def test_mode_controls_keep_auto_selection_and_allow_manual_override(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        root.withdraw()
        try:
            with patch("windows_app.WindowsBrowser"), patch.object(WindowsControlPanel, "_request_auto_room"):
                app = WindowsControlPanel(root)
                app._append_log = Mock()

                def widgets(parent):
                    for widget in parent.winfo_children():
                        yield widget
                        yield from widgets(widget)

                modes = {widget.cget("text"): widget for widget in widgets(root)
                         if isinstance(widget, ModeButton)}
                modes["自动跟随"].invoke()
                self.assertTrue(app._auto_mode())
                target = room("123")
                app._apply_auto_room(target, "")
                # Treeview emits its selection event asynchronously after rendering.
                app._select_room()
                self.assertTrue(app._auto_mode())
                self.assertEqual(app._selected(), target)
                modes["手动选择"].invoke()
                self.assertFalse(app._auto_mode())
                self.assertEqual(app._selected(), target)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
