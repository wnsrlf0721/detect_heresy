"""영상 → 텍스트 추출. 자막(caption), 음성(stt), 화면 글자(ocr) 세 출처를 구간으로 만든다."""

import re
from urllib.parse import parse_qs, urlparse

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def youtube_video_id(url: str) -> str | None:
    """유튜브 주소에서 영상 ID를 꺼낸다. 같은 영상을 가리키는 여러 형태의 주소를 하나로 묶는 데 쓴다."""
    parsed = urlparse(url)
    if parsed.hostname == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif parsed.path == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    else:
        parts = parsed.path.strip("/").split("/")
        candidate = parts[1] if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed") else ""
    return candidate if _VIDEO_ID.fullmatch(candidate) else None


def format_time(seconds: float) -> str:
    """초를 구간의 time 형식("02:15", 한 시간이 넘으면 "1:02:15")으로 바꾼다."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_time(time: str) -> int:
    """구간의 time("02:15", "1:02:15")을 초로 바꾼다."""
    seconds = 0
    for part in time.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def format_duration(seconds: int) -> str:
    """영상 길이를 사람이 읽는 형태("12분 30초", "1시간 2분")로 바꾼다."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}시간 {minutes}분"
    return f"{minutes}분 {secs}초" if minutes else f"{secs}초"


def bigrams(text: str) -> set[str]:
    """공백을 뺀 글자 2-gram. 인식 결과가 조금씩 다른 두 텍스트가 같은 말인지 비교하는 데 쓴다."""
    compact = "".join(text.split())
    return {compact[i : i + 2] for i in range(len(compact) - 1)}
