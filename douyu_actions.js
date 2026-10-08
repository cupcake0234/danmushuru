(function () {
  "use strict";
  const request = __PAYLOAD_JSON__;
  const data = { ok: false, url: location.href, fullscreen: Boolean(document.fullscreenElement) };
  const finish = () => JSON.stringify(data);
  const onDouyu = location.hostname === "www.douyu.com";
  const match = onDouyu && location.pathname.match(/^\/([A-Za-z0-9_-]+)(?:\/|$)/);
  const roomNumber = match ? match[1] : null;
  const loggedIn = onDouyu && /(?:^|;\s*)acf_uid=\d+(?:;|$)/.test(document.cookie);
  const findControls = () => ({
    input: document.querySelector("textarea.ChatSend-txt, div.ChatSend-txt"),
    button: document.querySelector(".ChatSend-button")
  });
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
    data.loggedIn = Boolean(loggedIn);
    data.ready = Boolean(roomNumber && loggedIn && controls.input && controls.button);
    return finish();
  }
  if (request.expectedRoom && roomNumber !== request.expectedRoom) {
    data.errorCode = "ROOM_CHANGED";
    data.error = "当前活动标签页已切换直播间。";
    return finish();
  }
  if (!roomNumber || !loggedIn || !controls.input || !controls.button) {
    data.errorCode = "NO_ROOM";
    data.error = "斗鱼直播间未登录或弹幕控件尚未加载。";
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
      await new Promise(resolve => setTimeout(resolve, 100));
      const currentMatch = location.hostname === "www.douyu.com" &&
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
