(function () {
  "use strict";
  const request = globalThis.__danmuPayload;
  const data = { ok: false, url: location.href, fullscreen: Boolean(document.fullscreenElement) };
  const finish = () => JSON.stringify(data);
  const roomFromLocation = () => {
    const host = location.hostname.toLowerCase();
    const parts = location.pathname.split("/").filter(Boolean);
    if (host === "live.douyin.com" && /^\d+$/.test(parts[0] || "")) return parts[0];
    if (host === "www.douyin.com" && parts[0] === "live" && /^\d+$/.test(parts[1] || "")) return parts[1];
    return null;
  };
  const roomNumber = roomFromLocation();
  const textOf = node => node ? String(node.value ?? node.innerText ?? node.textContent ?? "") : "";
  const visible = node => {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" &&
      !node.disabled && !node.readOnly;
  };
  const inputCandidates = () => Array.from(document.querySelectorAll(
    'textarea, input[type="text"], [contenteditable="true"], [role="textbox"], ' +
    '[data-e2e="chat_input"], [data-e2e="chatInput"]'
  )).filter(node => visible(node) && !["search", "password"].includes(String(node.type || "").toLowerCase()));
  const inputScore = node => {
    const hint = [node.placeholder, node.getAttribute("aria-label"), node.getAttribute("data-e2e"), node.className]
      .filter(Boolean).join(" ").toLowerCase();
    let score = node.matches('textarea, [contenteditable="true"], [role="textbox"]') ? 10 : 0;
    if (/弹幕|评论|聊天|说点什么|发送|danmu|comment|chat/.test(hint)) score += 100;
    if (/search|搜索|登录|手机号|验证码/.test(hint)) score -= 100;
    return score;
  };
  const findInput = () => inputCandidates().sort((a, b) => inputScore(b) - inputScore(a))[0] || null;
  const buttonCandidates = () => Array.from(document.querySelectorAll(
    'button, [role="button"], [data-e2e*="send"], [data-e2e*="Send"], [class*="send"], [class*="Send"]'
  )).filter(visible);
  const buttonScore = node => {
    const label = [node.innerText, node.getAttribute("aria-label"), node.title, node.getAttribute("data-e2e"), node.className]
      .filter(Boolean).join(" ").trim().toLowerCase();
    let score = 0;
    if (/发送|send|发布|评论/.test(label)) score += 100;
    if (/send|发送/.test(String(node.getAttribute("data-e2e") || ""))) score += 50;
    if (/gift|关注|点赞|share|礼物|分享/.test(label)) score -= 100;
    return score;
  };
  const findButton = () => buttonCandidates().map(node => ({ node, score: buttonScore(node) }))
    .filter(item => item.score > 0).sort((a, b) => b.score - a.score)[0]?.node || null;
  const getControls = () => ({ input: findInput(), button: findButton() });
  const jobKey = "__danmuSenderDouyinWebJob";
  const getJob = () => {
    try { return JSON.parse(sessionStorage.getItem(jobKey) || "null"); }
    catch (_) { return null; }
  };
  const saveJob = job => sessionStorage.setItem(jobKey, JSON.stringify(job));

  if (request.action === "inspect") {
    const controls = getControls();
    data.ok = true;
    data.platform = "douyin";
    data.roomNumber = roomNumber;
    data.loggedIn = null;
    data.ready = Boolean(roomNumber && controls.input && controls.button && !textOf(controls.input).trim());
    if (roomNumber && (!controls.input || !controls.button)) data.error = "未找到抖音网页弹幕输入框或发送按钮";
    if (roomNumber && controls.input && textOf(controls.input).trim()) data.error = "弹幕输入框已有草稿";
    return finish();
  }
  if (request.expectedRoom && request.expectedRoom !== roomNumber) {
    data.errorCode = "ROOM_CHANGED";
    data.error = "直播间已切换";
    return finish();
  }
  if (request.action === "poll") {
    const job = getJob();
    if (!job || job.id !== request.jobId) {
      data.errorCode = "JOB_LOST";
      data.error = "找不到发送任务";
      return finish();
    }
    data.ok = job.state !== "done" || job.ok;
    data.state = job.state;
    if (job.error) data.error = job.error;
    if (job.errorCode) data.errorCode = job.errorCode;
    if (job.state === "done") sessionStorage.removeItem(jobKey);
    return finish();
  }
  const controls = getControls();
  if (!roomNumber || !controls.input || !controls.button) {
    data.errorCode = "NO_ROOM";
    data.error = "抖音网页直播控件尚未加载";
    return finish();
  }
  if (request.action !== "send" || typeof request.message !== "string" || !request.message.trim() || !request.jobId) {
    data.error = "弹幕内容无效";
    return finish();
  }
  if (textOf(controls.input).trim()) {
    data.errorCode = "DRAFT_PRESENT";
    data.error = "弹幕输入框已有内容";
    return finish();
  }
  const previous = getJob();
  if (previous && previous.state === "pending" && Date.now() - previous.startedAt < 120000) {
    data.error = "上一条弹幕仍在发送，请稍后";
    return finish();
  }
  const job = { id: request.jobId, startedAt: Date.now(), state: "pending", ok: false, error: "" };
  saveJob(job);
  try {
    const input = controls.input;
    const button = controls.button;
    input.focus();
    if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {
      const prototype = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value").set.call(input, request.message);
    } else {
      input.textContent = request.message;
    }
    input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: request.message }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    setTimeout(() => {
      try {
        const currentControls = getControls();
        if (roomFromLocation() !== roomNumber || !input.isConnected || !button.isConnected ||
            currentControls.input !== input || currentControls.button !== button) {
          job.errorCode = "ROOM_CHANGED";
          throw new Error("直播间或弹幕控件已变化");
        }
        if (textOf(input).trim() !== request.message.trim()) throw new Error("输入框内容被页面修改");
        button.click();
        job.ok = true;
      } catch (error) {
        job.error = String(error);
      }
      job.state = "done";
      if (getJob() && getJob().id === job.id) saveJob(job);
    }, 100);
    data.ok = true;
    data.state = "pending";
  } catch (error) {
    job.error = String(error);
    job.state = "done";
    saveJob(job);
    data.error = job.error;
  }
  return finish();
})();
