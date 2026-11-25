"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../browser_extension_ready/service_worker.js"), "utf8")
  .replace(/\nstart\(\);\s*$/, "\n");

function fixture() {
  const state = {
    now: 1000,
    window: { id: 10, focused: true, state: "normal" },
    tab: { id: 7, url: "https://live.bilibili.com/123", title: "直播" },
    stored: { clientId: "edge", lastActiveAt: 500 },
    posts: [], scripts: [], events: {}, currentOverride: undefined
  };
  const event = name => ({ addListener: callback => { state.events[name] = callback; } });
  const context = vm.createContext({
    URL, Map, Promise, console,
    Date: class extends Date { static now() { return state.now; } },
    crypto: { randomUUID: () => "new-profile" },
    setInterval: () => 0, setTimeout: () => 0,
    fetch: async (url, options) => {
      const pathname = new URL(url).pathname;
      const body = options.body ? JSON.parse(options.body) : null;
      state.posts.push({ pathname, body });
      return { ok: true, json: async () => pathname === "/view"
        ? { ok: true, current: state.currentOverride === undefined ? body : state.currentOverride }
        : { ok: true, commands: [] } };
    },
    chrome: {
      storage: { local: {
        get: async () => ({ ...state.stored }),
        set: async values => Object.assign(state.stored, values)
      } },
      tabs: {
        query: async query => {
          if (query.active) assert.equal(query.windowId, state.window.id);
          return [state.tab];
        },
        get: async () => state.tab,
        onCreated: event("created"), onRemoved: event("removed"),
        onUpdated: event("updated"), onActivated: event("activated")
      },
      windows: {
        getLastFocused: async () => state.window,
        onFocusChanged: event("focused"), onRemoved: event("windowRemoved")
      },
      scripting: { executeScript: async request => {
        state.scripts.push(request);
        return [{ result: { ok: true, state: "done" } }];
      } },
      alarms: { create: () => {}, onAlarm: event("alarm") },
      runtime: { onStartup: event("startup"), onInstalled: event("installed") }
    }
  });
  return { state, context, run: expression => vm.runInContext(expression, context) };
}

test("reports the active tab in the last used normal window", async () => {
  const f = fixture();
  vm.runInContext(source, f.context);
  await f.run("reportViewing()");
  const view = f.state.posts.at(-1).body;
  assert.equal(view.tabId, 7);
  assert.equal(view.url, "https://live.bilibili.com/123");
  assert.equal(view.lastActiveAt, 1000);
  assert.ok(f.state.events.activated && f.state.events.focused);
});

test("returning to the control panel retains the last browser focus time", async () => {
  const f = fixture();
  vm.runInContext(source, f.context);
  await f.run("reportViewing()");
  f.state.window.focused = false;
  f.state.now = 2000;
  await f.run("reportViewing()");
  assert.equal(f.state.posts.at(-1).body.lastActiveAt, 1000);
});

test("non-live tab URLs and titles are not transmitted", async () => {
  const f = fixture();
  f.state.tab.url = "https://example.com/private";
  f.state.tab.title = "私人页面";
  vm.runInContext(source, f.context);
  await f.run("reportViewing()");
  assert.equal(f.state.posts.at(-1).body.url, "");
  assert.equal(f.state.posts.at(-1).body.title, "");
});

test("minimized browser pauses the target", async () => {
  const f = fixture();
  f.state.window.state = "minimized";
  vm.runInContext(source, f.context);
  await f.run("reportViewing()");
  assert.equal(f.state.posts.at(-1).body.tabId, -1);
  assert.equal(f.state.posts.at(-1).body.url, "");
});

test("auto send is blocked if another browser became current", async () => {
  const f = fixture();
  f.state.currentOverride = { clientId: "chrome", tabId: 8, url: "https://www.douyu.com/456" };
  vm.runInContext(source, f.context);
  await f.run(`execute({requestId:"1", tabId:7, expiresAt:9999, action:"send",
    payload:{expectedPlatform:"bilibili", expectedRoom:"123", followActive:true, message:"测试"}})`);
  assert.equal(f.state.scripts.length, 0);
  assert.equal(f.state.posts.at(-1).pathname, "/result");
  assert.equal(f.state.posts.at(-1).body.result.ok, false);
});

test("manual send remains available for a background tab", async () => {
  const f = fixture();
  f.state.currentOverride = { clientId: "chrome", tabId: 8 };
  vm.runInContext(source, f.context);
  await f.run(`execute({requestId:"1", tabId:7, expiresAt:9999, action:"send",
    payload:{expectedPlatform:"bilibili", expectedRoom:"123", message:"测试"}})`);
  assert.equal(f.state.scripts.length, 2);
  assert.equal(f.state.posts.at(-1).body.result.ok, true);
});

test("pending navigation cannot reuse the old live room for auto send", async () => {
  const f = fixture();
  f.state.tab.pendingUrl = "https://live.bilibili.com/456";
  vm.runInContext(source, f.context);
  await f.run(`execute({requestId:"1", tabId:7, expiresAt:9999, action:"send",
    payload:{expectedPlatform:"bilibili", expectedRoom:"123", followActive:true, message:"测试"}})`);
  assert.equal(f.state.scripts.length, 0);
  assert.equal(f.state.posts.at(-1).body.result.ok, false);
});
