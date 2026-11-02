(function () {
  "use strict";
  const request = globalThis.__danmuPayload;
  const data = { ok: false, url: location.href, fullscreen: Boolean(document.fullscreenElement) };
  const finish = () => JSON.stringify(data);
  const onDouyu = location.hostname === "www.douyu.com" || location.hostname === "douyu.com";
  const match = onDouyu && location.pathname.match(/^\/([A-Za-z0-9_-]+)(?:\/|$)/);
  const roomNumber = match ? match[1] : null;
  const loggedIn = onDouyu && /(?:^|;\s*)acf_uid=\d+(?:;|$)/.test(document.cookie);
  const visible = node => {
    if (!node || node.disabled || node.readOnly) return false;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const findControls = () => {
    const inputs = Array.from(document.querySelectorAll(
      "textarea.ChatSend-txt, div.ChatSend-txt, textarea[placeholder*='弹幕'], " +
      "[contenteditable='true'][class*='Chat'], [role='textbox']"
    )).filter(visible);
    const input = inputs.sort((left, right) => {
      const score = node => /ChatSend|弹幕|评论|聊天/i.test(
        [node.className, node.getAttribute("placeholder"), node.getAttribute("aria-label")].filter(Boolean).join(" ")
      ) ? 1 : 0;
      return score(right) - score(left);
    })[0] || null;
    const buttons = Array.from(document.querySelectorAll(
      ".ChatSend-button, [class*='ChatSend'] button, button[aria-label*='发送'], " +
      "button[data-e2e*='send'], [role='button'][aria-label*='发送']"
    )).filter(visible);
    const button = buttons.find(node => !node.disabled && !node.classList.contains("is-gray")) || buttons[0] || null;
    return { input, button };
  };
  const controls = findControls();
  const jobKey = "__danmuSenderDouyuJob";
  const getJob = () => {
    try { return JSON.parse(sessionStorage.getItem(jobKey) || "null"); }
    catch (_) { return null; }
  };
  const saveJob = job => sessionStorage.setItem(jobKey, JSON.stringify(job));

  if (request.action === "inspect") {
    data.ok = true;
    data.platform = "douyu";
    data.roomNumber = controls.input && controls.button ? roomNumber : null;
    data.loggedIn = loggedIn ? true : (controls.input && controls.button ? null : false);
    data.ready = Boolean(roomNumber && controls.input && controls.button);
    return finish();
  }
  if (request.expectedRoom && roomNumber !== request.expectedRoom) {
    data.errorCode = "ROOM_CHANGED";
    data.error = "当前活动标签页已切换直播间。";
    return finish();
  }
  if (request.action === "poll") {
    const job = getJob();
    if (!job || job.id !== request.jobId) {
      data.errorCode = "JOB_LOST";
      data.error = "找不到发送任务；页面可能已刷新。";
      return finish();
    }
    data.state = job.state;
    data.ok = true;
    if (job.state === "done") {
      data.ok = job.ok;
      if (!job.ok) data.error = job.error;
      if (job.errorCode) data.errorCode = job.errorCode;
      if (job.confirmation) data.confirmation = job.confirmation;
      sessionStorage.removeItem(jobKey);
    }
    return finish();
  }
  if (!roomNumber || !controls.input || !controls.button) {
    data.errorCode = "NO_ROOM";
    data.error = "斗鱼直播间未登录或弹幕控件尚未加载。";
    return finish();
  }
  if (request.action !== "send" || typeof request.message !== "string" ||
      !request.message.trim() || !request.jobId || !request.expectedRoom) {
    data.error = "操作或弹幕内容无效。";
    return finish();
  }
  const previous = getJob();
  if (previous && previous.state === "pending" && Date.now() - previous.startedAt < 120000) {
    data.error = "上一条弹幕仍在发送，请稍后。";
    return finish();
  }
  const input = controls.input;
  const button = controls.button;
  const readText = () => input.tagName === "TEXTAREA" ? input.value : input.innerText;
  if (readText().trim()) {
    data.error = "弹幕输入框已有内容；为避免覆盖你正在编辑的文字，本条未发送。";
    return finish();
  }
  const job = { id: request.jobId, startedAt: Date.now(), state: "pending", ok: false, error: "" };
  saveJob(job);
  (async function () {
    try {
      if (input.tagName === "TEXTAREA") {
        const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
        setter.call(input, request.message);
      } else {
        input.innerText = request.message;
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await new Promise(resolve => setTimeout(resolve, 100));
      const currentMatch = (location.hostname === "www.douyu.com" || location.hostname === "douyu.com") &&
        location.pathname.match(/^\/([A-Za-z0-9_-]+)(?:\/|$)/);
      if (!currentMatch || currentMatch[1] !== roomNumber || !input.isConnected || !button.isConnected) {
        job.errorCode = "ROOM_CHANGED";
        throw new Error("直播间已切换，取消发送。");
      }
      if (readText().trim() !== request.message.trim()) {
        throw new Error("弹幕输入内容已改变，取消发送。");
      }
      if (button.disabled || button.classList.contains("is-gray")) {
        throw new Error("斗鱼发送按钮不可用，可能处于冷却中或账号受限。");
      }
      button.click();
      job.ok = true;
      job.confirmation = "triggered";
    } catch (error) {
      job.error = String(error);
      if (input.isConnected && readText().trim() === request.message.trim()) {
        if (input.tagName === "TEXTAREA") input.value = "";
        else input.innerText = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    } finally {
      job.state = "done";
      if (getJob() && getJob().id === job.id) saveJob(job);
    }
  })();
  data.ok = true;
  data.state = "pending";
  return finish();
})();
