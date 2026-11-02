import queue
import time
import unittest
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock, patch

from windows_app import WindowsControlPanel


class ImmediateThread:
    def __init__(self, target, daemon=True):
        self.target = target

    def start(self):
        self.target()


class VoiceQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(WindowsControlPanel)
        self.app.listening = True
        self.app.voice_send_busy = False
        self.app.voice_send_timer = None
        self.app.voice_waiting_for_room = False
        self.app.voice_inflight = None
        self.app.voice_pending = deque()
        self.app.voice_session = 1
        self.app.last_sent = 0.0
        self.app.interval = 20.0
        self.app.listening_target_key = "room-1"
        self.app.rooms = [SimpleNamespace(key="room-1", ready=True)]
        self.app.browser = SimpleNamespace(send=Mock(return_value={"ok": True, "state": "done"}))
        self.app.jobs = queue.Queue()
        self.app.root = SimpleNamespace(after=Mock(return_value="timer-1"))
        self.app._append_log = Mock()

    def test_recognized_sentences_wait_and_send_in_order(self):
        with patch("windows_app.threading.Thread", ImmediateThread):
            self.app._send_voice_sentence("第一句")
            self.app._send_voice_sentence("第二句")
            self.app._send_voice_sentence("第三句")
            self.assertEqual(self.app.browser.send.call_args_list[0].args[1], "第一句")
            self.assertEqual(list(self.app.voice_pending), ["第二句", "第三句"])

            self.app._finish_voice_send("第一句", {"ok": True}, None)
            self.app.last_sent = time.monotonic() - self.app.interval
            self.app._voice_timer_ready()
            self.app._finish_voice_send("第二句", {"ok": True}, None)
            self.app.last_sent = time.monotonic() - self.app.interval
            self.app._voice_timer_ready()
            self.assertEqual([call.args[1] for call in self.app.browser.send.call_args_list],
                             ["第一句", "第二句", "第三句"])

    def test_page_temporarily_unready_keeps_sentence(self):
        self.app.rooms[0].ready = False
        self.app._send_voice_sentence("等待页面的一句")
        self.assertEqual(list(self.app.voice_pending), ["等待页面的一句"])
        self.app.rooms[0].ready = True
        with patch("windows_app.threading.Thread", ImmediateThread):
            self.app._voice_timer_ready()
        self.assertEqual(self.app.browser.send.call_args.args[1], "等待页面的一句")

    def test_zero_interval_sends_next_sentence_after_previous_result(self):
        self.app.interval = 0.0
        with patch("windows_app.threading.Thread", ImmediateThread):
            self.app._send_voice_sentence("第一句")
            self.app._send_voice_sentence("第二句")
            self.app._finish_voice_send("第一句", {"ok": True}, None)
        self.assertEqual([call.args[1] for call in self.app.browser.send.call_args_list],
                         ["第一句", "第二句"])
        self.app.root.after.assert_not_called()

    def test_reselecting_same_room_does_not_flood_log(self):
        room = SimpleNamespace(key="room-1", ready=True)
        self.app.rooms = [room]
        self.app.selected_key = room.key
        self.app.rendering_rooms = False
        self.app.table = SimpleNamespace(selection=Mock(return_value=("0",)))
        self.app._select_room()
        self.app._append_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
