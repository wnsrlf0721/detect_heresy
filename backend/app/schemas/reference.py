"""기준 데이터(정통 교리 / 이단 사례)와 평가셋의 스키마."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Topic(StrEnum):
    TRINITY = "trinity"  # 신론·삼위일체
    CHRISTOLOGY = "christology"  # 기독론
    SOTERIOLOGY = "soteriology"  # 구원론
    REVELATION = "revelation"  # 성경론·계시론
    ECCLESIOLOGY = "ecclesiology"  # 교회론
    ESCHATOLOGY = "eschatology"  # 종말론


class Verdict(StrEnum):
    SAFE = "safe"  # 안전
    CAUTION = "caution"  # 주의
    DANGER = "danger"  # 위험


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrthodoxDoc(_Record):
    """정통 교리 문서의 한 조항(문답 하나, 신조의 한 단락)."""

    id: str
    source: str  # 문서명 (예: 웨스트민스터 소요리문답)
    section: str  # 조항·문답 번호
    topic: Topic
    text: str = Field(min_length=1)
    scripture: list[str] = []
    # 공인 번역본·원출처와 대조해 사람이 확인했는지 여부
    verified: bool = False


class HeresyCase(_Record):
    """이단 교리 사례 하나. 결과 화면의 3단 비교(발언 ↔ 반증 ↔ 의도)의 재료가 된다."""

    id: str
    group: str  # 단체명
    topic: Topic
    claim: str = Field(min_length=1)  # 해당 단체가 가르치는 내용
    keywords: list[str] = []
    intent: str = Field(min_length=1)  # 이 교리가 노리는 원래 의도
    refutation: str = Field(min_length=1)  # 정통 교리의 반증
    orthodox_refs: list[str] = []  # 관련 OrthodoxDoc id
    scripture: list[str] = []
    source: str | None = None  # 근거 자료(교단 결의문, 상담 자료 등)
    verified: bool = False


class Chunk(_Record):
    """Vector DB에 적재되는 단위. text만 임베딩하고 나머지는 metadata로 보관한다."""

    id: str
    kind: Literal["orthodox", "heresy"]
    text: str
    metadata: dict


class EvalCase(_Record):
    """판별 품질 평가용 문장과 기대 결과."""

    id: str
    text: str = Field(min_length=1)
    expected_verdict: Verdict
    expected_group: str | None = None
    topic: Topic | None = None
    note: str | None = None
