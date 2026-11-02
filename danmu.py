#!/usr/bin/env python3
"""Send text to live rooms in macOS browsers or the macOS/Windows Douyin client."""

import argparse
from collections import deque
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from voice import VoiceError, VoiceStream, list_input_devices
from windows_browser import BrowserControlError, WindowsBrowser


BROWSERS = {
    "edge": ("Microsoft Edge", "/Applications/Microsoft Edge.app"),
    "chrome": ("Google Chrome", "/Applications/Google Chrome.app"),
    "safari": ("Safari", "/Applications/Safari.app"),
}
PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPT_PATH = PROJECT_ROOT / "web_actions" / "browser_actions.js"
DOUYU_SCRIPT_PATH = PROJECT_ROOT / "web_actions" / "douyu_actions.js"
DOUYIN_SOURCE_PATH = PROJECT_ROOT / "platforms" / "macos" / "douyin_ax.swift"
DOUYIN_BINARY_PATH = Path(__file__).with_name(".venv") / "bin" / "douyin_ax"


class BrowserError(RuntimeError):
    pass


class BrowserUnavailable(BrowserError):
    pass


class RoomChanged(BrowserError):
    pass


class SendStateUnknown(BrowserError):
    pass


def run_windows_browser_action(action: str, **kwargs: Any) -> Dict[str, Any]:
    browser = WindowsBrowser()
    platform = kwargs.get("expectedPlatform")
    room_number = kwargs.get("expectedRoom")
    target = browser.find_target(platform=platform, room_number=room_number)
    if action == "inspect":
        if target is None:
            return {
                "ok": True, "platform": None, "roomNumber": None, "url": "",
                "ready": False, "loggedIn": None,
                "reason": browser.last_error or "未发现支持的网页直播间。",
            }
        return target.as_result()
    if target is None:
        return {"ok": False, "errorCode": "NO_ROOM", "error": "未发现匹配的网页直播间。"}
    if action == "send":
        try:
            return browser.send(target, kwargs.get("message", ""))
        except BrowserControlError as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "errorCode": "UNSUPPORTED_ACTION", "error": f"不支持的网页操作：{action}"}


def run_douyin_windows_action(action: str, **kwargs: Any) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "platforms" / "windows" / "douyin_windows.py")],
            input=json.dumps({"action": action, **kwargs}, ensure_ascii=False),
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BrowserError("Windows 抖音操作失败或超时；请检查输入框和弹幕，不会自动重试。") from exc
    if result.returncode:
        raise BrowserError("Windows 抖音辅助程序失败：" + result.stderr[-1000:])
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise BrowserError("无法解析 Windows 抖音辅助程序结果。") from exc
    if not isinstance(data, dict):
        raise BrowserError("Windows 抖音辅助程序返回格式不正确。")
    return data


def run_douyin_action(action: str, **kwargs: Any) -> Dict[str, Any]:
    if sys.platform == "win32":
        return run_douyin_windows_action(action, **kwargs)
    if not DOUYIN_BINARY_PATH.exists() or (
        DOUYIN_SOURCE_PATH.stat().st_mtime > DOUYIN_BINARY_PATH.stat().st_mtime
    ):
        print("正在编译抖音客户端辅助程序（首次运行可能需要约一分钟）……", file=sys.stderr)
        DOUYIN_BINARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = Path(tempfile.gettempdir()) / "danmushuru-swift-cache"
        cache.mkdir(exist_ok=True)
        import os
        environment = os.environ.copy()
        environment["CLANG_MODULE_CACHE_PATH"] = str(cache / "clang")
        environment["SWIFT_MODULECACHE_PATH"] = str(cache / "swift")
        try:
            built = subprocess.run(
                ["xcrun", "swiftc", str(DOUYIN_SOURCE_PATH), "-o", str(DOUYIN_BINARY_PATH)],
                capture_output=True, text=True, timeout=180, env=environment, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise BrowserError(f"无法编译抖音客户端辅助程序：{exc}") from exc
        if built.returncode:
            raise BrowserError("编译抖音客户端辅助程序失败：" + built.stderr[-1800:])
    request = {"action": action, **kwargs}
    try:
        result = subprocess.run(
            [str(DOUYIN_BINARY_PATH)], input=json.dumps(request, ensure_ascii=False),
            capture_output=True, text=True, timeout=20, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserError("抖音客户端操作超过 20 秒，发送状态未知；请检查弹幕记录和输入框，脚本不会自动重试。") from exc
    if result.returncode:
        raise BrowserError("抖音客户端辅助程序运行失败：" + result.stderr[-1000:])
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise BrowserError("无法解析抖音客户端返回结果。") from exc
    if not isinstance(data, dict):
        raise BrowserError("抖音客户端返回格式不正确。")
    return data


def run_action(browser: str, action: str, **kwargs: Any) -> Dict[str, Any]:
    if browser == "douyin":
        return run_douyin_action(action, **kwargs)
    if sys.platform == "win32" and browser in ("edge", "chrome"):
        return run_windows_browser_action(action, **kwargs)
    if sys.platform != "darwin":
        raise BrowserError("网页浏览器发送目前支持带 CDP 端口的 Windows Edge/Chrome 或 macOS 浏览器。")
    payload = json.dumps({"action": action, **kwargs}, ensure_ascii=True)
    javascript = SCRIPT_PATH.read_text(encoding="utf-8").replace("__PAYLOAD_JSON__", payload)
    javascript = " ".join(javascript.splitlines())
    douyu_javascript = DOUYU_SCRIPT_PATH.read_text(encoding="utf-8").replace(
        "__PAYLOAD_JSON__", payload
    )
    douyu_javascript = " ".join(douyu_javascript.splitlines())
    app_name, app_path = BROWSERS[browser]
    tab_expression = "window.currentTab()" if browser == "safari" else "window.activeTab()"
    run_expression = (
        "app.doJavaScript(jsCode, {in: targetTab})" if browser == "safari" else
        "targetTab.execute({javascript: jsCode})"
    )
    fallback = {
        "ok": action == "inspect",
        "url": "",
        "fullscreen": False,
        "roomNumber": None,
        "loggedIn": False,
        "ready": False,
        "errorCode": "ROOM_CHANGED" if action != "inspect" else None,
        "error": "当前活动标签页不是支持的直播间。" if action != "inspect" else None,
    }
    script = "\n".join([
        "var app = Application(" + json.dumps(app_path) + ");",
        "if (!app.running()) throw new Error('浏览器未运行');",
        "var windows = app.windows();",
        "if (!windows.length) throw new Error('浏览器没有窗口');",
        "var window = windows[0];",
        "var targetTab = " + tab_expression + ";",
        "var biliCode = " + json.dumps(javascript, ensure_ascii=True) + ";",
        "var douyuCode = " + json.dumps(douyu_javascript, ensure_ascii=True) + ";",
        "var tabUrl = '';",
        "try { tabUrl = String(targetTab.url()); } catch (error) {}",
        "var fallback = " + json.dumps(fallback, ensure_ascii=True) + ";",
        "fallback.url = tabUrl;",
        "var site = /^https:\\/\\/live\\.bilibili\\.com\\//.test(tabUrl) ? 'bilibili' : "
        "(/^https:\\/\\/www\\.douyu\\.com\\//.test(tabUrl) ? 'douyu' : '');",
        "var expectedSite = " + json.dumps(kwargs.get("expectedPlatform")) + ";",
        "var jsCode = site === 'bilibili' ? biliCode : douyuCode;",
        "var jsResult = site && (!expectedSite || expectedSite === site) ? " +
        run_expression + " : JSON.stringify(fallback);",
        "String(jsResult);",
    ])
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True, text=True, timeout=20, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserError("浏览器响应超时；请确认直播页仍然打开。") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        if "浏览器未运行" in detail:
            raise BrowserUnavailable(f"{app_name} 当前未运行。")
        if "浏览器没有窗口" in detail:
            raise BrowserUnavailable(f"{app_name} 当前没有窗口。")
        raise BrowserError(
            f"无法操作 {app_name}：{detail}\n"
            "请启用浏览器菜单中的‘允许来自 Apple Events 的 JavaScript’，"
            "并允许终端/Python 控制浏览器。"
        )
    try:
        data = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise BrowserError(f"浏览器返回了无法解析的结果：{result.stdout[:200]!r}") from exc
    if not isinstance(data, dict):
        raise BrowserError("浏览器返回格式不正确。")
    return data


def read_lines(path: Path):
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise BrowserError(f"无法读取文本文件：{exc}") from exc
    messages = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not messages:
        raise BrowserError("文本文件没有可发送的内容；每行写一条弹幕。")
    return messages


def current_room(browser: str):
    try:
        page = run_action(browser, "inspect")
    except BrowserUnavailable:
        return None
    if not page.get("ok"):
        raise BrowserError(str(page.get("error", "检查直播页失败")))
    if page.get("ready") and page.get("platform") in ("bilibili", "douyu", "douyin"):
        return f"{page['platform']}:{page['roomNumber']}"
    return None


def room_target(value: str):
    platform, separator, room_number = value.partition(":")
    if not separator or platform not in ("bilibili", "douyu", "douyin") or not room_number:
        raise BrowserError(f"无效的直播间标识：{value}")
    return platform, room_number


def wait_for_job(browser: str, job_id: str, expected_room: str, timeout: float = 25) -> Dict[str, Any]:
    platform, room_number = room_target(expected_room)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            result = run_action(
                browser, "poll", jobId=job_id,
                expectedRoom=room_number, expectedPlatform=platform
            )
        except BrowserUnavailable as exc:
            raise SendStateUnknown("浏览器在发送过程中关闭；本条发送结果未知，未重试。") from exc
        if result.get("state") == "done":
            return result
        if result.get("state") != "pending":
            if result.get("errorCode") in ("ROOM_CHANGED", "NO_ROOM", "JOB_LOST"):
                raise SendStateUnknown("直播间在发送过程中切换；本条发送结果未知，未重试。")
            raise BrowserError(str(result.get("error", "发送状态未知")))
    raise BrowserError("等待接口结果超时；可能已经发出，脚本不会自动重试。")


def send_message(browser: str, expected_room: str, message: str) -> Dict[str, Any]:
    platform, room_number = room_target(expected_room)
    job_id = uuid.uuid4().hex
    try:
        started = run_action(
            browser, "send", expectedRoom=room_number,
            expectedPlatform=platform, jobId=job_id, message=message
        )
    except BrowserUnavailable as exc:
        raise RoomChanged("当前没有可用的直播间。") from exc
    if not started.get("ok"):
        if started.get("errorCode") in ("ROOM_CHANGED", "NO_ROOM", "APP_UNAVAILABLE"):
            raise RoomChanged(str(started.get("error", "直播间已切换")))
        raise BrowserError(str(started.get("error", "发送任务未开始")))
    result = started if started.get("state") == "done" else wait_for_job(browser, job_id, expected_room)
    if not result.get("ok"):
        if result.get("errorCode") == "ROOM_CHANGED":
            raise RoomChanged(str(result.get("error", "直播间已切换")))
        raise BrowserError(str(result.get("error", "接口返回失败")))
    return result


def split_message(text: str, max_chars: int):
    text = text.strip()
    result = []
    while len(text) > max_chars:
        window = text[:max_chars]
        cuts = [window.rfind(mark) + 1 for mark in "，。！？；,.!?; "]
        cut = max(cuts)
        if cut < max_chars // 2:
            cut = max_chars
        result.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        result.append(text)
    return [part for part in result if part]


def run_microphone(args):
    if not args.transcribe_only:
        target = "抖音客户端" if args.browser == "douyin" else BROWSERS[args.browser][0]
        print(f"发送目标：{target}")
    stream = VoiceStream(device_index=args.input_device, silence_ms=args.silence_ms)
    pending = deque()
    last_sent = None
    sent_count = 0
    recognized_count = 0
    active_room = None
    room_known = False
    last_checked = 0.0

    def refresh_room(force=False):
        nonlocal active_room, room_known, last_checked
        if not force and time.monotonic() - last_checked < 0.75:
            return active_room
        room = current_room(args.browser)
        last_checked = time.monotonic()
        if not room_known or room != active_room:
            dropped = len(pending) + stream.discard_pending()
            pending.clear()
            active_room = room
            room_known = True
            if room:
                print(f"当前直播间：{room}，开始发送新识别的语音。")
            else:
                print("当前没有可发送的直播间；继续监听，暂不发送。")
            if dropped:
                print(f"房间变化，已丢弃 {dropped} 条待发送内容。")
        return active_room

    try:
        stream.start()
        print("麦克风识别已启动。说完一句并短暂停顿后处理；按 Ctrl+C 停止。")
        if args.transcribe_only:
            while not args.limit or recognized_count < args.limit:
                sentence = stream.get_sentence()
                if sentence:
                    recognized_count += 1
                    print("识别完成：" + sentence)
            print("语音任务完成。")
            return
        refresh_room(force=True)
        while True:
            if args.limit and sent_count >= args.limit:
                break
            refresh_room()
            if active_room is None:
                sentence = stream.get_sentence()
                if sentence:
                    print("没有直播间，跳过：" + sentence)
                continue
            if not pending:
                sentence = stream.get_sentence()
                if sentence is None:
                    continue
                previous_room = active_room
                refresh_room(force=True)
                if active_room != previous_room:
                    print("房间已切换，跳过刚识别的内容。")
                    continue
                recognized_count += 1
                print("识别完成：" + sentence)
                pending.extend(split_message(sentence, args.max_chars))
            if not pending:
                continue
            if last_sent is not None:
                remaining = args.interval - (time.monotonic() - last_sent)
                if remaining > 0:
                    if stream.error:
                        raise VoiceError(stream.error)
                    time.sleep(min(remaining, 0.25))
                    continue
            if stream.error:
                raise VoiceError(stream.error)
            previous_room = active_room
            refresh_room(force=True)
            if active_room != previous_room or active_room is None:
                continue
            part = pending[0]
            try:
                result = send_message(args.browser, active_room, part)
            except (RoomChanged, SendStateUnknown) as exc:
                dropped = len(pending) + stream.discard_pending()
                pending.clear()
                print(f"直播间发生变化：{exc} 已丢弃 {dropped} 条待发送内容。")
                refresh_room(force=True)
                continue
            pending.popleft()
            sent_count += 1
            last_sent = time.monotonic()
            status = "已触发发送" if result.get("confirmation") == "triggered" else "已发送"
            print(f"{status}第 {sent_count} 条：{part}")
        print("语音任务完成。")
    finally:
        stream.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="持续把麦克风语音发送到浏览器直播间或抖音客户端；也可指定文本文件。")
    parser.add_argument("file", nargs="?", type=Path, help="UTF-8 文本文件，每行一条弹幕")
    parser.add_argument("--browser", choices=[*BROWSERS, "douyin"], default="edge",
                        help="发送目标；edge/chrome/safari 为网页，douyin 为 macOS/Windows 抖音客户端")
    parser.add_argument("--message", help="发送一条指定文本；与文本文件和 --mic 互斥")
    parser.add_argument("--interval", type=float, default=20.0, help="两条弹幕之间的秒数，最少 10 秒")
    parser.add_argument("--inspect", action="store_true", help="只检查当前页面、房间号和登录状态，不发送")
    parser.add_argument("--diagnose", action="store_true", help="检查抖音客户端的辅助功能控件结构，不发送")
    parser.add_argument("--limit", type=int, default=0, help="最多发送的条数；0 表示文件中的全部")
    parser.add_argument("--mic", action="store_true", help="持续识别麦克风语音并自动发送（不提供文件时默认）")
    parser.add_argument("--transcribe-only", action="store_true", help="麦克风模式只显示识别文本，不发送")
    parser.add_argument("--list-input-devices", action="store_true", help="列出可用麦克风设备")
    parser.add_argument("--input-device", type=int, help="麦克风设备编号；默认优先使用系统输入设备，排除常见回传设备")
    parser.add_argument("--silence-ms", type=int, default=800, help="一句话结束的静音时长，200–6000 毫秒")
    parser.add_argument("--max-chars", type=int, default=20, help="语音弹幕每条最多字符数，默认 20")
    parser.add_argument("--gui", action="store_true", help="Windows 网页直播控制面板")
    args = parser.parse_args()
    if args.gui:
        if sys.platform != "win32":
            parser.error("--gui 仅适用于 Windows")
        from windows_app import main as windows_main
        windows_main()
        return 0
    if args.file is None and args.message is None and not args.inspect and not args.diagnose and not args.list_input_devices:
        args.mic = True
    if args.diagnose and args.browser != "douyin":
        parser.error("--diagnose 仅适用于 --browser douyin")
    if args.interval < 10:
        parser.error("--interval 不能小于 10 秒")
    if args.limit < 0:
        parser.error("--limit 不能为负数")
    if not 200 <= args.silence_ms <= 6000:
        parser.error("--silence-ms 必须在 200 到 6000 之间")
    if not 1 <= args.max_chars <= 80:
        parser.error("--max-chars 必须在 1 到 80 之间")
    if sum((args.mic, args.file is not None, args.message is not None)) > 1:
        parser.error("--mic、--message 与文本文件只能选一种")
    if args.message is not None and (not args.message.strip() or any(ord(c) < 32 for c in args.message)):
        parser.error("--message 必须是非空的单行文本")
    if args.transcribe_only and not args.mic:
        parser.error("--transcribe-only 不能与文本文件合用")

    try:
        if args.list_input_devices:
            devices = list_input_devices()
            if not devices:
                print("未发现输入设备；请检查麦克风连接及 macOS 麦克风权限。")
            for index, name in devices:
                print(f"{index}: {name}")
            return 0
        if args.diagnose:
            result = run_douyin_action("diagnose")
            if not result.get("ok"):
                raise BrowserError(str(result.get("error", "检查辅助功能控件失败")))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.mic and args.transcribe_only:
            run_microphone(args)
            return 0
        if args.mic and not args.inspect:
            run_microphone(args)
            return 0
        if args.inspect:
            page = run_action(args.browser, "inspect")
            if not page.get("ok"):
                raise BrowserError(str(page.get("error", "检查页面失败")))
            if args.browser == "douyin":
                print("发送目标：抖音 " + ("Windows" if sys.platform == "win32" else "Mac") + " 客户端")
                print("客户端内嵌页：" + str(page["url"]))
            else:
                print("当前页面：" + str(page["url"]))
            print("平台：" + str(page.get("platform") or "未识别"))
            print("房间标识：" + str(page.get("roomNumber") or "未识别"))
            if args.browser != "douyin":
                logged_in = page.get("loggedIn")
                print("检测到登录令牌：" + ("未知" if logged_in is None else "是" if logged_in else "否"))
            print("可发送：" + ("是" if page.get("ready") else "否"))
            if page.get("reason"):
                print("原因：" + str(page["reason"]))
            if args.browser == "douyin" and not page.get("ready"):
                print("辅助功能诊断：" + json.dumps(
                    page.get("diagnostics", []), ensure_ascii=False, separators=(",", ":")
                ))
            if args.browser != "douyin":
                print("网页全屏：" + ("是" if page.get("fullscreen") else "否"))
            return 0
        messages = [args.message] if args.message is not None else read_lines(args.file)
        if args.limit:
            messages = messages[: args.limit]
        print(f"准备发送 {len(messages)} 条，间隔 {args.interval:g} 秒。按 Ctrl+C 停止。")
        for index, message in enumerate(messages, 1):
            if index > 1:
                time.sleep(args.interval)
            waiting = False
            while True:
                room = current_room(args.browser)
                if room is None:
                    if not waiting:
                        print("当前没有可发送的直播间，等待新的直播间……")
                        waiting = True
                    time.sleep(1)
                    continue
                try:
                    result = send_message(args.browser, room, message)
                except RoomChanged:
                    print("直播间已切换，重新检查当前房间。")
                    continue
                except BrowserError as exc:
                    raise BrowserError(f"第 {index} 条失败：{exc}") from exc
                status = "已触发页面发送" if result.get("confirmation") == "triggered" else "接口返回成功"
                print(f"[{index}/{len(messages)}] 房间 {room} {status}：{message}")
                break
        print("完成。弹幕是否最终展示仍取决于平台审核和直播间设置。")
        return 0
    except KeyboardInterrupt:
        print("\n已停止。")
        return 130
    except BrowserError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except VoiceError as exc:
        print(f"语音错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
