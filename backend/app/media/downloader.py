import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.errors import AnalysisError
from app.media import format_time
from app.schemas.analysis import Segment

# 자동 자막은 몇 단어씩 끊겨 있어서, 이 길이가 될 때까지 이어 붙여 한 구간으로 만든다.
CAPTION_MIN_CHARS = 60


@dataclass
class Media:
    title: str
    duration: int  # 초
    audio_path: Path
    video_path: Path
    captions: list[Segment]
    warnings: list[str]


class MediaSource(Protocol):
    def fetch(self, url: str, workdir: Path) -> Media: ...


def parse_json3(raw: bytes) -> list[Segment]:
    """유튜브 json3 자막을 구간으로 바꾼다."""
    lines: list[tuple[float, str]] = []
    for event in json.loads(raw).get("events", []):
        # aAppend 는 자동 자막에서 줄바꿈만 덧붙이는 이벤트다.
        if event.get("aAppend") or "segs" not in event:
            continue
        text = " ".join("".join(seg.get("utf8", "") for seg in event["segs"]).split())
        if text:
            lines.append((event.get("tStartMs", 0) / 1000, text))

    segments: list[Segment] = []
    start, buffer = 0.0, ""
    for time, text in lines:
        if not buffer:
            start = time
        buffer = f"{buffer} {text}".strip()
        if len(buffer) >= CAPTION_MIN_CHARS:
            segments.append(Segment(time=format_time(start), text=buffer, source="caption"))
            buffer = ""
    if buffer:
        segments.append(Segment(time=format_time(start), text=buffer, source="caption"))
    return segments


def _caption_urls(info: dict) -> list[str]:
    """시도할 자막 주소. 사람이 올린 자막, 원본 자동 자막, 번역 경로의 자동 자막 순이다."""
    candidates = [
        (info.get("subtitles") or {}, "ko"),
        (info.get("automatic_captions") or {}, "ko-orig"),
        (info.get("automatic_captions") or {}, "ko"),
    ]
    return [
        fmt["url"] for tracks, lang in candidates for fmt in tracks.get(lang, []) if fmt.get("ext") == "json3"
    ]


class YtDlpSource:
    # 음성과 화면을 따로 받아서 ffmpeg 병합 없이 쓴다. 화면은 OpenCV가 읽을 수 있는 H.264로 고른다.
    # 음성 인식 API의 파일 크기 한도(25MB) 때문에 음성은 낮은 비트레이트로 받는다. 말소리 인식에는 충분하다.
    AUDIO_FORMAT = "ba[abr<=80]/wa/b"
    VIDEO_FORMAT = "bv[vcodec^=avc1][height<=720]/b[vcodec^=avc1][height<=720]/b[height<=720]/b"

    DOWNLOAD_ATTEMPTS = 5

    def __init__(self, max_seconds: int):
        self._max_seconds = max_seconds

    def _options(self, **extra) -> dict:
        return {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "js_runtimes": {"node": {}}} | extra

    def fetch(self, url: str, workdir: Path) -> Media:
        import yt_dlp

        try:
            with yt_dlp.YoutubeDL(self._options()) as ydl:
                info = ydl.extract_info(url, download=False)
                if info.get("is_live"):
                    raise AnalysisError("실시간 방송은 분석할 수 없습니다.")
                duration = int(info.get("duration") or 0)
                if duration > self._max_seconds:
                    raise AnalysisError(
                        f"영상이 너무 깁니다. {self._max_seconds // 60}분 이하의 영상만 지원합니다."
                    )
                captions, warnings = self._captions(ydl, info)

            paths = {
                name: self._download(url, fmt, workdir / f"{name}.%(ext)s")
                for name, fmt in (("audio", self.AUDIO_FORMAT), ("video", self.VIDEO_FORMAT))
            }
        except yt_dlp.utils.DownloadError as e:
            raise AnalysisError(f"영상을 가져오지 못했습니다: {e}") from e

        return Media(
            title=info.get("title") or "",
            duration=duration,
            audio_path=paths["audio"],
            video_path=paths["video"],
            captions=captions,
            warnings=warnings,
        )

    def _download(self, url: str, fmt: str, outtmpl: Path) -> Path:
        """유튜브가 내려받기 주소에 간헐적으로 403을 돌려줘서, 주소를 새로 받아 다시 시도한다."""
        import yt_dlp

        for attempt in range(self.DOWNLOAD_ATTEMPTS):
            try:
                with yt_dlp.YoutubeDL(self._options(format=fmt, outtmpl=str(outtmpl))) as ydl:
                    return Path(ydl.prepare_filename(ydl.extract_info(url, download=True)))
            except yt_dlp.utils.DownloadError:
                if attempt == self.DOWNLOAD_ATTEMPTS - 1:
                    raise
                time.sleep(1 + attempt)
        raise AssertionError("unreachable")

    def _captions(self, ydl, info: dict) -> tuple[list[Segment], list[str]]:
        urls = _caption_urls(info)
        if not urls:
            return [], ["이 영상에는 한국어 자막이 없습니다."]
        error: Exception | None = None
        # 같은 언어에 주소가 여러 개 있고 일부만 429로 막히는 일이 있어 차례로 시도한다.
        for caption_url in urls:
            try:
                return parse_json3(ydl.urlopen(caption_url).read()), []
            except Exception as e:  # 자막만 실패해도 음성·화면 추출은 계속한다.
                error = e
        return [], [f"자막을 가져오지 못했습니다: {error}"]
