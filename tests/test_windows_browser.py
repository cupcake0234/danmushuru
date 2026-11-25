import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from windows_browser import BrowserControlError, BrowserTarget, WindowsBrowser, supported_platform


class WindowsBrowserTests(unittest.TestCase):
    def make_old_extension(self):
        browser = WindowsBrowser(ports=[])
        tabs = [SimpleNamespace(client_id="edge", tab_id=7, platform="bilibili", room_number="123",
                                url="https://live.bilibili.com/123", title="直播甲", ready=True, reason=""),
                SimpleNamespace(client_id="edge", tab_id=8, platform="douyu", room_number="456",
                                url="https://www.douyu.com/456", title="直播乙", ready=True, reason="")]
        browser.extension_bridge = SimpleNamespace(current_view=lambda: None, tabs=lambda: tabs,
                                                   execute=Mock(return_value={"ok": True, "state": "done"}))
        return browser, tabs

    def test_old_extension_follows_browser_window_title_without_focus_reports(self):
        browser, _ = self.make_old_extension()
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window", return_value=(123, "直播甲 - Microsoft Edge")
        ) as front, patch("windows_native_browser.NativeWindowsBrowser") as native:
            first, _ = browser.viewing_room()
            front.return_value = (123, "直播乙 - Microsoft Edge")
            second, _ = browser.viewing_room()
        self.assertEqual((first.room_number, second.room_number), ("123", "456"))
        native.assert_not_called()

    def test_edge_grouped_window_titles_and_profile_suffix_are_supported(self):
        browser, _ = self.make_old_extension()
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window",
            return_value=(123, "直播甲 和另外 17 个页面 - 个人 - Microsoft\u200b Edge")
        ), patch("windows_native_browser.NativeWindowsBrowser") as native:
            target, _ = browser.viewing_room()
        self.assertEqual(target.room_number, "123")
        native.assert_not_called()

    def test_fallback_can_send_through_old_extension_without_new_focus_guard(self):
        browser, _ = self.make_old_extension()
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window", return_value=(123, "直播甲 - Microsoft Edge")
        ):
            target, _ = browser.viewing_room()
            browser.send(target, "测试", follow_active=True)
        self.assertFalse(browser.extension_bridge.execute.call_args.args[3]["followActive"])

    def test_fast_fallback_does_not_keep_old_room_after_title_changes(self):
        browser, _ = self.make_old_extension()
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window", return_value=(123, "直播甲 - Microsoft Edge")
        ) as front:
            target, _ = browser.viewing_room()
            self.assertEqual(browser.viewing_room(refresh_native=False)[0], target)
            front.return_value = (123, "其他页面 - Microsoft Edge")
            self.assertIsNone(browser.viewing_room(refresh_native=False)[0])

    def test_ambiguous_same_room_tabs_are_not_guessed(self):
        browser, tabs = self.make_old_extension()
        tabs.append(SimpleNamespace(**{**vars(tabs[0]), "tab_id": 9}))
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window", return_value=(123, "直播甲 - Microsoft Edge")
        ), patch("windows_native_browser.NativeWindowsBrowser") as native:
            native.return_value.active_tab.return_value = SimpleNamespace(
                platform="bilibili", room_number="123", window_handle=123)
            target, hint = browser.viewing_room()
        self.assertIsNone(target)
        self.assertIn("多个标签页", hint)

    def test_fallback_pauses_on_non_live_active_page(self):
        browser, _ = self.make_old_extension()
        with patch("windows_browser.os.name", "nt"), patch(
            "windows_native_browser.frontmost_browser_window", return_value=(123, "其他页面 - Microsoft Edge")
        ), patch("windows_native_browser.NativeWindowsBrowser") as native:
            native.return_value.active_tab.return_value = None
            target, hint = browser.viewing_room()
        self.assertIsNone(target)
        self.assertIn("不是直播间", hint)

    def make_viewing_browser(self, *, snapshot_url=None):
        browser = WindowsBrowser(ports=[])
        view = {"clientId": "edge", "tabId": 7, "url": "https://live.bilibili.com/123", "title": "正在看的直播"}
        tab = SimpleNamespace(client_id="edge", tab_id=7, url=snapshot_url or view["url"],
                              ready=True, reason="")
        browser.extension_bridge = SimpleNamespace(current_view=lambda: view, tabs=lambda: [tab], execute=Mock(
            return_value={"ok": True, "state": "done"}))
        return browser, view

    def test_viewing_room_uses_exact_profile_and_tab(self):
        browser, _ = self.make_viewing_browser()
        target, hint = browser.viewing_room()
        self.assertEqual((target.client_id, target.tab_id, target.room_number), ("edge", "7", "123"))
        self.assertTrue(target.ready)

    def test_same_tab_navigation_does_not_reuse_old_ready_state(self):
        browser, _ = self.make_viewing_browser(snapshot_url="https://live.bilibili.com/999")
        target, _ = browser.viewing_room()
        self.assertEqual(target.room_number, "123")
        self.assertFalse(target.ready)

    def test_auto_send_has_extension_guard_and_rejects_changed_view(self):
        browser, view = self.make_viewing_browser()
        target, _ = browser.viewing_room()
        browser.send(target, "测试", follow_active=True)
        payload = browser.extension_bridge.execute.call_args.args[3]
        self.assertTrue(payload["followActive"])
        view["tabId"] = 8
        with self.assertRaisesRegex(BrowserControlError, "活动直播页已变化"):
            browser.send(target, "测试", follow_active=True)
        self.assertEqual(browser.extension_bridge.execute.call_count, 1)

    def test_no_extension_does_not_guess_an_auto_target(self):
        browser = WindowsBrowser(ports=[])
        target, hint = browser.viewing_room()
        self.assertIsNone(target)
        self.assertIn("扩展", hint)

    def test_extension_lists_background_room_and_sends_without_tab_selection(self):
        browser = WindowsBrowser(ports=[])
        tab = SimpleNamespace(client_id="profile", tab_id=7,
                              url="https://live.douyin.com/123", title="抖音直播",
                              platform="douyin", room_number="123", ready=True, reason="")
        bridge = SimpleNamespace(tabs=lambda: [tab], execute=lambda *args, **kwargs: {
            "ok": True, "state": "done", "confirmation": "triggered"
        })
        browser.extension_bridge = bridge
        with patch("windows_browser.os.name", "nt"), patch.object(
            browser, "endpoints", return_value=[]
        ), patch("windows_native_browser.NativeWindowsBrowser") as native:
            native.return_value.discover.return_value = []
            rooms = browser.rooms()
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0].source, "extension")
        self.assertEqual(rooms[0].room_number, "123")
        self.assertEqual(browser.send(rooms[0], "测试")["confirmation"], "triggered")

    def test_windows_prefers_silent_cdp_target_and_keeps_other_native_room(self):
        browser = WindowsBrowser(ports=[])
        cdp = BrowserTarget("cdp", 9222, "ws://cdp", "bilibili", "1",
                            "https://live.bilibili.com/1", "B站", True, True)
        native = [
            SimpleNamespace(tab_id="a", window_handle=1, platform="bilibili",
                            room_number="1", url=cdp.url, title="B站", ready=True, reason=""),
            SimpleNamespace(tab_id="b", window_handle=2, platform="douyu",
                            room_number="2", url="https://www.douyu.com/2", title="斗鱼",
                            ready=True, reason=""),
        ]
        with patch("windows_browser.os.name", "nt"), patch.object(
            browser, "endpoints", return_value=["endpoint"]
        ), patch.object(browser, "inspect", return_value=cdp), patch(
            "windows_native_browser.NativeWindowsBrowser"
        ) as native_browser:
            native_browser.return_value.discover.return_value = native
            rooms = browser.rooms()
        self.assertEqual([room.source for room in rooms], ["cdp", "windows"])
        self.assertEqual([room.room_number for room in rooms], ["1", "2"])

    def test_supported_platform_extracts_rooms(self):
        cases = {
            "https://live.bilibili.com/12345": ("bilibili", "12345"),
            "https://www.douyu.com/abc_room": ("douyu", "abc_room"),
            "https://douyu.com/abc_room/": ("douyu", "abc_room"),
            "https://live.douyin.com/7702781691840891699": ("douyin", "7702781691840891699"),
            "https://www.douyin.com/live/7702781691840891699?enter_from=web":
                ("douyin", "7702781691840891699"),
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(supported_platform(url), expected)

    def test_unrelated_pages_are_ignored(self):
        for url in ("https://www.douyin.com/video/123", "https://example.com/123", "about:blank"):
            with self.subTest(url=url):
                self.assertEqual(supported_platform(url), (None, None))

    def test_endpoints_only_include_supported_pages(self):
        payload = [
            {"type": "page", "id": "b", "url": "https://live.bilibili.com/1", "webSocketDebuggerUrl": "ws://b"},
            {"type": "page", "id": "x", "url": "https://example.com", "webSocketDebuggerUrl": "ws://x"},
            {"type": "service_worker", "id": "s", "url": "https://live.douyin.com/2", "webSocketDebuggerUrl": "ws://s"},
        ]

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps(payload).encode()

        with patch("windows_browser.urlopen", return_value=Response()):
            browser = WindowsBrowser(ports=[9222])
            endpoints = browser.endpoints()
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(endpoints[0][2:], ("bilibili", "1"))

    def test_send_polls_page_job_until_done(self):
        browser = WindowsBrowser(ports=[9222])
        target = BrowserTarget(
            target_id="b", port=9222, websocket_url="ws://b", platform="bilibili",
            room_number="1", url="https://live.bilibili.com/1", title="room",
            ready=True, logged_in=True,
        )

        class Connection:
            def __init__(self):
                self.expressions = []

            def evaluate(self, expression):
                self.expressions.append(expression)
                if '"action":"send"' in expression:
                    return {"ok": True, "state": "pending"}
                return {"ok": True, "state": "done", "confirmation": "api"}

            def close(self):
                pass

        connection = Connection()
        with patch("windows_browser.CDPConnection", return_value=connection), patch("windows_browser.time.sleep"):
            result = browser.send(target, "测试")
        self.assertEqual(result["state"], "done")
        self.assertEqual(len(connection.expressions), 2)
        self.assertIn('"action":"poll"', connection.expressions[1])


if __name__ == "__main__":
    unittest.main()
