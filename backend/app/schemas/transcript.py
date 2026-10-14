"""텍스트 추출 API(/transcripts)의 요청·응답 스키마."""

from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analysis import JobStatus, Segment

ALLOWED_HOSTS = {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}


class TranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def _youtube_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("유튜브 영상 주소만 지원합니다.")
        return value


class TranscriptResult(BaseModel):
    title: str
    duration: int  # 초
    # caption(영상 자막) / stt(음성 인식) / ocr(화면 글자)가 섞여 있고, 출처별로 시간순이다.
    # 그대로 POST /analyses 의 segments 로 넘길 수 있다.
    segments: list[Segment]
    # 일부 출처만 실패했을 때의 안내. 나머지 출처의 결과는 그대로 돌려준다.
    warnings: list[str] = []


class TranscriptResponse(BaseModel):
    """작업 형태의 응답. 추출은 오래 걸리므로 pending 으로 먼저 돌려주고 GET 으로 상태를 확인한다."""

    id: str
    status: JobStatus
    progress: str | None = None  # 진행 중인 단계 (화면 표시용)
    result: TranscriptResult | None = None  # status 가 done 일 때만 채워진다
    error: str | None = None
