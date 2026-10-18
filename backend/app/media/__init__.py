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
