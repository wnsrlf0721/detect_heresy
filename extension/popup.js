const toggle = document.querySelector("#enabled");
const status = document.querySelector("#status");
const result = document.querySelector("#result");
const progress = document.querySelector("#progress");
let clocks = [];
let refreshing = false;

function updateClocks() {
  for (const { time, submittedAt } of clocks) {
    const elapsed = Math.max(0, Math.floor((Date.now() - submittedAt) / 1000));
    time.textContent = `${Math.floor(elapsed / 60)}분 ${elapsed % 60}초 경과`;
  }
}

async function refreshProgress() {
  if (refreshing || clocks.length === 0) return;
  refreshing = true;
  try {
    await chrome.runtime.sendMessage({ type: "refresh-progress" });
  } catch {
    // 마지막으로 확인한 진행 상황을 유지하고 다음 주기에 다시 확인한다.
  } finally {
    refreshing = false;
  }
}

async function render() {
  const { enabled, pending = {}, last } = await chrome.storage.local.get(["enabled", "pending", "last"]);
  toggle.checked = enabled === true;
  const jobs = enabled ? Object.values(pending).sort((a, b) => b.submittedAt - a.submittedAt) : [];
  const count = jobs.length;
  status.textContent = !enabled
    ? "자동 분석 꺼짐"
    : count > 0
      ? `분석 중 ${count}건`
      : last?.message ?? "유튜브 영상 재생 대기 중";
  result.hidden = !last?.id;
  if (last?.id) result.href = resultUrl(last.id);
  progress.replaceChildren();
  clocks = jobs.map((job) => {
    const item = document.createElement("li");
    const time = document.createElement("time");
    const stage = document.createElement("span");
    stage.textContent = job.progress ?? (job.status === "running" ? "영상 분석 중" : "분석 접수 · 서버 응답 대기 중");
    item.append(time, stage);
    progress.append(item);
    return { time, submittedAt: job.submittedAt };
  });
  updateClocks();
}

toggle.addEventListener("change", async () => {
  toggle.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "set-enabled", enabled: toggle.checked });
    if (!response?.ok) throw new Error("설정 저장 실패");
    await render();
  } catch {
    await render();
    status.textContent = "설정을 저장하지 못했습니다. 다시 시도해 주세요.";
  } finally {
    toggle.disabled = false;
  }
});
chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "local") void render();
});
void render().then(() => {
  toggle.disabled = false;
  void refreshProgress();
});
setInterval(updateClocks, 1000);
setInterval(refreshProgress, 5000);
