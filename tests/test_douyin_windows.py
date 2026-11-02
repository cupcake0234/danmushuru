import json
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import danmu
from platforms.windows.douyin_windows import (ClientError, WindowsBackend, editor_metadata, field_text,
                            normalize_editor_value, room_in_url, run_action, send,
                            send_button_metadata)


class Field:
    def __init__(self, value=""):
        self.value = value

    def get_value(self):
        return self.value


class Page:
    room = "12345"
    url = "https://live.douyin.com/12345"

    def __init__(self, draft=""):
        self.field = Field(draft)
        self.matches = True

    def still_matches(self):
        return self.matches


class Backend:
    def __init__(self, page):
        self.page = page
        self.writes = []
        self.enters = 0
        self.has_focus = True
        self.restored = False
        self.after_write = lambda: None

    def discover(self):
        return self.page, []

    def foreground(self):
        return 1

    def focus(self, page):
        pass

    def focused(self, page):
        return self.has_focus

    def write(self, page, message):
        self.writes.append(message)
        page.field.value = message
        self.after_write()

    def enter(self, page):
        self.enters += 1

    def restore(self, previous, page):
        self.restored = True


class WindowsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.page = Page()
        self.backend = Backend(self.page)
        self.request = {"action": "send", "expectedPlatform": "douyin", "expectedRoom": "12345", "message": "测试 {字面} + ^ 😀"}

    def test_only_known_live_urls_identify_rooms(self):
        self.assertEqual(room_in_url("https://live.douyin.com/12345?ignored=1")[0], "12345")
        self.assertEqual(room_in_url("https://www.douyin.com/live/12345")[0], "12345")
        for url in ["https://live.douyin.com.evil.test/12345", "https://example.com/live/12345", "https://www.douyin.com/video/12345", "file://live.douyin.com/12345", "主播 12345", "https://live.douyin.com/１２３"]:
            with self.subTest(url=url):
                self.assertIsNone(room_in_url(url))

    def test_internal_and_public_ids_do_not_collide(self):
        identity = room_in_url("https://lf-test.bytegecko.com/live_pc_indicator_container_douyin/pages/index.html?room_id=12345&token=secret")
        self.assertEqual(identity[0], "internal-12345")
        self.assertNotIn("secret", identity[1])

    def test_single_trigger_keeps_literal_text(self):
        result = send(self.backend, self.page, self.request)
        self.assertEqual(result["confirmation"], "triggered")
        self.assertEqual(self.backend.writes, [self.request["message"]])
        self.assertEqual(self.backend.enters, 1)
        self.assertTrue(self.backend.restored)

    def test_draft_is_preserved(self):
        self.page.field.value = "手写草稿"
        with self.assertRaises(ClientError) as error:
            send(self.backend, self.page, self.request)
        self.assertEqual(error.exception.code, "DRAFT_PRESENT")
        self.assertEqual(self.page.field.value, "手写草稿")
        self.assertEqual(self.backend.writes, [])
        self.assertEqual(self.backend.enters, 0)

    def test_changed_room_before_input_does_not_write(self):
        self.page.matches = False
        result = run_action(self.request, self.backend)
        self.assertEqual(result["errorCode"], "ROOM_CHANGED")
        self.assertEqual(self.backend.writes, [])

    def test_room_change_after_input_does_not_submit_or_retry(self):
        self.backend.after_write = lambda: setattr(self.page, "matches", False)
        result = run_action(self.request, self.backend)
        self.assertEqual(result["errorCode"], "SEND_STATE_UNKNOWN")
        self.assertEqual(self.backend.enters, 0)
        self.assertEqual(len(self.backend.writes), 1)

    def test_focus_change_after_input_does_not_submit(self):
        self.backend.after_write = lambda: setattr(self.backend, "has_focus", False)
        result = run_action(self.request, self.backend)
        self.assertEqual(result["errorCode"], "SEND_STATE_UNKNOWN")
        self.assertEqual(self.backend.enters, 0)

    def test_missing_room_and_inspection_do_not_send(self):
        self.backend.page = None
        result = run_action({"action": "inspect"}, self.backend)
        self.assertTrue(result["ok"])
        self.assertFalse(result["ready"])
        result = run_action(self.request, self.backend)
        self.assertEqual(result["errorCode"], "NO_ROOM")
        self.assertEqual(self.backend.writes, [])

    def test_newlines_are_rejected_before_input(self):
        self.request["message"] = "第一条\n第二条"
        result = run_action(self.request, self.backend)
        self.assertEqual(result["errorCode"], "INVALID_MESSAGE")
        self.assertEqual(self.backend.writes, [])

    def test_unreadable_editor_does_not_mean_empty(self):
        with self.assertRaises(ClientError):
            field_text(object())


class PlatformCompatibilityTests(unittest.TestCase):
    def test_windows_uses_its_own_helper(self):
        with patch.object(danmu.sys, "platform", "win32"), patch.object(danmu, "run_douyin_windows_action", return_value={"ok": True}) as windows:
            self.assertTrue(danmu.run_douyin_action("inspect")["ok"])
            windows.assert_called_once_with("inspect")

    def test_macos_keeps_original_swift_helper(self):
        source = SimpleNamespace(stat=lambda: SimpleNamespace(st_mtime=1))
        binary = SimpleNamespace(exists=lambda: True, stat=lambda: SimpleNamespace(st_mtime=2), __str__=lambda: "helper")
        with patch.object(danmu.sys, "platform", "darwin"), patch.object(danmu, "DOUYIN_SOURCE_PATH", source), patch.object(danmu, "DOUYIN_BINARY_PATH", binary), patch.object(danmu, "run_douyin_windows_action") as windows, patch.object(danmu.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps({"ok": True}), "")) as process:
            self.assertTrue(danmu.run_douyin_action("inspect")["ok"])
            windows.assert_not_called()
            self.assertEqual(json.loads(process.call_args.kwargs["input"])["action"], "inspect")




class Control:
    def __init__(self, kind, name="", value=None, children=(), aria="", role=None, readonly=False):
        self.element_info = SimpleNamespace(control_type=kind, name=name,
            element=SimpleNamespace(CurrentIsKeyboardFocusable=kind == "Edit" or aria == "textbox",
                                    CurrentHelpText="", CurrentAriaRole=aria))
        self._children = list(children)
        if value is not None:
            self.iface_value = SimpleNamespace(CurrentValue=value, CurrentIsReadOnly=readonly)
        if role is not None:
            self.iface_legacy_iaccessible = SimpleNamespace(CurrentRole=role, CurrentState=0,
                CurrentName="", CurrentDescription="", CurrentHelp="")
        self.handle = 100
        if kind == "Button":
            self.iface_invoke = SimpleNamespace(Invoke=lambda: None)

    def children(self):
        return self._children

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def process_id(self):
        return 1


class ComposerDiscoveryTests(unittest.TestCase):
    def inspect(self, *controls):
        window = Control("Pane", children=controls)
        return WindowsBackend.__new__(WindowsBackend).inspect_window(window)

    def document(self, *children):
        return Control("Document", value="https://live.douyin.com/12345", children=children, readonly=True)

    def test_empty_name_with_value_placeholder_is_detected(self):
        editor = Control("Edit", value="与大家互动一下...")
        page, detail = self.inspect(self.document(editor))
        self.assertIs(page.field, editor)
        self.assertEqual(detail["matchingInputs"], 1)
        self.assertIn("valuePlaceholder", detail["inputCandidates"][0]["matchedBy"])

    def test_indicator_document_can_have_sibling_composer(self):
        indicator = Control("Document", value="https://lf-test.bytegecko.com/live_pc_indicator_container_douyin/pages/index.html?room_id=12345", readonly=True)
        editor = Control("Edit", value="与大家互动一下…")
        page, detail = self.inspect(indicator, editor)
        self.assertEqual(page.room, "internal-12345")
        self.assertIs(page.field, editor)

    def test_room_identity_is_preserved_without_composer(self):
        page, detail = self.inspect(self.document())
        self.assertEqual(page.room, "12345")
        self.assertIsNone(page.field)
        backend = Backend(page)
        result = run_action({"action": "inspect"}, backend)
        self.assertEqual(result["roomNumber"], "12345")
        self.assertFalse(result["ready"])
        self.assertEqual(backend.writes, [])

    def test_multiple_composers_do_not_select_first(self):
        page, detail = self.inspect(self.document(Control("Edit", "弹幕", ""), Control("Edit", "弹幕", "")))
        self.assertIsNone(page.field)
        self.assertEqual(detail["matchingInputs"], 2)

    def test_search_is_excluded_even_if_it_has_a_matching_value(self):
        search = Control("Edit", "搜索", "与大家互动一下...")
        page, detail = self.inspect(self.document(search))
        self.assertIsNone(page.field)
        self.assertTrue(detail["inputCandidates"][0]["excludedSearch"])

    def test_draft_text_is_not_used_as_a_placeholder_hint_or_logged(self):
        editor = Control("Edit", value="这是包含弹幕二字的私人草稿")
        page, detail = self.inspect(self.document(editor))
        self.assertIsNone(page.field)
        self.assertEqual(detail["matchingInputs"], 0)
        self.assertTrue(detail["inputCandidates"][0]["hasDraft"])
        self.assertNotIn(editor.iface_value.CurrentValue, json.dumps(detail, ensure_ascii=False))

    def test_known_child_placeholder_identifies_unnamed_editor(self):
        editor = Control("Edit", value="", children=[Control("Text", "与大家互动一下...")])
        page, detail = self.inspect(self.document(editor))
        self.assertIs(page.field, editor)
        self.assertIn("childPlaceholder", detail["inputCandidates"][0]["matchedBy"])

    def test_text_pattern_only_editor_can_read_and_preserve_draft(self):
        editor = Control("Document", "弹幕", aria="textbox", role=42)
        editor.iface_text = SimpleNamespace(DocumentRange=SimpleNamespace(GetText=lambda limit: "草稿\r"))
        self.assertEqual(field_text(editor), "草稿")
        metadata = editor_metadata(editor)
        self.assertTrue(metadata["readable"])
        self.assertTrue(metadata["hasDraft"])

    def test_static_or_readonly_content_is_not_an_editor(self):
        self.assertIsNone(editor_metadata(Control("Text", "弹幕")))
        self.assertIsNone(editor_metadata(Control("Edit", "弹幕", "", readonly=True)))

    def test_no_input_fails_without_typing(self):
        page, _ = self.inspect(self.document())
        backend = Backend(page)
        result = run_action({"action": "send", "expectedRoom": "12345", "message": "测试"}, backend)
        self.assertEqual(result["errorCode"], "NO_INPUT")
        self.assertEqual(backend.writes, [])

    def test_send_button_is_recognized_by_invoke_pattern(self):
        button = Control("Button", "发送")
        metadata = send_button_metadata(button)
        self.assertEqual(metadata["controlType"], "Button")
        self.assertIn("发送", metadata["matchedBy"])

    def test_disabled_send_button_remains_a_candidate(self):
        class DisabledButton(Control):
            def is_enabled(self):
                return False

        metadata = send_button_metadata(DisabledButton("Button", "发送"))
        self.assertFalse(metadata["enabledAtInspect"])

    def test_unique_unnamed_writable_control_is_used_when_empty(self):
        editor = Control("ListItem", value="")
        editor.element_info.element.CurrentIsKeyboardFocusable = True
        button = Control("Button", "发送")
        page, detail = self.inspect(self.document(editor, button))
        self.assertIs(page.field, editor)
        self.assertEqual(detail["matchingInputs"], 1)

    def test_legacy_default_action_is_supported_for_send_button(self):
        class LegacyButton(Control):
            def __init__(self):
                super().__init__("Custom", "发送")
                self.iface_invoke = None
                self.iface_legacy_iaccessible = SimpleNamespace(
                    CurrentName="发送", CurrentRole=0, CurrentState=0,
                    CurrentDescription="", CurrentHelp="",
                    DoDefaultAction=lambda: None,
                )

        metadata = send_button_metadata(LegacyButton())
        self.assertEqual(metadata["activationPattern"], "LegacyDefaultAction")




class EditorValueTests(unittest.TestCase):
    def test_empty_editor_markers_are_not_drafts(self):
        for value in ("\n", "\r\n", " \t\r\n", "\u200b", "\ufeff\n\u200c\u200d ", "\u00a0"):
            with self.subTest(value=repr(value)):
                self.assertEqual(normalize_editor_value(value), "")

    def test_known_placeholders_with_markers_are_empty(self):
        for value in ("与大家互动一下...\n", "\u200b与大家互动一下…\ufeff\r\n", " 说点什么... "):
            self.assertEqual(normalize_editor_value(value), "")

    def test_placeholder_words_inside_a_real_draft_are_preserved(self):
        for value in ("与大家互动一下...这是我的草稿", " 用户草稿 ", "\u200b用户草稿", "\ufffc"):
            self.assertEqual(normalize_editor_value(value), value)

    def test_provider_paragraph_terminators_do_not_change_message(self):
        message = "测试 👩\u200d💻 + {字面字符}"
        self.assertEqual(normalize_editor_value(message + "\r\n"), message)
        self.assertEqual(normalize_editor_value(message), message)

    def make_group_page(self, value):
        editor = Control("Group", value=value, children=[Control("Text", "与大家互动一下...")])
        editor.element_info.element.CurrentIsKeyboardFocusable = True
        document = Control("Document", value="https://live.douyin.com/12345", children=[editor], readonly=True)
        window = Control("Pane", children=[document])
        return WindowsBackend.__new__(WindowsBackend).inspect_window(window)

    def test_actual_group_shape_with_newline_is_ready(self):
        page, detail = self.make_group_page("\r\n")
        result = run_action({"action": "inspect"}, Backend(page))
        self.assertFalse(result["ready"])
        self.assertIn("发送按钮", result["reason"])
        self.assertFalse(detail["inputCandidates"][0]["hasDraft"])
        self.assertEqual(detail["inputCandidates"][0]["draftInfo"]["structuralCodes"], ["U+000A", "U+000D"])

    def test_actual_group_shape_keeps_user_draft_and_reports_reason(self):
        page, detail = self.make_group_page("手动草稿\r\n")
        backend = Backend(page)
        result = run_action({"action": "inspect"}, backend)
        self.assertFalse(result["ready"])
        self.assertIn("草稿", result["reason"])
        self.assertTrue(detail["inputCandidates"][0]["hasDraft"])
        self.assertNotIn("手动草稿", json.dumps(detail, ensure_ascii=False))
        result = run_action({"action": "send", "expectedRoom": "12345", "message": "测试"}, backend)
        self.assertEqual(result["errorCode"], "DRAFT_PRESENT")
        self.assertEqual(backend.writes, [])

    def test_group_placeholder_in_value_matches_without_children(self):
        editor = Control("Group", value="与大家互动一下...\r\n")
        editor.element_info.element.CurrentIsKeyboardFocusable = True
        metadata = editor_metadata(editor)
        self.assertIn("valuePlaceholder", metadata["matchedBy"])
        self.assertFalse(metadata["hasDraft"])

    def test_backend_uses_value_and_invoke_patterns(self):
        written = []
        invoked = []
        field = SimpleNamespace(iface_value=SimpleNamespace(
            CurrentIsReadOnly=False, SetValue=written.append))
        button = SimpleNamespace(is_enabled=lambda: True, iface_invoke=SimpleNamespace(
            Invoke=lambda: invoked.append(True)))
        page = SimpleNamespace(field=field, send_button=button)
        backend = WindowsBackend.__new__(WindowsBackend)
        backend.write(page, "hello")
        backend.enter(page)
        self.assertEqual(written, ["hello"])
        self.assertEqual(invoked, [True])


if __name__ == "__main__":
    unittest.main()
