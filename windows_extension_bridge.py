"""Loopback bridge for the optional Chromium extension.

The extension reads all open tabs without changing the selected tab. Only
chrome-extension origins may publish snapshots or receive queued commands.
"""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading
import time
from urllib.parse import parse_qs, urlsplit


PORT = 8765
MAX_BODY = 1_000_000
SNAPSHOT_TIMEOUT = 90
VIEW_TIMEOUT = 4
COMMAND_WAIT_SECONDS = 5


@dataclass(frozen=True)
class ExtensionTab:
    client_id: str
    tab_id: int
    url: str
    title: str
    platform: str
    room_number: str
    ready: bool
    reason: str


class ExtensionBridge:
    def __init__(self, supported_platform, port=PORT):
        self.supported_platform = supported_platform
        self.lock = threading.Lock()
        self.command_ready = threading.Condition(self.lock)
        self.snapshots = {}
        self.views = {}
        self.commands = {}
        self.pending = {}
        self.next_id = 0
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _headers(self, code=200):
                self.send_response(code)
                origin = self.headers.get("Origin", "")
                if origin.startswith("chrome-extension://"):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()

            def _allowed(self):
                return self.headers.get("Origin", "").startswith("chrome-extension://")

            def _write(self, value, code=200):
                self._headers(code)
                self.wfile.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))

            def do_OPTIONS(self):
                self._headers(204 if self._allowed() else 403)

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path != "/commands":
                    self._write({"error": "not found"}, 404)
                    return
                client_id = parse_qs(parsed.query).get("clientId", [""])[0]
                if not client_id or len(client_id) > 120:
                    self._write({"error": "invalid client"}, 400)
                    return
                origin = self.headers.get("Origin", "")
                if origin:
                    allowed = self._allowed()
                else:
                    # Chromium may omit Origin on a GET from an extension with
                    # host permission. The client must have published a snapshot.
                    with bridge.lock:
                        allowed = client_id in bridge.snapshots
                if not allowed:
                    self._write({"error": "extension origin required"}, 403)
                    return
                deadline = time.monotonic() + COMMAND_WAIT_SECONDS
                with bridge.command_ready:
                    while not bridge.commands.get(client_id):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        bridge.command_ready.wait(remaining)
                    commands = bridge.commands.pop(client_id, [])
                self._write({"commands": commands})

            def do_POST(self):
                if not self._allowed():
                    self._write({"error": "extension origin required"}, 403)
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0 or length > MAX_BODY:
                    self._write({"error": "invalid request size"}, 400)
                    return
                try:
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    self._write({"error": "invalid JSON"}, 400)
                    return
                if self.path == "/snapshot":
                    bridge.publish(data)
                    self._write({"ok": True})
                elif self.path == "/view":
                    bridge.publish_view(data)
                    self._write({"ok": True, "current": bridge.current_view()})
                elif self.path == "/result":
                    bridge.complete(data)
                    self._write({"ok": True})
                else:
                    self._write({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def publish(self, data):
        client_id = data.get("clientId")
        tabs = data.get("tabs")
        if not isinstance(client_id, str) or not client_id or len(client_id) > 120 or not isinstance(tabs, list):
            return
        found = []
        for tab in tabs[:500]:
            if not isinstance(tab, dict) or not isinstance(tab.get("tabId"), int):
                continue
            url = tab.get("url", "")
            platform, room = self.supported_platform(url)
            if platform:
                found.append(ExtensionTab(
                    client_id, tab["tabId"], url, str(tab.get("title", ""))[:300],
                    platform, room, bool(tab.get("ready")), str(tab.get("reason", ""))[:300],
                ))
        with self.lock:
            self.snapshots[client_id] = (time.monotonic(), found)

    def tabs(self):
        now = time.monotonic()
        with self.lock:
            stale = [client_id for client_id, (seen, _) in self.snapshots.items()
                     if now - seen > SNAPSHOT_TIMEOUT]
            for client_id in stale:
                self.snapshots.pop(client_id, None)
            return [tab for _, tabs in self.snapshots.values() for tab in tabs]

    def connected(self):
        self.tabs()
        with self.lock:
            return bool(self.snapshots)

    def publish_view(self, data):
        client_id, tab_id = data.get("clientId"), data.get("tabId")
        active_at = data.get("lastActiveAt")
        if (not isinstance(client_id, str) or not client_id or len(client_id) > 120
                or type(tab_id) is not int or type(active_at) not in (int, float)
                or not 0 <= active_at <= time.time() * 1000 + 5000):
            return
        url = data.get("url", "")
        if not isinstance(url, str):
            return
        platform, _ = self.supported_platform(url)
        with self.lock:
            self.views[client_id] = (time.monotonic(), {
                "clientId": client_id, "tabId": tab_id, "lastActiveAt": active_at,
                "url": url if platform else "",
                "title": str(data.get("title", ""))[:300] if platform else "",
            })

    def current_view(self):
        now = time.monotonic()
        with self.lock:
            if not self.views:
                return None
            if len(self.views) > 1 and not any(view["lastActiveAt"] for _, view in self.views.values()):
                return None
            # Consider the most recently used browser first. If it disconnects, pause
            # instead of falling back to a live page left open in another browser.
            seen, view = max(self.views.values(), key=lambda item: item[1]["lastActiveAt"])
            return dict(view) if now - seen <= VIEW_TIMEOUT else None

    def complete(self, data):
        request_id = data.get("requestId")
        with self.lock:
            response = self.pending.get(request_id)
        if response:
            response.put(data.get("result"))

    def execute(self, client_id, tab_id, action, payload=None, timeout=20):
        response = queue.Queue(maxsize=1)
        with self.command_ready:
            self.next_id += 1
            request_id = str(self.next_id)
            self.pending[request_id] = response
            self.commands.setdefault(client_id, []).append({
                "requestId": request_id, "tabId": tab_id,
                "action": action, "payload": payload or {},
                "expiresAt": time.time() * 1000 + timeout * 1000,
            })
            self.command_ready.notify_all()
        try:
            result = response.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("浏览器扩展没有响应；请确认扩展已启用") from exc
        finally:
            with self.lock:
                self.pending.pop(request_id, None)
                queued = self.commands.get(client_id, [])
                self.commands[client_id] = [item for item in queued
                                            if item["requestId"] != request_id]
        return result
