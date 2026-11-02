(function () {
  "use strict";
  const request = globalThis.__danmuPayload;
  const data = { ok: false, url: location.href, fullscreen: Boolean(document.fullscreenElement) };
  const finish = () => JSON.stringify(data);
  const onLiveSite = location.hostname === "live.bilibili.com";
  const roomMatch = onLiveSite && location.pathname.match(/^\/(\d+)(?:\/|$)/);
  const roomNumber = roomMatch && roomMatch[1];
  const csrfCookie = (onLiveSite ? document.cookie : "").split(";").map(part => part.trim())
    .find(part => part.startsWith("bili_jct="));
  const csrf = csrfCookie ? decodeURIComponent(csrfCookie.slice("bili_jct=".length)) : "";
  const jobKey = "__danmuSenderJob";
  const getJob = () => {
    try { return JSON.parse(sessionStorage.getItem(jobKey) || "null"); }
    catch (_) { return null; }
  };
  const saveJob = job => sessionStorage.setItem(jobKey, JSON.stringify(job));
  if (request.action === "inspect") {
    data.ok = true;
    data.platform = "bilibili";
    data.roomNumber = roomNumber || null;
    data.loggedIn = Boolean(csrf);
    data.ready = Boolean(roomNumber && csrf);
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
    if (job.state === "done") {
      data.ok = job.ok;
      if (!job.ok) data.error = job.error;
      if (job.errorCode) data.errorCode = job.errorCode;
      if (job.roomId) data.roomId = job.roomId;
      sessionStorage.removeItem(jobKey);
    } else {
      data.ok = true;
    }
    return finish();
  }
  if (!roomNumber || !csrf) {
    data.errorCode = "NO_ROOM";
    data.error = "缺少直播房间号或登录令牌；请确认浏览器里已经登录 B 站。";
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
  const job = { id: request.jobId, startedAt: Date.now(), state: "pending", ok: false, error: "" };
  saveJob(job);
  (async function () {
    try {
      const roomResponse = await fetch(
        "https://api.live.bilibili.com/room/v1/Room/room_init?id=" + encodeURIComponent(roomNumber),
        { credentials: "include" }
      );
      if (!roomResponse.ok) throw new Error("查询房间失败：HTTP " + roomResponse.status);
      const roomData = await roomResponse.json();
      if (roomData.code !== 0 || !roomData.data || !roomData.data.room_id) {
        throw new Error("无法确认真实房间号：" + (roomData.message || roomData.msg || roomData.code));
      }
      const roomId = String(roomData.data.room_id);
      job.roomId = roomId;
      const currentRoom = location.hostname === "live.bilibili.com" &&
        location.pathname.match(/^\/(\d+)(?:\/|$)/);
      if (!currentRoom || currentRoom[1] !== roomNumber) {
        job.errorCode = "ROOM_CHANGED";
        throw new Error("直播间已切换，取消发送。");
      }
      const body = new URLSearchParams({
        roomid: roomId,
        msg: request.message,
        rnd: String(Math.floor(Date.now() / 1000)),
        fontsize: "25",
        color: "16777215",
        mode: "1",
        bubble: "0",
        csrf: csrf,
        csrf_token: csrf
      });
      const sendResponse = await fetch("https://api.live.bilibili.com/msg/send", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: body.toString()
      });
      if (!sendResponse.ok) throw new Error("发送失败：HTTP " + sendResponse.status);
      const sent = await sendResponse.json();
      if (sent.code !== 0) {
        throw new Error("B 站拒绝发送（" + sent.code + "）：" + (sent.message || sent.msg || "未知原因"));
      }
      job.ok = true;
    } catch (error) {
      job.error = String(error);
    } finally {
      job.state = "done";
      if (getJob() && getJob().id === job.id) saveJob(job);
    }
  })();
  data.ok = true;
  data.state = "pending";
  return finish();
})();
