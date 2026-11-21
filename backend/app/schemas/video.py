"""영상 분석 API(/videos)의 요청·응답 스키마. 추출부터 판별, 대주제 정리까지 한 작업으로 처리한다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.media import youtube_video_id
from app.schemas.analysis import AnalysisResult, JobStatus
from app.schemas.reference import Verdict
from app.schemas.transcript import TranscriptResult, check_youtube_url

VideoSource = Literal["caption", "stt", "ocr"]


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=500)
    # 생략하면 수동 자막과 음성 인식 중 하나를 고른다. 기존 호출자가 출처를 지정할 수도 있다.
    sources: list[VideoSource] | None = Field(default=None, min_length=1)
    # 저장된 분석이 있어도 추출부터 다시 한다.
    force: bool = False

    @field_validator("url")
    @classmethod
    def _youtube_video(cls, value: str) -> str:
        check_youtube_url(value)
        if youtube_video_id(value) is None:
            raise ValueError("유튜브 영상 주소에서 영상을 찾지 못했습니다.")
        return value

    @field_validator("sources")
    @classmethod
    def _normalize(cls, value: list[str] | None) -> list[str] | None:
        """같은 조합이 같은 저장 결과를 가리키도록 중복을 없애고 정렬한다."""
        return sorted(set(value)) if value is not None else None


class VideoPreview(BaseModel):
    """분석 전에 입력한 주소가 맞는 영상인지 보여 주는 정보."""

    video_id: str
    title: str | None = None  # 퍼가기가 막힌 영상은 제목을 알 수 없다
    author: str | None = None
    thumbnail_url: str
    embeddable: bool  # false 면 화면에서 재생하지 못하고 썸네일만 보여 준다


class VideoTopic(BaseModel):
    title: str  # 대주제 한 줄
    summary: str
    keywords: list[str]


class RelatedVideo(BaseModel):
    """대주제가 비슷한 이전 영상 분석."""

    id: str
    url: str
    title: str  # 영상 제목
    topic: str  # 대주제 한 줄
    verdict: Verdict
    score: int
    similarity: float  # 대주제 임베딩의 코사인 유사도
    created_at: datetime


class VideoStatus(BaseModel):
    id: str
    status: JobStatus
    progress: str | None = None


class VideoResponse(VideoStatus):
    """작업 형태의 응답. pending 으로 먼저 돌려주고 GET 으로 상태를 확인한다.
    저장된 분석을 돌려줄 때는 처음부터 done 이고 cached 가 true 다."""

    url: str
    sources: list[VideoSource]
    created_at: datetime
    log: list[str] = []  # 진행 과정. 추출과 판별에서 실제로 한 일을 한 줄씩 (화면 표시용)
    log_times: list[datetime] = []  # 값은 log의 끝에서부터 대응한다.
    cached: bool = False
    transcript: TranscriptResult | None = None  # 추출이 끝나면 판별 전이라도 채워진다
    result: AnalysisResult | None = None  # status 가 done 일 때만 채워진다
    topic: VideoTopic | None = None  # 대주제 정리에 실패하면 비어 있다
    related: list[RelatedVideo] = []  # 조회할 때마다 새로 찾는다
    error: str | None = None
