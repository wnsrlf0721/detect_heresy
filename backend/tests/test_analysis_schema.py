import pytest
from pydantic import ValidationError

from app.schemas.analysis import AnalysisRequest, AnalysisResponse, Finding, Segment


@pytest.mark.parametrize("time", ["02:15", "2:15", "1:02:15", None])
def test_segment_accepts_valid_time(time):
    assert Segment(time=time, text="본문").time == time


@pytest.mark.parametrize("time", ["2분 15초", "02:75", "135", ""])
def test_segment_rejects_invalid_time(time):
    with pytest.raises(ValidationError):
        Segment(time=time, text="본문")


def test_plain_text_input_needs_only_text():
    request = AnalysisRequest.model_validate({"segments": [{"text": "보석은 말씀 가진 사람을 뜻합니다."}]})
    assert request.segments[0].source == "user"
    assert request.segments[0].time is None


def test_stt_shape_from_project_doc_is_accepted():
    request = AnalysisRequest.model_validate(
        {"segments": [{"time": "02:15", "text": "이 땅 육의 세계의 천국이 되는 거겠죠", "source": "stt"}]}
    )
    assert request.segments[0].time == "02:15"


@pytest.mark.parametrize("payload", [{"segments": []}, {"segments": [{"text": ""}]}, {"text": "본문"}])
def test_invalid_request_is_rejected(payload):
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(payload)


def test_finding_score_is_bounded():
    with pytest.raises(ValidationError):
        Finding(source="user", quote="발언", score=101, reason="이유", orthodox_refutation="반증")


@pytest.mark.parametrize("source", ["user", "stt", "ocr", "caption"])
def test_every_source_is_accepted(source):
    assert Segment(text="본문", source=source).source == source


def test_unknown_source_is_rejected():
    with pytest.raises(ValidationError):
        Segment(text="본문", source="video")


def test_pending_response_has_no_result():
    response = AnalysisResponse(id="a1", status="pending")
    assert response.result is None
