import unittest
from types import SimpleNamespace
from unittest.mock import patch

from windows_browser import supported_platform
from windows_native_browser import NativeBrowserError, NativeWindowsBrowser


class Tab:
    def __init__(self, name, runtime_id, active):
        self.element_info = SimpleNamespace(
            name=name,
            element=SimpleNamespace(GetRuntimeId=lambda: runtime_id),
        )
        self.active = active
        self.iface_selection_item = Selection(self)

    def select(self):
        for tab in self.group:
            tab.active = False
        self.active = True


class Selection:
    def __init__(self, tab):
        self.tab = tab

    @property
    def CurrentIsSelected(self):
        return self.tab.active

    def Select(self):
        self.tab.select()


class NativeBrowserTests(unittest.TestCase):
    def setUp(self):
        self.first = Tab("B站直播", [1, 1], True)
        self.second = Tab("斗鱼直播", [1, 2], False)
        self.tabs = [self.first, self.second]
        for tab in self.tabs:
            tab.group = self.tabs
        self.window = SimpleNamespace(handle=123)
        self.browser = NativeWindowsBrowser.__new__(NativeWindowsBrowser)
        self.browser._windows = lambda: [(self.window, "Edge")]
        self.browser._window = lambda handle: self.window
        self.browser._tabs = lambda window: self.tabs

    def address(self, _window):
        return ("https://live.bilibili.com/1" if self.first.active
                else "https://www.douyu.com/2")

    def test_discovers_active_tab_without_switching(self):
        with patch("windows_native_browser._address", side_effect=self.address), patch(
            "windows_native_browser._composer", return_value=(object(), object(), "")
        ):
            found = self.browser.discover(supported_platform)
        self.assertEqual([(tab.platform, tab.room_number) for tab in found],
                         [("bilibili", "1")])
        self.assertTrue(self.first.active)
        self.assertFalse(self.second.active)

    def test_background_tab_with_exposed_url_is_listed_unready(self):
        self.second.element_info.name = "https://www.douyu.com/2"
        with patch("windows_native_browser._address", side_effect=self.address), patch(
            "windows_native_browser._composer", return_value=(object(), object(), "")
        ):
            found = self.browser.discover(supported_platform)
        self.assertEqual(len(found), 2)
        self.assertFalse(found[1].ready)
        self.assertFalse(self.second.active)

    def test_room_change_blocks_send_without_switching(self):
        target = SimpleNamespace(window_handle=123, tab_id="1:1", platform="bilibili",
                                 room_number="999")
        with patch("windows_native_browser._address", side_effect=self.address):
            with self.assertRaisesRegex(NativeBrowserError, "切换房间"):
                self.browser.send(target, "测试", supported_platform)
        self.assertTrue(self.first.active)

    def test_background_send_is_rejected_without_switching(self):
        target = SimpleNamespace(window_handle=123, tab_id="1:2", platform="douyu",
                                 room_number="2")
        with self.assertRaisesRegex(NativeBrowserError, "活动标签页"):
            self.browser.send(target, "测试", supported_platform)
        self.assertTrue(self.first.active)

    def test_existing_draft_blocks_send(self):
        target = SimpleNamespace(window_handle=123, tab_id="1:1", platform="bilibili",
                                 room_number="1")
        editor = SimpleNamespace(iface_value=SimpleNamespace(CurrentValue="已有草稿"))
        button = SimpleNamespace(iface_invoke=SimpleNamespace(Invoke=lambda: self.fail("sent")))
        with patch("windows_native_browser._address", side_effect=self.address), patch(
            "windows_native_browser._composer", return_value=(editor, button, "")
        ):
            with self.assertRaisesRegex(NativeBrowserError, "草稿"):
                self.browser.send(target, "测试", supported_platform)
        self.assertTrue(self.first.active)

    def test_sends_only_to_active_room_without_switching(self):
        target = SimpleNamespace(window_handle=123, tab_id="1:1", platform="bilibili",
                                 room_number="1")
        value = SimpleNamespace(CurrentValue="", CurrentIsReadOnly=False)
        value.SetValue = lambda text: setattr(value, "CurrentValue", text)
        editor = SimpleNamespace(iface_value=value)
        invoked = []
        button = SimpleNamespace(is_enabled=lambda: True,
                                 iface_invoke=SimpleNamespace(Invoke=lambda: invoked.append(True)))
        with patch("windows_native_browser._address", side_effect=self.address), patch(
            "windows_native_browser._composer", return_value=(editor, button, "")
        ):
            result = self.browser.send(target, "测试", supported_platform)
        self.assertEqual(result["confirmation"], "triggered")
        self.assertEqual(invoked, [True])
        self.assertTrue(self.first.active)


if __name__ == "__main__":
    unittest.main()
