import AppKit
import ApplicationServices
import Foundation

struct Request: Decodable {
    let action: String
    let expectedRoom: String?
    let message: String?
}

func output(_ data: [String: Any]) {
    guard let raw = try? JSONSerialization.data(withJSONObject: data, options: [.sortedKeys]),
          let line = String(data: raw, encoding: .utf8) else { return }
    print(line)
}

func fail(_ message: String, code: String? = nil) {
    var result: [String: Any] = ["ok": false, "error": message]
    if let code = code { result["errorCode"] = code }
    output(result)
}

func attribute(_ element: AXUIElement, _ name: String) -> Any? {
    var value: CFTypeRef?
    guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
        return nil
    }
    return value
}

func stringAttribute(_ element: AXUIElement, _ name: String) -> String? {
    guard let value = attribute(element, name) else { return nil }
    if let url = value as? URL { return url.absoluteString }
    return value as? String ?? String(describing: value)
}

func childElements(_ element: AXUIElement) -> [AXUIElement] {
    return attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
}

func clean(_ value: String) -> String {
    let invisible = CharacterSet(charactersIn: "\u{200B}\u{200C}\u{200D}\u{FEFF}")
    return value.trimmingCharacters(in: .whitespacesAndNewlines.union(invisible))
}

func fieldText(_ field: AXUIElement) -> String {
    let value = clean(stringAttribute(field, kAXValueAttribute) ?? "")
    let placeholder = clean(stringAttribute(field, kAXPlaceholderValueAttribute) ?? "")
    // The Douyin client can expose its visual placeholder as AXValue while
    // leaving AXPlaceholderValue empty, even though the editor has no draft.
    let clientPlaceholders = ["与大家互动一下...", "与大家互动一下…"]
    return value == placeholder || clientPlaceholders.contains(value) ? "" : value
}

func roomInURL(_ raw: String) -> String? {
    let urlText = raw.hasPrefix("http") ? raw : "https://" + raw
    guard let url = URLComponents(string: urlText),
          let host = url.host?.lowercased(),
          host == "douyin.com" || host == "www.douyin.com" || host == "live.douyin.com" else { return nil }
    let parts = url.path.split(separator: "/")
    if host == "live.douyin.com", parts.count == 1 {
        let room = String(parts[0])
        return !room.isEmpty && room.allSatisfy(\.isNumber) ? room : nil
    }
    guard let position = parts.firstIndex(of: "live"), position + 1 < parts.count else { return nil }
    let room = String(parts[position + 1])
    return !room.isEmpty && room.allSatisfy(\.isNumber) ? room : nil
}

func roomInIndicatorURL(_ raw: String) -> String? {
    let urlText = raw.hasPrefix("http") ? raw : "https://" + raw
    guard let url = URLComponents(string: urlText),
          let host = url.host?.lowercased(),
          (host == "bytegecko.com" || host.hasSuffix(".bytegecko.com")),
          url.path.contains("/live_pc_indicator_container_douyin/pages/"),
          let room = url.queryItems?.first(where: { $0.name == "room_id" })?.value,
          !room.isEmpty, room.allSatisfy(\.isNumber) else { return nil }
    return room
}

struct LivePage {
    let room: String
    let url: String
    let source: AXUIElement
    let field: AXUIElement
}

func inspectWindow(_ window: AXUIElement) -> LivePage? {
    var stack: [AXUIElement] = [window]
    var seen = 0
    var room: String?
    var pageURL: String?
    var pageSource: AXUIElement?
    var indicatorRoom: String?
    var indicatorURL: String?
    var indicatorSource: AXUIElement?
    var fields: [(AXUIElement, String)] = []
    while let element = stack.popLast(), seen < 2500 {
        seen += 1
        let role = stringAttribute(element, kAXRoleAttribute) ?? ""
        if role == "AXWebArea", let url = stringAttribute(element, kAXURLAttribute) {
            if let found = roomInURL(url) {
                room = found
                pageURL = url
                pageSource = element
            } else if let found = roomInIndicatorURL(url) {
                indicatorRoom = found
                indicatorURL = url
                indicatorSource = element
            }
        }
        if role == "AXTextArea" || role == "AXTextField" {
            let hint = (stringAttribute(element, kAXPlaceholderValueAttribute) ?? "") +
                (stringAttribute(element, kAXDescriptionAttribute) ?? "") +
                (stringAttribute(element, kAXValueAttribute) ?? "")
            fields.append((element, hint))
        }
        stack.append(contentsOf: childElements(element).reversed())
    }
    guard let room = room ?? indicatorRoom,
          let url = pageURL ?? indicatorURL,
          let source = pageSource ?? indicatorSource else { return nil }
    let matching = fields.filter { $0.1.contains("互动") || $0.1.contains("弹幕") }
    let field = matching.first?.0 ?? (fields.count == 1 ? fields[0].0 : nil)
    guard let input = field else { return nil }
    return LivePage(room: room, url: url, source: source, field: input)
}

func roomStillMatches(_ page: LivePage) -> Bool {
    guard let url = stringAttribute(page.source, kAXURLAttribute) else { return false }
    return (roomInURL(url) ?? roomInIndicatorURL(url)) == page.room
}

func livePage(_ app: AXUIElement) -> LivePage? {
    let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement] ?? []
    for window in windows {
        if let page = inspectWindow(window) { return page }
    }
    // Some Electron builds expose their window through AXChildren but not AXWindows.
    return inspectWindow(app)
}

func settledLivePage(_ app: AXUIElement) -> LivePage? {
    // Electron may populate nested web areas only after the first AX traversal.
    for attempt in 0..<3 {
        if let page = livePage(app) { return page }
        if attempt < 2 { Thread.sleep(forTimeInterval: 0.12) }
    }
    return nil
}

func diagnostic(_ running: NSRunningApplication, app: AXUIElement) -> ([String: Any], LivePage?) {
    var windowValue: CFTypeRef?
    let windowError = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windowValue)
    let windows = windowValue as? [AXUIElement] ?? []
    var stack: [AXUIElement] = windows.isEmpty ? [app] : windows
    var seen = 0
    var webAreas = 0
    var inputFields = 0
    var matchingInputs = 0
    var urlKinds: [String] = []
    while let element = stack.popLast(), seen < 3000 {
        seen += 1
        let role = stringAttribute(element, kAXRoleAttribute) ?? ""
        if role == "AXWebArea" {
            webAreas += 1
            if let raw = stringAttribute(element, kAXURLAttribute) {
                let urlText = raw.hasPrefix("http") ? raw : "https://" + raw
                if let url = URLComponents(string: urlText) {
                    let kind = (url.host ?? "unknown") + url.path
                    if !urlKinds.contains(kind), urlKinds.count < 8 { urlKinds.append(kind) }
                }
            }
        }
        if role == "AXTextArea" || role == "AXTextField" {
            inputFields += 1
            let hint = (stringAttribute(element, kAXPlaceholderValueAttribute) ?? "") +
                (stringAttribute(element, kAXDescriptionAttribute) ?? "") +
                (stringAttribute(element, kAXValueAttribute) ?? "")
            if hint.contains("互动") || hint.contains("弹幕") { matchingInputs += 1 }
        }
        stack.append(contentsOf: childElements(element).reversed())
    }
    let page = settledLivePage(app)
    let details: [String: Any] = [
        "pid": running.processIdentifier, "windowError": windowError.rawValue,
        "windows": windows.count, "elements": seen, "webAreas": webAreas,
        "inputFields": inputFields, "matchingInputs": matchingInputs,
        "urlKinds": urlKinds, "roomFound": page != nil
    ]
    return (details, page)
}

func key(_ code: CGKeyCode, command: Bool = false) {
    for down in [true, false] {
        if let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down) {
            if command { event.flags = .maskCommand }
            event.post(tap: .cghidEventTap)
        }
    }
}

func click(_ point: CGPoint) {
    for kind in [CGEventType.leftMouseDown, .leftMouseUp] {
        CGEvent(mouseEventSource: nil, mouseType: kind,
                mouseCursorPosition: point, mouseButton: .left)?.post(tap: .cghidEventTap)
    }
}

func center(_ field: AXUIElement) -> CGPoint? {
    guard let positionValue = attribute(field, kAXPositionAttribute) as! AXValue?,
          let sizeValue = attribute(field, kAXSizeAttribute) as! AXValue? else { return nil }
    var point = CGPoint.zero
    var size = CGSize.zero
    guard AXValueGetValue(positionValue, .cgPoint, &point),
          AXValueGetValue(sizeValue, .cgSize, &size) else { return nil }
    return CGPoint(x: point.x + size.width / 2, y: point.y + size.height / 2)
}

func focusedOnField(_ app: AXUIElement, field: AXUIElement,
                    expectedText: String) -> Bool {
    guard let focused = attribute(app, kAXFocusedUIElementAttribute) as! AXUIElement?,
          let role = stringAttribute(focused, kAXRoleAttribute),
          role == "AXTextArea" || role == "AXTextField",
          fieldText(focused) == expectedText else { return false }
    if CFEqual(focused, field) { return true }
    guard let first = center(focused), let second = center(field) else { return false }
    return abs(first.x - second.x) < 8 && abs(first.y - second.y) < 8
}

func refocusDraft(_ running: NSRunningApplication, app: AXUIElement,
                  page: LivePage, message: String) -> Bool {
    for _ in 0..<2 {
        _ = running.activate(options: [])
        guard let point = center(page.field) else { return false }
        click(point)
        Thread.sleep(forTimeInterval: 0.12)
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier,
           focusedOnField(app, field: page.field, expectedText: message) {
            return true
        }
    }
    return false
}

func copyPasteboardItems(_ board: NSPasteboard) -> [NSPasteboardItem] {
    return (board.pasteboardItems ?? []).map { item in
        let copied = NSPasteboardItem()
        for type in item.types {
            if let data = item.data(forType: type) { copied.setData(data, forType: type) }
        }
        return copied
    }
}

func send(_ request: Request, running: NSRunningApplication, app: AXUIElement,
          page: LivePage) {
    guard let expected = request.expectedRoom, let message = request.message,
          !clean(message).isEmpty else { fail("缺少房间标识或弹幕内容。"); return }
    guard page.room == expected else { fail("抖音直播间已切换，取消发送。", code: "ROOM_CHANGED"); return }
    guard fieldText(page.field).isEmpty else {
        fail("弹幕输入框已有内容；为避免覆盖草稿，本条未发送。")
        return
    }
    let previousApp = NSWorkspace.shared.frontmostApplication
    _ = running.activate(options: [])
    defer {
        if let previous = previousApp, previous.processIdentifier != running.processIdentifier,
           NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier {
            _ = previous.activate(options: [])
        }
    }
    Thread.sleep(forTimeInterval: 0.15)
    guard roomStillMatches(page) else {
        fail("抖音直播间已切换，取消发送。", code: "ROOM_CHANGED")
        return
    }
    guard let point = center(page.field) else { fail("无法定位抖音弹幕输入区。"); return }
    click(point)
    Thread.sleep(forTimeInterval: 0.08)
    guard focusedOnField(app, field: page.field, expectedText: "") else {
        fail("未能聚焦抖音弹幕输入框，取消发送。")
        return
    }
    key(0, command: true) // Command+A
    let board = NSPasteboard.general
    let savedItems = copyPasteboardItems(board)
    board.clearContents()
    guard board.setString(message, forType: .string) else {
        board.clearContents()
        if !savedItems.isEmpty { _ = board.writeObjects(savedItems) }
        fail("无法把弹幕内容放入临时剪贴板。")
        return
    }
    let temporaryChange = board.changeCount
    key(9, command: true) // Command+V
    Thread.sleep(forTimeInterval: 0.2)
    if board.changeCount == temporaryChange {
        board.clearContents()
        if !savedItems.isEmpty { _ = board.writeObjects(savedItems) }
    }
    guard roomStillMatches(page) else {
        fail("输入期间直播间已切换，取消发送。", code: "ROOM_CHANGED")
        return
    }
    guard fieldText(page.field) == clean(message) else {
        fail("客户端弹幕输入内容与识别文本不一致，已取消发送。")
        return
    }
    guard refocusDraft(running, app: app, page: page, message: clean(message)) else {
        fail("输入文字后无法重新聚焦抖音弹幕输入框；文字保留在输入框，未发送。")
        return
    }
    guard roomStillMatches(page) else {
        fail("发送前直播间已切换，取消发送。", code: "ROOM_CHANGED")
        return
    }
    guard fieldText(page.field) == clean(message) else {
        fail("发送前弹幕输入内容发生变化，已取消发送。")
        return
    }
    key(36) // Return
    Thread.sleep(forTimeInterval: 0.3)
    guard fieldText(page.field).isEmpty else {
        fail("已按回车，但弹幕仍留在输入框；请检查客户端是否需要点击发送按钮。")
        return
    }
    output(["ok": true, "state": "done", "confirmation": "triggered", "roomNumber": expected])
}

guard AXIsProcessTrusted() else {
    fail("请在 macOS 系统设置中允许当前终端使用辅助功能，然后重新运行。")
    exit(0)
}
let raw = FileHandle.standardInput.readDataToEndOfFile()
guard let request = try? JSONDecoder().decode(Request.self, from: raw) else {
    fail("无法解析客户端操作请求。")
    exit(0)
}
let runningApps = NSRunningApplication.runningApplications(
    withBundleIdentifier: "com.bytedance.douyin.desktop")
guard !runningApps.isEmpty else {
    if request.action == "inspect" {
        output(["ok": true, "platform": "douyin", "url": "",
                "roomNumber": NSNull(), "ready": false, "loggedIn": NSNull(),
                "diagnostics": []])
    } else if request.action == "diagnose" {
        output(["ok": true, "processes": []])
    } else {
        fail("抖音客户端尚未运行。", code: "APP_UNAVAILABLE")
    }
    exit(0)
}
let candidates = runningApps.map { running -> (NSRunningApplication, AXUIElement) in
    let app = AXUIElementCreateApplication(running.processIdentifier)
    AXUIElementSetMessagingTimeout(app, 3)
    return (running, app)
}
switch request.action {
case "inspect":
    let inspected = candidates.map { diagnostic($0.0, app: $0.1) }
    if let page = inspected.compactMap({ $0.1 }).first {
        output(["ok": true, "platform": "douyin", "url": page.url,
                "roomNumber": page.room, "ready": true, "loggedIn": NSNull()])
    } else {
        output(["ok": true, "platform": "douyin", "url": "",
                "roomNumber": NSNull(), "ready": false, "loggedIn": NSNull(),
                "diagnostics": inspected.map { $0.0 }])
    }
case "diagnose":
    output(["ok": true, "processes": candidates.map { diagnostic($0.0, app: $0.1).0 }])
case "send":
    let targets = candidates.compactMap { running, app -> (NSRunningApplication, AXUIElement, LivePage)? in
        guard let page = diagnostic(running, app: app).1 else { return nil }
        return (running, app, page)
    }
    guard let target = targets.first else {
        fail("抖音客户端当前没有可发送的直播间。", code: "NO_ROOM")
        break
    }
    send(request, running: target.0, app: target.1, page: target.2)
default:
    fail("不支持的客户端操作。")
}
