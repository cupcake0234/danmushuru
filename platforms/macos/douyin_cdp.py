"""Read-only probe for a Douyin desktop client started with a local CDP port.

This module does not read cookies or send messages. It is kept separate from
the working Accessibility sender until the client protocol is verified.
"""

import argparse
import json
import time
from urllib.parse import urlparse
from urllib.request import urlopen

import websocket


class CDPError(RuntimeError):
    pass


def live_room(url: str):
    parsed = urlparse(url)
    if parsed.hostname not in {"douyin.com", "www.douyin.com", "live.douyin.com"}:
        return None
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "live.douyin.com" and len(parts) == 1 and parts[0].isdigit():
        return parts[0]
    for index, part in enumerate(parts[:-1]):
        if part == "live" and parts[index + 1].isdigit():
            return parts[index + 1]
    return None


def live_targets(port: int):
    if not 1024 <= port <= 65535:
        raise CDPError("端口必须在 1024 到 65535 之间。")
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
            targets = json.load(response)
    except (OSError, ValueError) as exc:
        raise CDPError("无法连接抖音客户端的本机调试端口。") from exc
    if not isinstance(targets, list):
        raise CDPError("调试端口返回格式不正确。")
    result = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        room = live_room(str(target.get("url", "")))
        ws_url = target.get("webSocketDebuggerUrl")
        if not room or not isinstance(ws_url, str):
            continue
        parsed_ws = urlparse(ws_url)
        if parsed_ws.scheme != "ws" or parsed_ws.hostname not in {"127.0.0.1", "localhost", "::1"}:
            continue
        result.append((room, target, ws_url))
    return result


def evaluate(ws_url: str, expression: str):
    try:
        connection = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
        try:
            connection.send(json.dumps({
                "id": 1, "method": "Runtime.evaluate",
                "params": {"expression": expression, "returnByValue": True,
                           "awaitPromise": True}
            }))
            while True:
                payload = json.loads(connection.recv())
                if payload.get("id") == 1:
                    break
        finally:
            connection.close()
    except (OSError, websocket.WebSocketException, ValueError) as exc:
        raise CDPError("读取客户端页面失败。") from exc
    if "error" in payload:
        raise CDPError("客户端拒绝调试请求：" + str(payload["error"].get("message", "未知错误")))
    result = payload.get("result", {})
    if "exceptionDetails" in result:
        raise CDPError("客户端页面执行检查失败。")
    return result.get("result", {}).get("value")


def capture_request_paths(ws_url: str, seconds: int):
    """Observe request methods and paths; never print headers, query values or bodies."""
    try:
        connection = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
        connection.settimeout(1)
        try:
            connection.send(json.dumps({"id": 2, "method": "Network.enable", "params": {}}))
            deadline = time.monotonic() + seconds
            seen = set()
            while time.monotonic() < deadline:
                try:
                    event = json.loads(connection.recv())
                except websocket.WebSocketTimeoutException:
                    continue
                if event.get("method") != "Network.requestWillBeSent":
                    continue
                request = event.get("params", {}).get("request", {})
                url = urlparse(str(request.get("url", "")))
                method = str(request.get("method", ""))
                host = url.hostname or ""
                if not (host.endswith(".douyin.com") or host.endswith(".bytedance.com")):
                    continue
                if method != "POST" and not any(
                    word in url.path.lower() for word in ("chat", "comment", "webcast")
                ):
                    continue
                item = (method, host, url.path)
                if item in seen:
                    continue
                seen.add(item)
                print(json.dumps({"method": method, "host": host, "path": url.path},
                                 ensure_ascii=False), flush=True)
                if len(seen) >= 40:
                    break
        finally:
            connection.close()
    except (OSError, websocket.WebSocketException, ValueError) as exc:
        raise CDPError("监听客户端请求失败。") from exc


PROBE_SCRIPT = """(() => ({
  href: location.href,
  fullscreen: Boolean(document.fullscreenElement),
  editors: Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"]'))
    .map(el => ({tag: el.tagName, placeholder: el.getAttribute('placeholder') || '',
                 label: el.getAttribute('aria-label') || '',
                 editable: el.getAttribute('contenteditable') || '',
                 connected: el.isConnected}))
    .filter(el => /互动|弹幕|评论/.test(el.placeholder + el.label) || el.editable === 'true')
}))()"""


def main():
    parser = argparse.ArgumentParser(description="只读检查抖音客户端内嵌直播页的调试接口")
    parser.add_argument("--port", type=int, required=True, help="抖音启动时指定的本机调试端口")
    parser.add_argument("--capture-seconds", type=int, default=0,
                        help="只读监听指定秒数的请求路径；不记录请求内容")
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 120:
        parser.error("--capture-seconds 必须在 0 到 120 之间")
    try:
        targets = live_targets(args.port)
        if not targets:
            print("调试端口可连接，但没有找到抖音直播页面。")
            return 1
        for room, target, ws_url in targets:
            page = evaluate(ws_url, PROBE_SCRIPT)
            print(json.dumps({"room": room, "targetType": target.get("type"),
                              "page": page}, ensure_ascii=False, indent=2))
            if args.capture_seconds:
                capture_request_paths(ws_url, args.capture_seconds)
        return 0
    except CDPError as exc:
        print("错误：" + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
