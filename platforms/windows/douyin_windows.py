"""Windows-only Douyin UI Automation backend (no cookies or private API)."""

from collections import deque
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import json
import re
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

MAX_ELEMENTS = 2500
MAX_DIAGNOSTIC_ELEMENTS = 1000


class GUIThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


ENUM_CHILD_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PLACEHOLDERS = {"与大家互动一下...", "与大家互动一下…", "说点什么...", "说点什么…", "发送弹幕"}
INPUT_HINTS = ("互动", "弹幕", "说点什么")
SEND_HINTS = ("发送", "send")


class ClientError(RuntimeError):
    def __init__(self, message, code="CLIENT_ERROR"):
        super().__init__(message)
        self.code = code


def room_in_url(raw):
    """Accept only known live document URLs, never unrelated numeric text."""
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        url = urlsplit(raw if "://" in raw else "https://" + raw)
        host = (url.hostname or "").lower()
        if url.scheme not in ("http", "https"):
            return None
        if host in {"douyin.com", "www.douyin.com", "live.douyin.com"}:
            parts = url.path.strip("/").split("/")
            if host == "live.douyin.com" and len(parts) == 1 and re.fullmatch(r"[0-9]+", parts[0]):
                return parts[0], "https://live.douyin.com/" + parts[0]
            if len(parts) == 2 and parts[0] == "live" and re.fullmatch(r"[0-9]+", parts[1]):
                return parts[1], "https://live.douyin.com/" + parts[1]
        if host == "bytegecko.com" or host.endswith(".bytegecko.com"):
            values = parse_qs(url.query).get("room_id", [])
            if "/live_pc_indicator_container_douyin/pages/" in url.path and len(values) == 1:
                if re.fullmatch(r"[0-9]+", values[0]):
                    return "internal-" + values[0], "https://" + host + url.path + "?room_id=" + values[0]
    except ValueError:
        return None
    return None


EDITOR_EMPTY_MARKERS = "\u200b\u200c\u200d\ufeff"


def normalize_editor_value(value):
    """Ignore empty scaffolding and known hints, preserving actual draft text."""
    # Strip mixed whitespace/markers at the edges only for empty/placeholder tests.
    hint = re.sub(r"^[\s\u200b\u200c\u200d\ufeff]+|[\s\u200b\u200c\u200d\ufeff]+$", "", value)
    if not hint or hint in PLACEHOLDERS:
        return ""
    # Text/Value providers can append a paragraph terminator to visible contents.
    # Preserve spaces, zero-width chars in real drafts, and emoji joiners.
    return value.rstrip("\r\n")


def read_field_value(field):
    """Read real contents through Value, MSAA or Text, never through the label."""
    readers = (
        ("getValue", lambda: field.get_value()),
        ("value", lambda: field.iface_value.CurrentValue),
        ("legacyValue", lambda: field.iface_legacy_iaccessible.CurrentValue),
        ("text", lambda: field.iface_text.DocumentRange.GetText(-1)),
    )
    for source, reader in readers:
        try:
            value = reader()
        except Exception:
            continue
        if isinstance(value, str):
            return value, source
    raise ClientError("无法读取弹幕输入框内容，已停止，避免覆盖草稿。", "UNREADABLE_INPUT")


def field_text(field):
    value, _ = read_field_value(field)
    return normalize_editor_value(value)


def draft_summary(value, source):
    """Describe editor scaffolding without exposing a draft or its text."""
    contents = normalize_editor_value(value)
    codes = {f"U+{ord(char):04X}" for char in value
             if char.isspace() or char in EDITOR_EMPTY_MARKERS or char == "\ufffc"}
    return {"source": source, "rawLength": len(value), "contentLength": len(contents),
            "blankOrPlaceholder": not bool(contents), "structuralCodes": sorted(codes)}


def control_property(element, name, default=None):
    try:
        return getattr(element.element_info.element, name)
    except Exception:
        return default


def element_info_property(element, name, default=""):
    try:
        value = getattr(element.element_info, name)
    except Exception:
        return default
    return default if value is None else value


def pattern_metadata(element):
    """Return UIA pattern availability and text lengths without exposing text."""
    patterns = []
    value_length = text_length = legacy_length = None
    try:
        value = element.iface_value
        patterns.append("Value")
        try:
            current = value.CurrentValue
            value_length = len(current) if isinstance(current, str) else None
        except Exception:
            pass
    except Exception:
        value = None
    try:
        text = element.iface_text
        patterns.append("Text")
        try:
            current = text.DocumentRange.GetText(-1)
            text_length = len(current) if isinstance(current, str) else None
        except Exception:
            pass
    except Exception:
        text = None
    try:
        legacy = element.iface_legacy_iaccessible
        patterns.append("LegacyIAccessible")
        try:
            current = legacy.CurrentValue
            legacy_length = len(current) if isinstance(current, str) else None
        except Exception:
            pass
        if callable(getattr(legacy, "DoDefaultAction", None)):
            patterns.append("LegacyDefaultAction")
    except Exception:
        legacy = None
    for name, label in (("iface_invoke", "Invoke"), ("iface_selection_item", "SelectionItem"),
                        ("iface_toggle", "Toggle"), ("iface_range_value", "RangeValue")):
        try:
            if getattr(element, name) is not None:
                patterns.append(label)
        except Exception:
            pass
    return {"patterns": sorted(set(patterns)), "valueLength": value_length,
            "textLength": text_length, "legacyValueLength": legacy_length}


def control_diagnostic(element):
    """Describe a UIA element without returning any value or document text."""
    info = pattern_metadata(element)
    try:
        legacy = element.iface_legacy_iaccessible
        role = int(legacy.CurrentRole)
    except Exception:
        role = None
    name = str(element_info_property(element, "name", "") or "")[:200]
    return {
        "controlType": str(element_info_property(element, "control_type", "") or ""),
        "name": name,
        "automationId": str(element_info_property(element, "automation_id", "") or "")[:200],
        "className": str(element_info_property(element, "class_name", "") or "")[:200],
        "legacyRole": role,
        "ariaRole": str(control_property(element, "CurrentAriaRole", "") or ""),
        "visible": bool(element.is_visible()),
        "enabled": bool(element.is_enabled()),
        "focusable": bool(control_property(element, "CurrentIsKeyboardFocusable", False)),
        **info,
    }


def editor_metadata(element):
    """Recognize editable controls and collect known hints without logging drafts."""
    kind = element_info_property(element, "control_type", "")
    role, legacy = None, None
    try:
        legacy = element.iface_legacy_iaccessible
        role = int(legacy.CurrentRole)
    except Exception:
        pass
    focusable = bool(control_property(element, "CurrentIsKeyboardFocusable", False))
    aria_role = str(control_property(element, "CurrentAriaRole", "") or "").lower()
    value_pattern = None
    try:
        value_pattern = element.iface_value
        read_only = bool(value_pattern.CurrentIsReadOnly)
    except Exception:
        read_only = None
    if read_only is None and role == 42:
        try:
            read_only = bool(int(legacy.CurrentState) & 0x40)
        except Exception:
            pass
    editable = kind in {"Edit", "Document"} or role == 42 or aria_role in {"textbox", "searchbox"}
    editable = editable or (focusable and read_only is False and value_pattern is not None)
    if not editable:
        return None
    if not element.is_visible() or not element.is_enabled() or read_only is True:
        return None

    labels = {"name": element.element_info.name or "",
              "help": control_property(element, "CurrentHelpText", "") or ""}
    if legacy is not None:
        for key, attribute in (("legacyName", "CurrentName"), ("description", "CurrentDescription"), ("legacyHelp", "CurrentHelp")):
            try:
                labels[key] = getattr(legacy, attribute) or ""
            except Exception:
                pass
    matched_by = [key for key, label in labels.items() if any(hint in str(label) for hint in INPUT_HINTS)]
    # Only exact known placeholders can supply evidence from the field's value.
    for key, reader in (("valuePlaceholder", lambda: value_pattern.CurrentValue),
                        ("legacyPlaceholder", lambda: legacy.CurrentValue),
                        ("textPlaceholder", lambda: element.iface_text.DocumentRange.GetText(-1).rstrip("\r\n"))):
        try:
            value = reader()
            if isinstance(value, str) and normalize_editor_value(value) == "" and any(char not in EDITOR_EMPTY_MARKERS and not char.isspace() for char in value):
                matched_by.append(key)
        except Exception:
            pass
    try:
        for child in element.children():
            if child.element_info.control_type == "Text" and child.element_info.name in PLACEHOLDERS:
                matched_by.append("childPlaceholder")
                break
    except Exception:
        pass
    # An explicitly labelled search field is never the live composer.
    excluded = aria_role == "searchbox" or any(
        word in str(label).lower() for label in labels.values() for word in ("搜索", "查找", "search")
    )
    try:
        value, source = read_field_value(element)
        info = draft_summary(value, source)
        readable, has_draft = True, bool(normalize_editor_value(value))
    except ClientError:
        readable, has_draft, info = False, None, None
    return {"controlType": kind, "legacyRole": role, "focusable": focusable,
            "writable": value_pattern is not None and read_only is not True,
            "matchedBy": sorted(set(matched_by)), "excludedSearch": excluded,
            "readable": readable, "hasDraft": has_draft, "draftInfo": info}


def document_room(element):
    """Chromium may expose its document URL through LegacyIAccessible.Value."""
    values = [element.element_info.name or ""]
    try:
        values.append(element.iface_value.CurrentValue)
    except Exception:
        pass
    try:
        values.append(element.iface_legacy_iaccessible.CurrentValue)
    except Exception:
        pass
    for value in values:
        identity = room_in_url(value)
        if identity:
            return identity
    return None


@dataclass
class LivePage:
    window: Any
    source: Any
    field: Any
    room: str
    url: str
    send_button: Any = None

    def still_matches(self):
        identity = document_room(self.source)
        return identity is not None and identity[0] == self.room


def send_button_metadata(element):
    """Recognize a button labelled as the live comment submit action."""
    kind = element_info_property(element, "control_type", "")
    labels = [element_info_property(element, "name", ""),
              element_info_property(element, "automation_id", ""),
              element_info_property(element, "class_name", ""),
              control_property(element, "CurrentAriaRole", "")]
    try:
        labels.append(element.iface_legacy_iaccessible.CurrentName or "")
    except Exception:
        pass
    try:
        labels.append(element.element_info.element.CurrentHelpText or "")
    except Exception:
        pass
    pending = deque([(element, 0)])
    while pending:
        current, depth = pending.popleft()
        if current is not element:
            labels.extend((element_info_property(current, "name", ""),
                           element_info_property(current, "automation_id", ""),
                           control_property(current, "CurrentAriaRole", "")))
        if depth < 3:
            try:
                pending.extend((child, depth + 1) for child in current.children())
            except Exception:
                pass
    matched_by = [label for label in labels if any(hint in str(label).lower() for hint in SEND_HINTS)]
    if not matched_by or not element.is_visible():
        return None
    patterns = pattern_metadata(element)["patterns"]
    activation = "Invoke" if "Invoke" in patterns else "LegacyDefaultAction" if "LegacyDefaultAction" in patterns else None
    if activation is None:
        return None
    return {"controlType": element.element_info.control_type,
            "matchedBy": sorted(set(matched_by)), "enabledAtInspect": element.is_enabled(),
            "activationPattern": activation}


def invoke_button(element):
    """Activate a button through UIA, never through mouse or keyboard input."""
    try:
        element.iface_invoke.Invoke()
        return
    except Exception as invoke_error:
        try:
            legacy = element.iface_legacy_iaccessible
            action = getattr(legacy, "DoDefaultAction")
            action()
            return
        except Exception as legacy_error:
            raise legacy_error from invoke_error


class WindowsBackend:
    def __init__(self):
        if sys.platform != "win32":
            raise ClientError("Windows 抖音模块只能在 Windows 上运行。", "UNSUPPORTED_PLATFORM")
        try:
            from pywinauto import Desktop
            from pywinauto.uia_defines import IUIA
        except ImportError as exc:
            raise ClientError("缺少 Windows 控件依赖，请运行 python -m pip install -r requirements.txt。", "MISSING_DEPENDENCY") from exc
        self.desktop = Desktop(backend="uia")
        self.uia = IUIA().iuia
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUIThreadInfo)]
        self.user32.GetGUIThreadInfo.restype = wintypes.BOOL
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.restype = ctypes.c_int
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.restype = wintypes.BOOL
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUM_CHILD_PROC, wintypes.LPARAM]
        self.user32.EnumChildWindows.restype = wintypes.BOOL

    def child_window_handles(self, hwnd):
        handles = []

        @ENUM_CHILD_PROC
        def callback(child, _):
            handles.append(int(child))
            return True

        self.user32.EnumChildWindows(hwnd, callback, 0)
        return handles

    def native_window_metadata(self, hwnd):
        class_name = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, class_name, len(class_name))
        self.user32.GetWindowTextW(hwnd, title, len(title))
        process_id = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        return {"handle": int(hwnd), "pid": int(process_id.value),
                "className": class_name.value, "title": title.value,
                "visible": bool(self.user32.IsWindowVisible(hwnd))}

    def focused_chain(self, window):
        if not hasattr(self, "uia"):
            return []
        try:
            focused = self.uia.GetFocusedElement()
            process_id = wintypes.DWORD()
            thread_id = self.user32.GetWindowThreadProcessId(window.handle, ctypes.byref(process_id))
            if thread_id:
                gui_info = GUIThreadInfo(cbSize=ctypes.sizeof(GUIThreadInfo))
                if self.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)) and gui_info.hwndFocus:
                    try:
                        focused = self.uia.ElementFromHandle(gui_info.hwndFocus)
                    except Exception:
                        pass
            from pywinauto.controls.uiawrapper import UIAWrapper
            from pywinauto.uia_element_info import UIAElementInfo
            current = focused
            chain = []
            for _ in range(32):
                wrapper = UIAWrapper(UIAElementInfo(current))
                native_handle = control_property(wrapper, "CurrentNativeWindowHandle", 0) or 0
                if native_handle and int(native_handle) != int(window.handle):
                    break
                chain.append(wrapper)
                current = self.uia.RawViewWalker.GetParentElement(current)
                if current is None:
                    break
            return chain
        except Exception:
            return []

    def process_name(self, pid):
        handle = self.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(path))
            if self.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                return path.value.replace("\\", "/").rsplit("/", 1)[-1].lower()
            return ""
        finally:
            self.kernel32.CloseHandle(handle)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def restore(self, previous, page):
        # Do not steal focus back after the user switches to another app.
        if previous and previous != page.window.handle and self.foreground() == page.window.handle:
            self.user32.SetForegroundWindow(previous)

    def focused(self, page):
        if self.foreground() != page.window.handle:
            return False
        focused = self.uia.GetFocusedElement()
        return bool(self.uia.CompareElements(focused, page.field.element_info.element))

    def focus(self, page):
        page.window.set_focus()
        page.field.set_focus()
        time.sleep(0.08)
        if not self.focused(page):
            raise ClientError("无法确认弹幕输入框获得焦点，未发送。", "FOCUS_FAILED")

    def write(self, page, message):
        try:
            value = page.field.iface_value
            if bool(value.CurrentIsReadOnly):
                raise ClientError("抖音弹幕输入框为只读控件，未发送。", "NO_VALUE_PATTERN")
            value.SetValue(message)
        except ClientError:
            raise
        except Exception as exc:
            raise ClientError("无法通过 ValuePattern 写入抖音弹幕输入框，未发送。", "NO_VALUE_PATTERN") from exc

    def enter(self, page):
        if page.send_button is None:
            raise ClientError("未找到唯一的抖音弹幕发送按钮，未发送。", "NO_SEND_BUTTON")
        try:
            deadline = time.monotonic() + 1
            while not page.send_button.is_enabled() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not page.send_button.is_enabled():
                raise ClientError("弹幕内容已写入，但发送按钮仍不可用，未发送。", "SEND_DISABLED")
            invoke_button(page.send_button)
        except ClientError:
            raise
        except Exception as exc:
            raise ClientError("无法通过 UI Automation 调用抖音弹幕发送按钮，发送状态未知。", "SEND_STATE_UNKNOWN") from exc


    def inspect_window(self, window, verbose=False):
        stack = deque([(window, None, 0)])
        documents, editors, candidates, candidate_elements, senders, tree = [], [], [], [], [], []
        focused_chain = self.focused_chain(window)
        count, errors = 0, 0
        deadline = time.monotonic() + 4
        while stack and count < MAX_ELEMENTS and time.monotonic() < deadline:
            element, scope, depth = stack.popleft()
            count += 1
            try:
                kind = element.element_info.control_type
                if verbose and len(tree) < MAX_DIAGNOSTIC_ELEMENTS:
                    item = control_diagnostic(element)
                    item["depth"] = depth
                    tree.append(item)
                if kind == "Document":
                    identity = document_room(element)
                    if identity:
                        scope = (element, identity)
                        documents.append(scope)
                metadata = editor_metadata(element)
                if metadata is not None:
                    candidates.append(metadata)
                    candidate_elements.append((element, scope))
                    if (metadata["matchedBy"] and not metadata["excludedSearch"]
                            and metadata["writable"]):
                        editors.append((element, scope))
                button = send_button_metadata(element)
                if button is not None:
                    senders.append((element, scope, button))
                stack.extend((child, scope, depth + 1) for child in element.children())
            except Exception:
                errors += 1
        truncated = bool(stack)
        focused_scope = None
        for focused_element in focused_chain:
            identity = document_room(focused_element)
            if identity:
                focused_scope = (focused_element, identity)
                if not any(self.uia.CompareElements(focused_element.element_info.element, source.element_info.element)
                           for source, _ in documents):
                    documents.append(focused_scope)
        if focused_chain:
            focused_element = focused_chain[0]
            focused_metadata = editor_metadata(focused_element)
            if focused_metadata is not None and focused_scope is not None:
                duplicate = False
                for existing, _ in candidate_elements:
                    try:
                        if self.uia.CompareElements(focused_element.element_info.element,
                                                    existing.element_info.element):
                            duplicate = True
                            break
                    except Exception:
                        pass
                if not duplicate:
                    candidates.append(focused_metadata)
                    candidate_elements.append((focused_element, focused_scope))
                    if (not focused_metadata["excludedSearch"] and focused_metadata["writable"]
                            and (focused_metadata["matchedBy"] or focused_metadata["hasDraft"])):
                        editors.append((focused_element, focused_scope))
        pages = []
        for field, scope in editors:
            # Indicator document and composer can be siblings in the client.
            if scope is None and len(documents) == 1:
                scope = documents[0]
            if scope:
                source, (room, url) = scope
                scoped_senders = [button for button, button_scope, _ in senders
                                  if button_scope is scope or (button_scope is None and len(documents) == 1)]
                pages.append(LivePage(window, source, field, room, url,
                                      scoped_senders[0] if len(scoped_senders) == 1 else None))
        diagnostic = {"pid": window.process_id(), "handle": window.handle, "elements": count,
                      "documents": len(documents), "matchingInputs": len(editors), "readErrors": errors,
                      "truncated": truncated, "roomFound": bool(documents), "composerFound": len(pages) == 1,
                      "sendButtonFound": len(senders) == 1,
                      "urls": list(dict.fromkeys(identity[1] for _, identity in documents)),
                      "inputFields": len(candidates), "inputCandidates": candidates[:20],
                      "sendButtonCandidates": [metadata for _, _, metadata in senders[:20]]}
        if verbose:
            diagnostic["controlTree"] = tree
            diagnostic["controlTreeTruncated"] = count > MAX_DIAGNOSTIC_ELEMENTS or truncated
            diagnostic["focusedChain"] = ([control_diagnostic(element) for element in focused_chain]
                                            if focused_scope is not None else [])
        # A partial tree or several candidate composers cannot select a safe target.
        if not truncated and not pages:
            # If Chromium omitted both the placeholder and accessible name,
            # select one unique empty writable field. Drafts are never used as
            writable_empty = []
            for element, scope in candidate_elements:
                metadata = editor_metadata(element)
                if (metadata and metadata["writable"] and metadata["readable"]
                        and not metadata["hasDraft"] and not metadata["excludedSearch"]):
                    writable_empty.append((element, scope))
            if len(writable_empty) == 1:
                editors = writable_empty
                field, scope = editors[0]
                if scope is None and len(documents) == 1:
                    scope = documents[0]
                if scope:
                    source, (room, url) = scope
                    scoped_senders = [button for button, button_scope, _ in senders
                                      if button_scope is scope or (button_scope is None and len(documents) == 1)]
                    pages.append(LivePage(window, source, field, room, url,
                                          scoped_senders[0] if len(scoped_senders) == 1 else None))
            diagnostic["matchingInputs"] = len(editors)
            diagnostic["composerFound"] = len(pages) == 1
        if not truncated and len(pages) == 1:
            return pages[0], diagnostic
        # Keep a proven room identity visible even when its composer is unavailable.
        identities = {identity[0] for _, identity in documents}
        if not truncated and len(identities) == 1:
            source, (room, url) = documents[0]
            return LivePage(window, source, None, room, url), diagnostic
        return None, diagnostic

    def discover(self, verbose=False):
        pages, diagnostics = [], []
        process_names = {}
        for window in self.desktop.windows(visible_only=False):
            try:
                pid = window.process_id()
                if pid not in process_names:
                    process_names[pid] = self.process_name(pid)
                if process_names[pid] != "douyin.exe":
                    continue
                if not window.is_visible():
                    diagnostics.append({"pid": pid, "handle": window.handle, "visible": False,
                                        "reason": "抖音主窗口已隐藏，请从任务栏或托盘打开主窗口并进入直播间。"})
                    continue
                handles = [window.handle]
                try:
                    handles.extend(self.child_window_handles(window.handle))
                except Exception:
                    pass
                native_info = []
                for child_handle in handles[1:1001]:
                    try:
                        native_info.append(self.native_window_metadata(child_handle))
                    except Exception:
                        pass
                native_children = native_info if verbose else []
                native_classes = {item["handle"]: item.get("className", "") for item in native_info}
                seen_handles = set()
                inspected_children = 0
                for handle in handles:
                    if handle in seen_handles:
                        continue
                    seen_handles.add(handle)
                    if handle != window.handle and "Intermediate D3D Window" in native_classes.get(handle, ""):
                        continue
                    if handle != window.handle:
                        if inspected_children >= 8:
                            continue
                        inspected_children += 1
                    candidate = window if handle == window.handle else self.desktop.window(handle=handle)
                    try:
                        candidate_pid = candidate.process_id()
                        page, detail = self.inspect_window(candidate, verbose=verbose)
                    except Exception as exc:
                        diagnostics.append({"pid": pid, "handle": handle, "error": type(exc).__name__})
                        continue
                    if verbose and handle == window.handle:
                        detail["nativeChildren"] = native_children
                        detail["renderingSurfaceOnly"] = bool(native_children) and all(
                            "D3D" in str(item.get("className", "")) for item in native_children
                        ) and not detail.get("roomFound")
                    diagnostics.append(detail)
                    if page:
                        pages.append(page)
            except Exception as exc:
                diagnostics.append({"error": type(exc).__name__})
        grouped = {}
        for page in pages:
            grouped.setdefault(page.room, []).append(page)
        pages = []
        for room_pages in grouped.values():
            field_pages = [page for page in room_pages if page.field is not None]
            unique_fields = []
            for page in field_pages:
                duplicate = False
                for previous in unique_fields:
                    try:
                        if self.uia.CompareElements(page.field.element_info.element,
                                                    previous.field.element_info.element):
                            duplicate = True
                            break
                    except Exception:
                        pass
                if not duplicate:
                    unique_fields.append(page)
            pages.extend(unique_fields or room_pages)
        active = [page for page in pages if page.window.handle == self.foreground()]
        page = active[0] if len(active) == 1 else pages[0] if len(pages) == 1 else None
        return page, diagnostics


def send(backend, page, request):
    message = request.get("message")
    if not isinstance(message, str) or not message.strip() or any(ord(c) < 32 for c in message):
        raise ClientError("弹幕必须是非空的单行文本，不能包含换行或控制字符。", "INVALID_MESSAGE")
    if request.get("expectedPlatform") not in (None, "douyin") or request.get("expectedRoom") != page.room:
        raise ClientError("直播间已切换，取消旧房间弹幕。", "ROOM_CHANGED")
    if not page.still_matches():
        raise ClientError("直播间已关闭或切换。", "ROOM_CHANGED")
    if page.field is None:
        raise ClientError("直播间已识别，但未找到唯一弹幕输入框；请运行 --diagnose 查看编辑控件。", "NO_INPUT")
    if field_text(page.field):
        raise ClientError("弹幕输入框已有草稿，未覆盖、未发送。", "DRAFT_PRESENT")
    if hasattr(page, "send_button") and page.send_button is None:
        raise ClientError("未找到唯一的抖音弹幕发送按钮，未发送。", "NO_SEND_BUTTON")
    previous = backend.foreground()
    editing = False
    try:
        backend.focus(page)
        if not page.still_matches():
            raise ClientError("聚焦时直播间已切换。", "ROOM_CHANGED")
        if field_text(page.field):
            raise ClientError("输入框出现了新草稿，未覆盖。", "DRAFT_PRESENT")
        if not backend.focused(page):
            raise ClientError("输入框焦点已变化，未发送。", "FOCUS_FAILED")
        editing = True
        backend.write(page, message)
        # React processes native input asynchronously.
        deadline = time.monotonic() + 1
        while field_text(page.field) != message and time.monotonic() < deadline:
            time.sleep(0.05)
        if field_text(page.field) != message:
            raise ClientError("输入框内容与弹幕不一致，未调用发送按钮；请检查草稿。", "SEND_STATE_UNKNOWN")
        if not page.still_matches() or not backend.focused(page):
            raise ClientError("输入后房间或焦点变化，未调用发送按钮；请检查草稿。", "SEND_STATE_UNKNOWN")
        backend.enter(page)
        return {"ok": True, "state": "done", "platform": "douyin", "roomNumber": page.room,
                "confirmation": "triggered"}
    except ClientError:
        raise
    except Exception as exc:
        code = "SEND_STATE_UNKNOWN" if editing else "CLIENT_ERROR"
        raise ClientError("客户端操作失败，已停止；请检查弹幕和草稿，不会自动重试。", code) from exc
    finally:
        try:
            backend.restore(previous, page)
        except Exception:
            pass


def run_action(request, backend=None):
    action = request.get("action")
    if action not in {"inspect", "diagnose", "send"}:
        return {"ok": False, "errorCode": "INVALID_ACTION", "error": "不支持的 Windows 抖音操作。"}
    try:
        backend = backend or WindowsBackend()
        try:
            page, diagnostics = backend.discover(verbose=action == "diagnose")
        except TypeError as exc:
            if "verbose" not in str(exc):
                raise
            page, diagnostics = backend.discover()
        result = {"ok": True, "platform": "douyin", "url": page.url if page else "",
                  "roomNumber": page.room if page else None, "loggedIn": None,
                  "ready": False, "diagnostics": diagnostics}
        if page and page.field is not None:
            try:
                if not page.still_matches():
                    result["reason"] = "检查时直播间已变化，请重新检查。"
                elif hasattr(page, "send_button") and page.send_button is None and not field_text(page.field):
                    result["reason"] = "未找到唯一的抖音弹幕发送按钮；请用 --diagnose 查看 sendButtonCandidates。"
                elif field_text(page.field):
                    result["reason"] = "弹幕输入框存在非空内容，已保留草稿；若界面只有占位提示，请查看 inputCandidates 中的 draftInfo。"
                else:
                    result["ready"] = True
            except ClientError as exc:
                result["reason"] = str(exc)
        if page and page.field is None:
            result["reason"] = "直播间已识别，但未找到唯一弹幕输入框；请用 --diagnose 查看 inputCandidates。"
        if action in {"inspect", "diagnose"}:
            if not result["ready"] and "reason" not in result:
                if (diagnostics and any(item.get("renderingSurfaceOnly") for item in diagnostics)
                        and not any(item.get("roomFound") for item in diagnostics)):
                    result["reason"] = "抖音客户端当前只暴露 D3D 渲染表面，未暴露直播页面、弹幕输入框或发送按钮的 UI Automation 接口；无法在不模拟鼠标键盘的前提下发送。"
                    return result
                result["reason"] = ("抖音主窗口已隐藏，请打开主窗口并进入直播间。"
                                    if diagnostics and all(item.get("visible") is False for item in diagnostics)
                                    else "未找到唯一直播间和可用弹幕输入框，或输入框已有草稿。")
            return result
        if page is None:
            raise ClientError("没有找到唯一可用的抖音直播间；请先运行 --inspect 或 --diagnose。", "NO_ROOM")
        return send(backend, page, request)
    except ClientError as exc:
        return {"ok": False, "errorCode": exc.code, "error": str(exc), "state": "done"}
    except Exception as exc:
        return {"ok": False, "errorCode": "CLIENT_ERROR", "error": "Windows 控件读取失败：" + type(exc).__name__, "state": "done"}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    try:
        request = json.load(sys.stdin)
        result = run_action(request) if isinstance(request, dict) else {"ok": False, "error": "请求必须是 JSON 对象。"}
    except (ValueError, TypeError):
        result = {"ok": False, "error": "请求 JSON 格式无效。"}
    print(json.dumps(result, ensure_ascii=False))
