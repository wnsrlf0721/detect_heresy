"""영상 → 텍스트 추출 결과의 스키마. 영상 분석 API(/videos) 응답의 transcript 로 쓰인다."""

from urllib.parse import urlparse

from pydantic import BaseModel, computed_field

from app.media.merge import merge_sources
from app.schemas.analysis import Segment

ALLOWED_HOSTS = {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}


def check_youtube_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("유튜브 영상 주소만 지원합니다.")
    return value


class TranscriptResult(BaseModel):
    title: str
    duration: int  # 초
    # caption(영상 자막) / stt(음성 인식) / ocr(화면 글자)가 섞여 있고, 출처별로 시간순이다.
    segments: list[Segment]
    # 일부 출처만 실패했을 때의 안내. 나머지 출처의 결과는 그대로 돌려준다.
    warnings: list[str] = []

    @computed_field
    @property
    def merged(self) -> list[Segment]:
        """화면에 보여 주는 합친 텍스트. 세 출처에서 겹치는 내용을 하나로 줄인다(app/media/merge.py)."""
        return merge_sources(self.segments)
