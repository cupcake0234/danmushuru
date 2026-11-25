"""Browser live-room discovery via Windows UIA, with legacy CDP support."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


class BrowserControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserTarget:
    target_id: str
    port: int
    websocket_url: str
    platform: str
    room_number: str
    url: str
    title: str
    ready: bool
    logged_in: bool | None
    reason: str = ""
    source: str = "cdp"
    window_handle: int = 0
    tab_id: str = ""
    client_id: str = ""

    @property
    def key(self):
        if self.source == "extension":
            return f"extension:{self.client_id}:{self.tab_id}"
        if self.source == "windows":
            return f"windows:{self.window_handle}:{self.tab_id}"
        return f"{self.port}:{self.target_id}"

    def as_result(self):
        return {
            "ok": True,
            "platform": self.platform,
            "roomNumber": self.room_number,
            "url": self.url,
            "title": self.title,
            "ready": self.ready,
            "loggedIn": self.logged_in,
            "reason": self.reason,
        }


class CDPConnection:
    def __init__(self, websocket_url, timeout=5):
        try:
            import websocket
        except ImportError as exc:
            raise BrowserControlError("缺少 websocket-client，请安装 requirements.txt") from exc
        self._websocket = websocket
        try:
            try:
                self.socket = websocket.create_connection(
                    websocket_url, timeout=timeout, http_proxy_host=None,
                    http_proxy_port=None,
                )
            except TypeError:
                self.socket = websocket.create_connection(websocket_url, timeout=timeout)
        except Exception as exc:
            raise BrowserControlError(f"无法连接浏览器调试页面：{exc}") from exc
        self._next_id = 0

    def close(self):
        try:
            self.socket.close()
        except Exception:
            pass

    def call(self, method, params=None):
        self._next_id += 1
        request_id = self._next_id
        try:
            self.socket.send(json.dumps({"id": request_id, "method": method,
                                         "params": params or {}}))
        except Exception as exc:
            raise BrowserControlError(f"发送浏览器调试请求失败：{exc}") from exc
        while True:
            try:
                message = json.loads(self.socket.recv())
            except Exception as exc:
                raise BrowserControlError(f"读取浏览器调试响应失败：{exc}") from exc
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise BrowserControlError(f"CDP {method} 失败：{error.get('message', error)}")
            return message.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "userGesture": True,
        })
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            raise BrowserControlError(f"页面脚本执行失败：{detail.get('text', 'unknown')}")
        value = result.get("result", {}).get("value")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value


def supported_platform(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None, None
    if parsed.scheme not in {"http", "https"}:
        return None, None
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "live.bilibili.com" and parts and re.fullmatch(r"\d+", parts[0]):
        return "bilibili", parts[0]
    if (host in {"www.douyu.com", "douyu.com"} and parts and
            parts[0].lower() not in {"directory", "topic", "search", "video", "gapi"} and
            re.fullmatch(r"[A-Za-z0-9_-]+", parts[0])):
        return "douyu", parts[0]
    if host == "live.douyin.com" and parts and re.fullmatch(r"\d+", parts[0]):
        return "douyin", parts[0]
    if host == "www.douyin.com" and len(parts) == 2 and parts[0] == "live" and re.fullmatch(r"\d+", parts[1]):
        return "douyin", parts[1]
    return None, None


def _window_matches_page_title(window_title, page_title):
    if not page_title or not window_title.startswith(page_title):
        return False
    suffix = window_title[len(page_title):]
    return not suffix or suffix.startswith(" - ") or bool(re.match(
        r"^\s*(?:和另外\s*\d+\s*个(?:页面|标签页)|and\s+\d+\s+(?:(?:other|more)\s+)?(?:pages?|tabs?))"
        r"\s*(?: - |$)", suffix, re.IGNORECASE))


class WindowsBrowser:
    def __init__(self, ports=None, timeout=1.2):
        configured = ports if ports is not None else os.environ.get("DANMU_CDP_PORTS", "9222,9223")
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",") if item.strip()]
        self.ports = tuple(int(port) for port in configured)
        self.timeout = timeout
        self.last_error = None
        self.native_lock = threading.Lock()
        self.extension_bridge = None
        self.extension_error = None
        self._discovered_rooms = []
        self._native_view_cache = None
        self._native_view_signature = None
        self._native_view_time = 0
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "web_actions"
        self.scripts = {
            "bilibili": (root / "browser_actions.js").read_text(encoding="utf-8"),
            "douyu": (root / "douyu_actions.js").read_text(encoding="utf-8"),
            "douyin": (root / "douyin_web_actions.js").read_text(encoding="utf-8"),
        }

    @property
    def extension_connected(self):
        return bool(self.extension_bridge and self.extension_bridge.connected())

    def endpoints(self):
        targets = []
        seen = set()
        errors = []
        reachable = False
        for port in self.ports:
            try:
                with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (OSError, URLError, ValueError, TimeoutError):
                errors.append(port)
                continue
            reachable = True
            for target in payload if isinstance(payload, list) else []:
                if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
                    continue
                identity = (port, target.get("id"))
                if identity in seen:
                    continue
                seen.add(identity)
                platform, room = supported_platform(target.get("url", ""))
                if platform:
                    targets.append((port, target, platform, room))
        self.last_error = (
            "未连接到 CDP 端口：" + ", ".join(str(port) for port in errors)
            if errors and not reachable else None
        )
        return targets

    def _expression(self, platform, action, payload):
        request = {"action": action, **payload}
        return self.scripts[platform].replace(
            "__PAYLOAD_JSON__", json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        )

    def inspect(self, endpoint):
        port, raw, platform, room = endpoint
        connection = CDPConnection(raw["webSocketDebuggerUrl"], timeout=self.timeout * 4)
        try:
            result = connection.evaluate(self._expression(platform, "inspect", {}))
        finally:
            connection.close()
        if not isinstance(result, dict):
            raise BrowserControlError("页面检查返回格式无效")
        return BrowserTarget(
            target_id=str(raw.get("id", "")), port=port,
            websocket_url=raw["webSocketDebuggerUrl"], platform=platform,
            room_number=str(result.get("roomNumber") or room),
            url=str(raw.get("url", "")), title=str(raw.get("title", "")),
            ready=bool(result.get("ready")),
            logged_in=result.get("loggedIn"), reason=str(result.get("error", "")),
        )

    def rooms(self):
        result = self._discover_rooms()
        self._discovered_rooms = result
        return result

    def _discover_rooms(self):
        if os.name == "nt":
            extension_rooms = []
            try:
                if self.extension_bridge is None:
                    from windows_extension_bridge import ExtensionBridge
                    self.extension_bridge = ExtensionBridge(supported_platform)
                extension_rooms = [BrowserTarget(
                    target_id=str(tab.tab_id), port=0, websocket_url="",
                    platform=tab.platform, room_number=tab.room_number,
                    url=tab.url, title=tab.title, ready=tab.ready,
                    logged_in=None, reason=tab.reason, source="extension",
                    tab_id=str(tab.tab_id), client_id=tab.client_id,
                ) for tab in self.extension_bridge.tabs()]
                self.extension_error = None
            except Exception as exc:
                self.extension_error = str(exc)
            cdp_rooms = []
            for endpoint in self.endpoints():
                try:
                    cdp_rooms.append(self.inspect(endpoint))
                except Exception as exc:
                    port, raw, platform, room = endpoint
                    cdp_rooms.append(BrowserTarget(
                        target_id=str(raw.get("id", "")), port=port,
                        websocket_url=raw["webSocketDebuggerUrl"], platform=platform,
                        room_number=room, url=str(raw.get("url", "")),
                        title=str(raw.get("title", "")), ready=False,
                        logged_in=None, reason=str(exc),
                    ))
            try:
                from windows_native_browser import NativeWindowsBrowser
                with self.native_lock:
                    native_rooms = NativeWindowsBrowser().discover(supported_platform)
                self.last_error = None
                native_targets = [BrowserTarget(
                    target_id=tab.tab_id, port=0, websocket_url="",
                    platform=tab.platform, room_number=tab.room_number,
                    url=tab.url, title=tab.title, ready=tab.ready,
                    logged_in=None, reason=tab.reason, source="windows",
                    window_handle=tab.window_handle, tab_id=tab.tab_id,
                ) for tab in native_rooms]
                preferred_urls = {target.url for target in extension_rooms}
                cdp_rooms = [target for target in cdp_rooms if target.url not in preferred_urls]
                preferred_urls.update(target.url for target in cdp_rooms)
                return extension_rooms + cdp_rooms + [
                    target for target in native_targets if target.url not in preferred_urls
                ]
            except Exception as exc:
                if extension_rooms or cdp_rooms:
                    self.last_error = None
                    return extension_rooms + cdp_rooms
                self.last_error = f"读取已打开的浏览器失败：{exc}"
                return []
        result = []
        for endpoint in self.endpoints():
            try:
                result.append(self.inspect(endpoint))
            except Exception as exc:
                port, raw, platform, room = endpoint
                result.append(BrowserTarget(
                    target_id=str(raw.get("id", "")), port=port,
                    websocket_url=raw["webSocketDebuggerUrl"], platform=platform,
                    room_number=room, url=str(raw.get("url", "")),
                    title=str(raw.get("title", "")), ready=False,
                    logged_in=None, reason=str(exc),
                ))
        return result

    def find_target(self, platform=None, room_number=None):
        candidates = self.rooms()
        if platform:
            candidates = [target for target in candidates if target.platform == platform]
        if room_number:
            candidates = [target for target in candidates if target.room_number == str(room_number)]
        if not candidates:
            return None
        ready = [target for target in candidates if target.ready]
        return (ready or candidates)[0]

    def viewing_room(self, *, refresh_native=True):
        bridge = self.extension_bridge
        view = bridge.current_view() if bridge else None
        if view is None:
            return self._native_viewing_room(refresh_native)
        platform, room = supported_platform(view["url"])
        if not platform:
            return None, "当前浏览器活动页不是直播间，自动跟随已暂停。"
        tab = next((tab for tab in bridge.tabs() if tab.client_id == view["clientId"]
                    and tab.tab_id == view["tabId"] and tab.url == view["url"]), None)
        target = BrowserTarget(
            target_id=str(view["tabId"]), port=0, websocket_url="",
            platform=platform, room_number=room, url=view["url"], title=view["title"],
            ready=bool(tab and tab.ready), logged_in=None,
            reason=tab.reason if tab else "等待直播页状态更新",
            source="extension", tab_id=str(view["tabId"]), client_id=view["clientId"],
        )
        return target, ""

    def _native_viewing_room(self, refresh):
        waiting = "等待浏览器活动页信息；请安装或重新加载新版浏览器扩展。"
        if os.name != "nt" or (not self.extension_bridge and not self._discovered_rooms):
            return None, waiting
        from windows_native_browser import NativeWindowsBrowser, frontmost_browser_window
        signature = frontmost_browser_window()
        if not signature:
            return None, "没有可见的浏览器窗口，自动跟随已暂停。"
        if not refresh:
            if signature == self._native_view_signature and time.monotonic() - self._native_view_time < 2:
                return self._native_view_cache
            return None, "正在确认当前浏览器活动页…"
        try:
            extension_tabs = self.extension_bridge.tabs() if self.extension_bridge else []
            # An already-running old extension still publishes the exact live-page
            # titles. Match only a unique title in the front browser window before
            # using UIA, which Chromium may not expose on this machine.
            title_matches = [item for item in extension_tabs
                             if _window_matches_page_title(signature[1], item.title)]
            if title_matches:
                longest = max(len(item.title) for item in title_matches)
                title_matches = [item for item in title_matches if len(item.title) == longest]
            if len(title_matches) == 1:
                result = (self._extension_view_target(title_matches[0], signature[0]),
                          "已通过 Windows 窗口识别活动直播页；重新加载扩展可启用精确跟随。")
                self._native_view_cache = result
                self._native_view_signature = signature
                self._native_view_time = time.monotonic()
                return result
            with self.native_lock:
                tab = NativeWindowsBrowser().active_tab(signature[0], supported_platform)
            if not tab:
                result = (None, "当前浏览器活动页不是直播间，自动跟随已暂停。")
            else:
                matching = [item for item in extension_tabs
                            if (item.platform, item.room_number) == (tab.platform, tab.room_number)]
                if len(matching) == 1:
                    result = (self._extension_view_target(matching[0], tab.window_handle),
                              "已通过 Windows 识别活动直播页；建议重新加载浏览器扩展。")
                elif len(matching) > 1:
                    result = (None, "同一房间打开了多个标签页，请重新加载扩展以区分当前标签页。")
                else:
                    known = next((item for item in self._discovered_rooms
                                  if item.source == "windows" and item.window_handle == tab.window_handle
                                  and item.tab_id == tab.tab_id and item.url == tab.url), None)
                    result = (known or BrowserTarget(
                        target_id=tab.tab_id, port=0, websocket_url="", platform=tab.platform,
                        room_number=tab.room_number, url=tab.url, title=tab.title,
                        ready=False, logged_in=None, reason=tab.reason, source="windows",
                        window_handle=tab.window_handle, tab_id=tab.tab_id,
                    ), "已通过 Windows 识别活动直播页。")
        except Exception as exc:
            result = (None, f"Windows 读取活动页失败：{exc}；请重新加载浏览器扩展。")
        self._native_view_cache = result
        self._native_view_signature = signature
        self._native_view_time = time.monotonic()
        return result

    @staticmethod
    def _extension_view_target(tab, handle=0):
        return BrowserTarget(
            target_id=str(tab.tab_id), port=0, websocket_url="",
            platform=tab.platform, room_number=tab.room_number, url=tab.url,
            title=tab.title, ready=tab.ready, logged_in=None, reason=tab.reason,
            source="extension", tab_id=str(tab.tab_id), client_id=tab.client_id,
            window_handle=handle,
        )

    def send(self, target, message, timeout=75, *, follow_active=False):
        if not isinstance(message, str) or not message.strip() or any(ord(char) < 32 for char in message):
            raise BrowserControlError("弹幕必须是非空单行文本")
        if follow_active:
            current, _ = self.viewing_room()
            if not current or (current.key, current.url) != (target.key, target.url):
                raise BrowserControlError("自动跟随的活动直播页已变化，未发送")
        if target.source == "extension":
            if self.extension_bridge is None:
                raise BrowserControlError("浏览器扩展连接未启动")
            job_id = f"extension-{time.time_ns()}"
            payload = {"expectedRoom": target.room_number,
                       "expectedPlatform": target.platform, "jobId": job_id,
                       "message": message}
            if follow_active:
                # Older extension workers still send correctly using the expected-room
                # guard; only request their new focus guard when that data is available.
                payload["followActive"] = self.extension_bridge.current_view() is not None
            result = self.extension_bridge.execute(
                target.client_id, int(target.tab_id), "send", payload, timeout=timeout,
            )
            if not isinstance(result, dict) or not result.get("ok"):
                raise BrowserControlError(str((result or {}).get("error", "网页拒绝发送")))
            if result.get("state") != "pending":
                return result
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.2)
                polled = self.extension_bridge.execute(
                    target.client_id, int(target.tab_id), "poll", payload,
                    timeout=max(1, deadline - time.monotonic()),
                )
                if isinstance(polled, dict) and polled.get("state") == "done":
                    if not polled.get("ok"):
                        raise BrowserControlError(str(polled.get("error", "弹幕发送失败")))
                    return polled
            raise BrowserControlError("等待网页发送结果超时")
        if target.source == "windows":
            from windows_native_browser import NativeTab, NativeWindowsBrowser
            native_target = NativeTab(
                target.window_handle, target.tab_id, "", target.url, target.title,
                target.platform, target.room_number, target.ready, target.reason,
            )
            with self.native_lock:
                return NativeWindowsBrowser().send(native_target, message, supported_platform)
        connection = CDPConnection(target.websocket_url, timeout=self.timeout * 4)
        try:
            job_id = f"windows-{time.time_ns()}"
            result = connection.evaluate(self._expression(target.platform, "send", {
                "expectedRoom": target.room_number, "expectedPlatform": target.platform,
                "jobId": job_id, "message": message,
            }))
            if not isinstance(result, dict) or not result.get("ok"):
                raise BrowserControlError(str((result or {}).get("error", "页面拒绝发送")))
            if result.get("state") != "pending":
                return result
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.2)
                polled = connection.evaluate(self._expression(target.platform, "poll", {
                    "expectedRoom": target.room_number, "expectedPlatform": target.platform,
                    "jobId": job_id,
                }))
                if isinstance(polled, dict) and polled.get("state") == "done":
                    if not polled.get("ok"):
                        raise BrowserControlError(str(polled.get("error", "弹幕发送失败")))
                    return polled
            raise BrowserControlError("等待网页发送结果超时")
        finally:
            connection.close()


def create_default_browser():
    return WindowsBrowser()
