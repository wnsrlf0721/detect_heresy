let enabled = false;
let navigating = false;
let lastReported = null;

function currentVideo() {
  const selector = location.pathname.startsWith("/shorts/")
    ? "ytd-reel-video-renderer[is-active] video"
    : "#movie_player video.html5-main-video";
  return document.querySelector(selector);
}

function reportPlayback(video) {
  if (!enabled || navigating || !video || video.paused || video.ended) return;
  const id = youtubeVideoId(location.href);
  if (!id || id === lastReported) return;
  if (video !== currentVideo() || video.closest(".ad-showing")) return;
  lastReported = id;
  chrome.runtime.sendMessage({ type: "video-playing", videoId: id }).then(
    (response) => {
      if (!response?.ok && lastReported === id) lastReported = null;
    },
    () => {
      if (lastReported === id) lastReported = null;
    },
  );
}

document.addEventListener("playing", (event) => reportPlayback(event.target), true);
// 유튜브가 광고에서 본 영상으로 전환할 때 같은 video 요소를 재사용할 수 있다.
document.addEventListener("timeupdate", (event) => reportPlayback(event.target), true);
document.addEventListener("yt-navigate-start", () => {
  navigating = true;
});
document.addEventListener("yt-navigate-finish", () => {
  navigating = false;
  if (lastReported !== youtubeVideoId(location.href)) lastReported = null;
  reportPlayback(currentVideo());
});

function setEnabled(value) {
  enabled = value === true;
  if (enabled) reportPlayback(currentVideo());
  else lastReported = null;
}

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.enabled) setEnabled(changes.enabled.newValue);
});
chrome.storage.local.get("enabled").then(({ enabled: value }) => setEnabled(value));
