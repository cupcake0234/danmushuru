"use strict";

const BASE = "http://127.0.0.1:8765";
const SCRIPTS = {
  bilibili: "generated/bilibili.js",
  douyu: "generated/douyu.js",
  douyin: "generated/douyin.js"
};
const tabLocks = new Map();
const inspected = new Map();
let clientId = null;
let identityTask = null;
let nextSnapshot = 0;
let polling = false;
let hasSnapshot = false;
let lastActiveAt = 0;
let viewingTask = null;

async function identity() {
  if (clientId) return clientId;
  if (!identityTask) identityTask = (async () => {
    const saved = await chrome.storage.local.get(["clientId", "lastActiveAt"]);
    clientId = saved.clientId || crypto.randomUUID();
    lastActiveAt = Number(saved.lastActiveAt) || 0;
    if (!saved.clientId) await chrome.storage.local.set({ clientId });
    return clientId;
  })();
  return identityTask;
}

function platformAndRoom(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return null;
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parsed.hostname === "live.bilibili.com" && /^\d+$/.test(parts[0] || ""))
      return ["bilibili", parts[0]];
    if (["www.douyu.com", "douyu.com"].includes(parsed.hostname) &&
        /^[A-Za-z0-9_-]+$/.test(parts[0] || "") &&
        !["directory", "topic", "search", "video", "gapi"].includes(parts[0].toLowerCase()))
      return ["douyu", parts[0]];
    if (parsed.hostname === "live.douyin.com" && /^\d+$/.test(parts[0] || ""))
      return ["douyin", parts[0]];
    if (parsed.hostname === "www.douyin.com" && parts[0] === "live" && /^\d+$/.test(parts[1] || ""))
      return ["douyin", parts[1]];
  } catch (_) {}
  return null;
}

async function request(path, method = "GET", body) {
  const response = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) throw new Error("本机连接失败：HTTP " + response.status);
  return response.json();
}

// Report the last used normal browser window, even while the control panel is in front.
// A non-live active tab is reported with an empty URL; unrelated browsing stays in the browser.
async function publishViewing() {
  const id = await identity();
  let tab = null;
  try {
    const window = await chrome.windows.getLastFocused({ windowTypes: ["normal"] });
    if (window.state !== "minimized") {
      [tab] = await chrome.tabs.query({ active: true, windowId: window.id });
      if (window.focused) {
        lastActiveAt = Date.now();
        await chrome.storage.local.set({ lastActiveAt });
      }
    }
  } catch (_) {}
  const live = tab && platformAndRoom(tab.pendingUrl || tab.url || "");
  return request("/view", "POST", {
    clientId: id, tabId: tab?.id ?? -1, lastActiveAt,
    url: live ? (tab.pendingUrl || tab.url) : "", title: live ? (tab.title || "") : ""
  });
}

function reportViewing() {
  if (!viewingTask) viewingTask = publishViewing().catch(() => null).finally(() => { viewingTask = null; });
  return viewingTask;
}

async function runScript(tabId, platform, payload) {
  const previous = tabLocks.get(tabId) || Promise.resolve();
  const task = previous.catch(() => {}).then(async () => {
    await chrome.scripting.executeScript({
      target: { tabId }, world: "MAIN",
      func: requestPayload => { globalThis.__danmuPayload = requestPayload; },
      args: [payload]
    });
    const injected = await chrome.scripting.executeScript({
      target: { tabId }, world: "MAIN", files: [SCRIPTS[platform]]
    });
    const result = injected?.[0]?.result;
    return typeof result === "string" ? JSON.parse(result) : result;
  });
  tabLocks.set(tabId, task);
  try { return await task; }
  finally { if (tabLocks.get(tabId) === task) tabLocks.delete(tabId); }
}

async function snapshot() {
  const tabs = await chrome.tabs.query({});
  const live = tabs.filter(tab => platformAndRoom(tab.url || ""));
  const id = await identity();
  await request("/snapshot", "POST", { clientId: id, tabs: live.map(tab => ({
    tabId: tab.id, url: tab.url, title: tab.title || "",
    ready: inspected.get(tab.id)?.url === tab.url ? inspected.get(tab.id).ready : false,
    reason: inspected.get(tab.id)?.url === tab.url ? inspected.get(tab.id).reason : "正在检查网页状态"
  })) });
  const entries = await Promise.all(live.map(async tab => {
    const [platform] = platformAndRoom(tab.url);
    if (tab.discarded || tab.status !== "complete") {
      return { tabId: tab.id, url: tab.url, title: tab.title || "", ready: false,
               reason: "直播页尚未加载" };
    }
    try {
      const result = await Promise.race([
        runScript(tab.id, platform, { action: "inspect" }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("网页检查超时")), 3000))
      ]);
      return { tabId: tab.id, url: tab.url, title: tab.title || "",
               ready: Boolean(result?.ok && result?.ready),
               reason: result?.ready ? "" : String(result?.error || "网页未登录或弹幕控件尚未加载") };
    } catch (error) {
      return { tabId: tab.id, url: tab.url, title: tab.title || "",
               ready: false, reason: String(error) };
    }
  }));
  inspected.clear();
  for (const entry of entries) inspected.set(entry.tabId, entry);
  await request("/snapshot", "POST", { clientId: id, tabs: entries });
}

async function execute(command) {
  let result;
  try {
    if (Date.now() > command.expiresAt) throw new Error("发送任务已过期，未发送");
    const tab = await chrome.tabs.get(command.tabId);
    const identity = platformAndRoom(tab.url || "");
    const expected = command.payload || {};
    if (expected.followActive && command.action === "send") {
      const view = (await reportViewing())?.current;
      if (!view || view.clientId !== clientId || view.tabId !== tab.id || view.url !== tab.url) {
        throw new Error("自动跟随的活动直播页已变化，未发送");
      }
    }
    if (!identity || (expected.expectedPlatform && identity[0] !== expected.expectedPlatform) ||
        (expected.expectedRoom && identity[1] !== expected.expectedRoom)) {
      throw new Error("直播标签页已切换房间，未发送");
    }
    result = await runScript(tab.id, identity[0], { action: command.action, ...expected });
  } catch (error) {
    result = { ok: false, error: String(error) };
  }
  await request("/result", "POST", { requestId: command.requestId, result });
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    const id = await identity();
    if (!hasSnapshot) {
      await snapshot();
      hasSnapshot = true;
      nextSnapshot = Date.now() + 5000;
    }
    const incoming = await request("/commands?clientId=" + encodeURIComponent(id));
    await Promise.all((incoming.commands || []).map(execute));
    if (Date.now() >= nextSnapshot) {
      await snapshot();
      nextSnapshot = Date.now() + 5000;
    }
  } catch (_) {
    hasSnapshot = false;
    nextSnapshot = 0;
  } finally {
    polling = false;
  }
}

function start() {
  chrome.alarms.create("bridge", { periodInMinutes: 0.5 });
  poll();
  reportViewing();
}

chrome.runtime.onStartup.addListener(start);
chrome.runtime.onInstalled.addListener(start);
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "bridge") poll(); });
chrome.tabs.onCreated.addListener(() => { nextSnapshot = 0; poll(); });
chrome.tabs.onRemoved.addListener(() => { nextSnapshot = 0; poll(); });
chrome.tabs.onUpdated.addListener((_tabId, change) => {
  if (change.url || change.status === "complete") { nextSnapshot = 0; poll(); reportViewing(); }
});
chrome.tabs.onActivated.addListener(() => { nextSnapshot = 0; reportViewing(); poll(); });
chrome.windows.onFocusChanged.addListener(() => { reportViewing(); });
chrome.windows.onRemoved.addListener(() => { reportViewing(); });
setInterval(poll, 1000);
setInterval(reportViewing, 1000);
start();
