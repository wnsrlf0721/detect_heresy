"""판별 API(/analyses)의 요청·응답 스키마."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.reference import Topic, Verdict

# "02:15" 또는 "1:02:15"
TIME_PATTERN = r"^(\d+:)?[0-5]?\d:[0-5]\d$"


# 텍스트가 어디서 추출됐는지. 요청의 구간부터 결과의 적발 문장까지 그대로 유지된다.
# user: 사용자 직접 입력 / stt: 음성 인식 / ocr: 화면 속 글자 / caption: 영상에 딸린 자막
Source = Literal["user", "stt", "ocr", "caption"]


class Segment(BaseModel):
    """분석 대상 텍스트 한 구간. 영상 추출 결과와 사용자 직접 입력이 같은 형태를 쓴다."""

    model_config = ConfigDict(extra="forbid")

    time: str | None = Field(default=None, pattern=TIME_PATTERN)  # 직접 입력한 텍스트는 None
    text: str = Field(min_length=1, max_length=2000)
    source: Source = "user"


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[Segment] = Field(min_length=1, max_length=500)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Reference(BaseModel):
    """판별 근거로 쓰인 기준 데이터 한 건."""

    id: str  # 기준 데이터 id (예: wsc-33, scj-parable)
    kind: Literal["orthodox", "heresy"]
    label: str  # 화면 표시용 출처 (예: 웨스트민스터 소요리문답 제33문)
    excerpt: str


class Finding(BaseModel):
    """적발 문장 하나와 3단 비교(발언 ↔ 정통 반증 ↔ 이단의 의도)."""

    time: str | None = Field(default=None, pattern=TIME_PATTERN)
    source: Source
    quote: str  # 적발된 발언 원문
    score: int = Field(ge=0, le=100)
    group: str | None = None  # 유사한 교리를 가르치는 단체
    topic: Topic | None = None
    reason: str  # 왜 정통 교리에 위배되는지
    orthodox_refutation: str
    heresy_intent: str | None = None
    scripture: list[str] = []
    references: list[Reference] = []
    # 판별에 넘긴 구간 목록에서 적발된 구간의 번호. 저장할 때 구간(segments)과 잇는 데만 쓰고 응답에는 넣지 않는다.
    segment_index: int | None = Field(default=None, exclude=True)


class AnalysisResult(BaseModel):
    verdict: Verdict
    score: int = Field(ge=0, le=100)  # 종합 의심 지수(게이지)
    summary: str
    findings: list[Finding]


class AnalysisResponse(BaseModel):
    """작업 형태의 응답. 판별은 오래 걸리므로 pending 으로 먼저 돌려주고 GET 으로 상태를 확인한다."""

    id: str
    status: JobStatus
    result: AnalysisResult | None = None  # status 가 done 일 때만 채워진다
    error: str | None = None
