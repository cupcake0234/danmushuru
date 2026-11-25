"""Keep room navigation and log selection working with the flat light controls."""

from types import SimpleNamespace
import gc
import tkinter as tk
import unittest
from unittest.mock import Mock

from windows_theme import ActivityLog, RoomTable


class PhotoControlsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)

    def tearDown(self):
        self.root.destroy()
        self.root = None
        gc.collect()

    def make_table(self):
        table = RoomTable(self.root, columns=("platform", "room", "title", "ready", "url"))
        table.place(x=0, y=0, width=700, height=180)
        self.root.update_idletasks()
        for index in range(20):
            table.insert("", "end", iid=str(index),
                         values=("bilibili", str(index), "直播间", "可发送", "https://example.com"))
        return table

    def test_mouse_and_keyboard_choose_the_corresponding_room(self):
        table = self.make_table()
        table._click(SimpleNamespace(x=100, y=table.header_height + 50))
        self.assertEqual(table.item(table.selection()[0], "values")[1], "1")
        table._key(SimpleNamespace(keysym="Down"))
        self.assertEqual(table.selection(), ("2",))
        table._key(SimpleNamespace(keysym="End"))
        self.assertEqual(table.selection(), ("19",))
        self.assertGreater(table.offset, 0)
        table._key(SimpleNamespace(keysym="Home"))
        self.assertEqual(table.offset, 0)

    def test_scroll_and_refresh_do_not_select_a_different_room(self):
        table = self.make_table()
        table.selection_set("3")
        self.root.update_idletasks()
        table.yview("scroll", 2, "units")
        self.assertEqual(table.selection(), ("3",))
        table.delete(*table.get_children())
        self.assertEqual(table.selection(), ())
        table.insert("", "end", iid="0", values=("douyu", "456", "新房间", "可发送", "url"))
        table.selection_set("0")
        self.assertEqual(table.item("0", "values")[1], "456")

    def test_log_keeps_selected_text_and_can_copy_complete_log(self):
        log = ActivityLog(self.root)
        log.place(x=0, y=0, width=700, height=130)
        log.clipboard_clear = Mock()
        log.clipboard_append = Mock()
        self.root.update_idletasks()
        log.append("first line")
        log.append("second line", "recognized")
        self.root.update_idletasks()
        log._selection_start, log._selection_end = (1, 0), (1, 6)
        log.copy_selection()
        log.clipboard_append.assert_called_with("second")
        log.copy_all()
        log.clipboard_append.assert_called_with("first line\nsecond line")

    def test_initial_unmapped_controls_do_not_raise_render_errors(self):
        table = RoomTable(self.root, columns=("platform", "room", "title", "ready", "url"))
        log = ActivityLog(self.root)
        table.redraw()
        log.redraw()
        self.root.update_idletasks()
        self.assertEqual(self.callback_errors, [])

    def test_full_log_scrollbar_renders_at_the_end_of_a_long_session(self):
        log = ActivityLog(self.root)
        log.place(x=0, y=0, width=700, height=130)
        for index in range(1000):
            log.append(f"message {index}")
        self.root.update_idletasks()
        self.assertEqual(self.callback_errors, [])
        self.assertIsNotNone(log.rendered_image)
        self.assertGreater(log.offset, 0)


if __name__ == "__main__":
    unittest.main()
