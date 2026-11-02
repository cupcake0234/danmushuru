import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from windows_browser import supported_platform
from windows_extension_bridge import ExtensionBridge


class ExtensionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = ExtensionBridge(supported_platform, port=0)
        self.base = f"http://127.0.0.1:{self.bridge.server.server_port}"
        self.origin = "chrome-extension://abcdefghijklmnop"

    def tearDown(self):
        self.bridge.close()

    def request(self, path, value=None, *, origin=True):
        body = None if value is None else json.dumps(value).encode()
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = self.origin
        request = Request(self.base + path, data=body, headers=headers)
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_snapshot_filters_to_live_tabs_and_command_round_trip(self):
        self.request("/snapshot", {"clientId": "edge-profile", "tabs": [
            {"tabId": 11, "url": "https://live.bilibili.com/123", "title": "直播", "ready": True},
            {"tabId": 12, "url": "https://example.com/", "title": "其他", "ready": True},
        ]})
        tabs = self.bridge.tabs()
        self.assertEqual([(tab.tab_id, tab.room_number) for tab in tabs], [(11, "123")])

        results = []
        worker = threading.Thread(target=lambda: results.append(
            self.bridge.execute("edge-profile", 11, "inspect", timeout=2)
        ))
        worker.start()
        try:
            # Wait until the command is queued, then emulate the extension.
            for _ in range(100):
                with self.bridge.lock:
                    queued = bool(self.bridge.commands.get("edge-profile"))
                if queued:
                    break
                threading.Event().wait(0.01)
            commands = self.request("/commands?clientId=edge-profile", origin=False)["commands"]
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0]["tabId"], 11)
            self.request("/result", {"requestId": commands[0]["requestId"],
                                     "result": {"ok": True, "ready": True}})
        finally:
            worker.join(timeout=3)
        self.assertEqual(results, [{"ok": True, "ready": True}])

    def test_no_origin_requires_published_client(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/commands?clientId=unknown", origin=False)
        self.assertEqual(caught.exception.code, 403)

    def test_waiting_extension_receives_new_command_immediately(self):
        received = []
        poller = threading.Thread(target=lambda: received.extend(
            self.request("/commands?clientId=edge-profile")["commands"]
        ))
        poller.start()
        time.sleep(0.05)
        results = []
        sender = threading.Thread(target=lambda: results.append(
            self.bridge.execute("edge-profile", 11, "inspect", timeout=2)
        ))
        sender.start()
        poller.join(timeout=1)
        self.assertFalse(poller.is_alive(), "queued command did not wake the extension")
        self.assertEqual(len(received), 1)
        self.request("/result", {"requestId": received[0]["requestId"],
                                 "result": {"ok": True}})
        sender.join(timeout=2)
        self.assertEqual(results, [{"ok": True}])


if __name__ == "__main__":
    unittest.main()
