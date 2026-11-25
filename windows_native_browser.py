"""Discover and operate already open Chromium tabs through Windows UI Automation."""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import sys


LIVE_HINTS = ("弹幕", "评论", "聊天", "说点什么", "互动", "danmu", "comment", "chat")
EXCLUDED_HINTS = ("搜索", "search", "验证码", "手机号", "password", "gift", "礼物")
SEND_HINTS = ("发送", "发布", "send")
BROWSER_NAMES = {"msedge.exe": "Edge", "chrome.exe": "Chrome"}


class NativeBrowserError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeTab:
    window_handle: int
    tab_id: str
    browser: str
    url: str
    title: str
    platform: str
    room_number: str
    ready: bool
    reason: str = ""


def _name(control):
    try:
        return str(control.element_info.name or "")
    except Exception:
        return ""


def _property(control, name, default=""):
    try:
        return getattr(control.element_info, name) or default
    except Exception:
        return default


def _value(control):
    for getter in (
        lambda: control.iface_value.CurrentValue,
        lambda: control.iface_legacy_iaccessible.CurrentValue,
    ):
        try:
            result = getter()
            if isinstance(result, str):
                return result
        except Exception:
            pass
    return None


def _selected(tab):
    try:
        return bool(tab.iface_selection_item.CurrentIsSelected)
    except Exception:
        return False


def _tab_id(tab):
    try:
        return ":".join(map(str, tab.element_info.element.GetRuntimeId()))
    except Exception:
        return _name(tab)


def _controls(window):
    return window.descendants()


def _inside_document(control):
    try:
        parent = control.parent()
        for _ in range(20):
            if parent is None:
                break
            if _property(parent, "control_type") == "Document":
                return True
            parent = parent.parent()
    except Exception:
        pass
    return False


def _address(window):
    candidates = []
    for item in window.descendants(control_type="Edit"):
        identity = (_name(item) + " " + _property(item, "automation_id")).lower()
        if "omnibox" in identity or "address" in identity or "地址" in identity or "搜索栏" in identity:
            candidates.append(item)
    for item in candidates:
        value = _value(item)
        if value:
            if value.startswith(("https://", "http://")):
                return value
            if value.startswith(("live.bilibili.com/", "www.douyu.com/", "douyu.com/",
                                 "live.douyin.com/", "www.douyin.com/live/")):
                return "https://" + value
    return ""


def _tab_address(tab):
    """Use a URL exposed on the tab itself, without selecting it."""
    values = [_name(tab)]
    try:
        values.append(str(tab.element_info.element.CurrentHelpText or ""))
    except Exception:
        pass
    try:
        values.append(str(tab.iface_legacy_iaccessible.CurrentDescription or ""))
    except Exception:
        pass
    value = _value(tab)
    if value:
        values.append(value)
    for value in values:
        value = value.strip()
        if value.startswith(("https://", "http://")):
            return value
    return ""


def _composer(window):
    editors = []
    buttons = []
    documents = window.descendants(control_type="Document")
    if not documents:
        return None, None, "浏览器未提供直播页控件"
    for item in documents[0].descendants():
        kind = _property(item, "control_type")
        identity = (_name(item) + " " + _property(item, "automation_id") +
                    " " + _property(item, "class_name")).lower()
        try:
            identity += " " + str(item.element_info.element.CurrentHelpText or "").lower()
        except Exception:
            pass
        if any(hint in identity for hint in EXCLUDED_HINTS):
            continue
        if kind in ("Edit", "Document"):
            try:
                aria = str(item.element_info.element.CurrentAriaRole or "").lower()
            except Exception:
                aria = ""
            if kind == "Edit" or aria == "textbox":
                if any(hint in identity for hint in LIVE_HINTS):
                    editors.append(item)
        if kind == "Button" and any(hint in identity for hint in SEND_HINTS):
            try:
                if item.is_visible():
                    buttons.append(item)
            except Exception:
                pass
    if len(editors) != 1 or len(buttons) != 1:
        reason = "未找到唯一的弹幕输入框和发送按钮"
        return None, None, reason
    return editors[0], buttons[0], ""


def _process_name(pid):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        path = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(path))
        if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return path.value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def frontmost_browser_window():
    """Read Z order only: the front browser stays first when the panel takes focus."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetTopWindow.argtypes = [wintypes.HWND]
    user32.GetTopWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    handle = user32.GetTopWindow(None)
    seen = set()
    while handle and handle not in seen:
        seen.add(handle)
        if user32.IsWindowVisible(handle) and not user32.IsIconic(handle):
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(handle, class_name, len(class_name))
            if class_name.value == "Chrome_WidgetWin_1":
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
                if _process_name(pid.value) in BROWSER_NAMES:
                    title = ctypes.create_unicode_buffer(1024)
                    user32.GetWindowTextW(handle, title, len(title))
                    return int(handle), title.value
        handle = user32.GetWindow(handle, 2)  # GW_HWNDNEXT, never activate/select.
    return None


class NativeWindowsBrowser:
    def __init__(self):
        if sys.platform != "win32":
            raise NativeBrowserError("界面自动化仅支持 Windows")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise NativeBrowserError("缺少 pywinauto，请安装 requirements.txt") from exc
        self.desktop = Desktop(backend="uia")

    def _windows(self):
        for window in self.desktop.windows():
            try:
                browser = BROWSER_NAMES.get(_process_name(window.process_id()))
                if browser and window.class_name() == "Chrome_WidgetWin_1":
                    yield window, browser
            except Exception:
                continue

    def _tabs(self, window):
        return [item for item in window.descendants(control_type="TabItem")
                if not _inside_document(item) and
                (_selected(item) or hasattr(item, "iface_selection_item"))]

    def _window(self, handle):
        for window, _ in self._windows():
            if window.handle == handle:
                return window
        raise NativeBrowserError("浏览器窗口已关闭")

    def active_tab(self, handle, supported_platform):
        window = self.desktop.window(handle=handle).wrapper_object()
        url = _address(window)
        platform, room = supported_platform(url)
        if not platform:
            return None
        tab = next((tab for tab in self._tabs(window) if _selected(tab)), None)
        if tab is None:
            raise NativeBrowserError("浏览器没有提供活动标签页信息")
        return NativeTab(handle, _tab_id(tab), "", url, _name(tab), platform, room,
                         False, "等待直播页状态更新")

    def discover(self, supported_platform):
        result = []
        for window, browser in self._windows():
            try:
                tabs = self._tabs(window)
            except Exception:
                continue
            for tab in tabs:
                try:
                    active = _selected(tab)
                    url = _address(window) if active else _tab_address(tab)
                    platform, room = supported_platform(url)
                    if not platform:
                        continue
                    if active:
                        _, _, reason = _composer(window)
                    else:
                        reason = "后台标签页无法通过 Windows 控件发送；请将它设为活动标签页"
                    result.append(NativeTab(
                        window.handle, _tab_id(tab), browser, url, _name(tab),
                        platform, room, not bool(reason), reason,
                    ))
                except Exception:
                    continue
        return result

    def send(self, target, message, supported_platform):
        if not isinstance(message, str) or not message.strip() or any(ord(ch) < 32 for ch in message):
            raise NativeBrowserError("弹幕必须是非空单行文本")
        window = self._window(target.window_handle)
        tabs = self._tabs(window)
        tab = next((tab for tab in tabs if _tab_id(tab) == target.tab_id), None)
        if tab is None:
            raise NativeBrowserError("直播标签页已关闭")
        if not _selected(tab):
            raise NativeBrowserError("目标直播页不再是活动标签页，未发送；请切回该标签页")
        platform, room = supported_platform(_address(window))
        if (platform, room) != (target.platform, target.room_number):
            raise NativeBrowserError("直播标签页已切换房间，未发送")
        editor, button, reason = _composer(window)
        if reason:
            raise NativeBrowserError(reason)
        current = _value(editor)
        if current is None:
            raise NativeBrowserError("无法读取弹幕输入框，未发送")
        if current.strip(" \t\r\n\u200b\ufeff"):
            raise NativeBrowserError("输入框已有草稿，未覆盖")
        try:
            pattern = editor.iface_value
            if pattern.CurrentIsReadOnly:
                raise NativeBrowserError("弹幕输入框不可写")
            pattern.SetValue(message)
        except NativeBrowserError:
            raise
        except Exception as exc:
            raise NativeBrowserError("无法写入网页弹幕输入框") from exc
        if _value(editor) != message:
            raise NativeBrowserError("无法确认弹幕输入成功，未发送")
        if supported_platform(_address(window)) != (target.platform, target.room_number):
            raise NativeBrowserError("直播房间在输入后变化，未发送")
        if not button.is_enabled():
            raise NativeBrowserError("发送按钮仍不可用；弹幕可能留在输入框中")
        try:
            button.iface_invoke.Invoke()
        except Exception as exc:
            raise NativeBrowserError("网页发送按钮无法调用；弹幕可能仍在输入框中") from exc
        return {"ok": True, "state": "done", "confirmation": "triggered"}
