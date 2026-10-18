"""LLM이 반환해야 하는 구조. API 응답(schemas/analysis.py)과 분리해 둔다.

LLM에게는 판단만 맡기고, 시간·출처·근거 문서·종합 등급은 코드가 채운다.
"""

from pydantic import BaseModel, Field

from app.schemas.reference import Topic


class LLMFinding(BaseModel):
    segment_index: int  # 프롬프트에 넣은 구간 번호
    quote: str  # 해당 구간에서 그대로 옮긴 문제 발언
    score: int = Field(ge=0, le=100)
    group: str | None  # 유사한 교리를 가르치는 단체. 특정할 수 없으면 null
    topic: Topic | None
    reason: str
    orthodox_refutation: str
    heresy_intent: str | None
    scripture: list[str]
    reference_ids: list[str]  # 근거로 삼은 참고 자료 id


class LLMAnalysis(BaseModel):
    summary: str
    findings: list[LLMFinding]


class FrameText(BaseModel):
    index: int  # 프롬프트에 넣은 프레임 번호
    text: str  # 화면에 보이는 글자. 없으면 빈 문자열


class FrameTexts(BaseModel):
    frames: list[FrameText]


class SegmentSelection(BaseModel):
    """1차 선별 결과. 정밀 분석이 필요한 구간 번호."""

    indices: list[int]


class LLMTopic(BaseModel):
    title: str  # 영상의 대주제 한 줄
    summary: str  # 2~3문장 요약
    keywords: list[str]
