importScripts("site.js", "youtube.js");

const POLL_ALARM = "poll-analyses";
const NOTIFICATION_PREFIX = "analysis:";
const ANALYSIS_ID = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const POLL_LIMIT_MS = 60 * 60 * 1000;

// 새 영상, 상태 조회, ON/OFF가 같은 저장 데이터를 동시에 덮어쓰지 않도록 순서대로 처리한다.
let operations = Promise.resolve();
function enqueue(work) {
  const operation = operations.then(work);
  operations = operation.catch((error) => console.warn(new Date().toISOString(), "분석 상태 처리 실패", error));
  return operation;
}

async function request(path, options) {
  const response = await fetch(SITE + "/api/videos" + path, {
    ...options,
    cache: "no-store",
    signal: AbortSignal.timeout(12_000),
  });
  if (!response.ok) {
    const error = new Error(`서버 응답 오류 (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const job = await response.json();
  if (!ANALYSIS_ID.test(job.id) || !["pending", "running", "done", "failed"].includes(job.status)) {
    throw new Error("분석 서버의 응답 형식을 확인해 주세요.");
  }
  return job;
}

async function syncAlarm(pending) {
  if (Object.keys(pending).length === 0) {
    await chrome.alarms.clear(POLL_ALARM);
  } else if (!await chrome.alarms.get(POLL_ALARM)) {
    await chrome.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
  }
}

async function notify(id) {
  try {
    await chrome.notifications.create(NOTIFICATION_PREFIX + id, {
      type: "basic",
      iconUrl: chrome.runtime.getURL("icon.png"),
      title: "영상 분석 완료",
      message: "알림을 클릭하면 분석 결과를 열 수 있습니다.",
    });
  } catch (error) {
    console.warn(new Date().toISOString(), "알림을 표시하지 못했습니다.", error);
  }
}

async function start(videoId) {
  const { enabled, pending = {} } = await chrome.storage.local.get(["enabled", "pending"]);
  if (!enabled || pending[videoId]) return;
  let job;
  try {
    job = await request("", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: "https://www.youtube.com/watch?v=" + videoId }),
    });
  } catch (error) {
    await chrome.storage.local.set({ last: { message: error.status ? error.message : "분석 서버에 연결하지 못했습니다." } });
    return;
  }
  if (job.status === "done") {
    await chrome.storage.local.set({ last: { id: job.id, message: "저장된 분석 결과를 열 수 있습니다." } });
    await notify(job.id);
  } else if (job.status === "failed") {
    await chrome.storage.local.set({ last: { message: "영상 분석에 실패했습니다." } });
  } else {
    pending[videoId] = { id: job.id, submittedAt: Date.now(), status: job.status, progress: job.progress };
    await chrome.storage.local.set({ pending, last: null });
    await syncAlarm(pending);
  }
}

async function poll() {
  const { enabled, pending = {} } = await chrome.storage.local.get(["enabled", "pending"]);
  if (!enabled) return syncAlarm({});
  const updates = await Promise.all(Object.entries(pending).map(async ([videoId, entry]) => {
    if (Date.now() - entry.submittedAt >= POLL_LIMIT_MS) {
      return { videoId, message: "분석 상태 확인 시간이 지났습니다." };
    }
    try {
      const job = await request("/" + entry.id + "/status");
      if (job.status === "done") return { videoId, id: job.id, message: "영상 분석이 완료되었습니다." };
      if (job.status === "failed") return { videoId, message: "영상 분석에 실패했습니다." };
      if (job.status !== entry.status || job.progress !== entry.progress) {
        return { videoId, pendingEntry: { ...entry, status: job.status, progress: job.progress } };
      }
    } catch (error) {
      if (error.status === 404) return { videoId, message: "서버에서 분석 작업을 찾을 수 없습니다." };
      // 연결이 잠시 끊겨도 새 작업을 접수하지 않고 기존 작업의 상태를 다시 확인한다.
    }
    return null;
  }));

  let last;
  const completed = [];
  for (const update of updates) {
    if (!update) continue;
    const { videoId, pendingEntry, ...message } = update;
    if (pendingEntry) {
      pending[videoId] = pendingEntry;
    } else {
      delete pending[videoId];
      last = message;
      if (message.id) completed.push(message.id);
    }
  }
  if (updates.some(Boolean)) await chrome.storage.local.set(last ? { pending, last } : { pending });
  for (const id of completed) await notify(id);
  await syncAlarm(pending);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "video-playing" && sender.tab && sender.frameId === 0) {
    const id = youtubeVideoId(sender.url);
    if (!id || id !== message.videoId) return;
    enqueue(() => start(id)).then(() => sendResponse({ ok: true }), () => sendResponse({ ok: false }));
    return true;
  }
  if (sender.url !== chrome.runtime.getURL("popup.html")) return;
  if (message?.type === "refresh-progress") {
    enqueue(poll).then(() => sendResponse({ ok: true }), () => sendResponse({ ok: false }));
    return true;
  }
  if (message?.type === "set-enabled") {
    enqueue(async () => {
      if (message.enabled === true) {
        await chrome.storage.local.set({ enabled: true });
      } else {
        await chrome.storage.local.set({ enabled: false, pending: {}, last: null });
        await syncAlarm({});
      }
    }).then(() => sendResponse({ ok: true }), () => sendResponse({ ok: false }));
    return true;
  }
});

function restoreAlarm() {
  void enqueue(async () => {
    const { enabled, pending = {} } = await chrome.storage.local.get(["enabled", "pending"]);
    await syncAlarm(enabled ? pending : {});
  });
}

chrome.runtime.onInstalled.addListener(restoreAlarm);
chrome.runtime.onStartup.addListener(restoreAlarm);
chrome.alarms.onAlarm.addListener(({ name }) => {
  if (name === POLL_ALARM) void enqueue(poll);
});
chrome.notifications.onClicked.addListener((notificationId) => {
  if (!notificationId.startsWith(NOTIFICATION_PREFIX)) return;
  const id = notificationId.slice(NOTIFICATION_PREFIX.length);
  if (ANALYSIS_ID.test(id)) void chrome.tabs.create({ url: resultUrl(id) });
});
