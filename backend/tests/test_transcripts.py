import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_pipeline, get_transcript_repository
from app.db.repository import InMemoryTranscriptRepository
from app.errors import AnalysisError
from app.main import app
from app.media import format_time
from app.media.downloader import Media, parse_json3
from app.media.ocr import dedupe
from app.media.pipeline import TranscriptPipeline
from app.schemas.analysis import AnalysisRequest, Segment

URL = "https://youtu.be/UeXJQ7cA7lo"


class FakeSource:
    def __init__(self, captions=(), warnings=(), error=None):
        self.captions, self.warnings, self.error = list(captions), list(warnings), error

    def fetch(self, url, workdir):
        if self.error:
            raise self.error
        return Media("제목", 240, Path(workdir) / "audio.m4a", Path(workdir) / "video.mp4", self.captions, self.warnings)


class FakeStep:
    """Transcriber 와 FrameReader 를 함께 흉내 낸다."""

    def __init__(self, output):
        self.output = output

    def _run(self, path):
        if isinstance(self.output, Exception):
            raise self.output
        return self.output

    transcribe = read = _run


CAPTION = Segment(time="00:01", text="자막", source="caption")
STT = Segment(time="00:02", text="음성", source="stt")
OCR = Segment(time="00:03", text="화면", source="ocr")


@pytest.mark.parametrize("seconds, expected", [(0, "00:00"), (135.9, "02:15"), (3735, "1:02:15")])
def test_format_time(seconds, expected):
    assert format_time(seconds) == expected
    Segment(time=expected, text="발언")  # 구간의 time 형식에 맞아야 한다


def test_parse_json3_merges_fragments_and_skips_append_events():
    events = [
        {"tStartMs": 1000, "segs": [{"utf8": "성경의"}, {"utf8": " 비유는"}]},
        {"tStartMs": 2000, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 3000, "segs": [{"utf8": "가" * 60}]},
        {"tStartMs": 65000, "segs": [{"utf8": "마지막 줄"}]},
        {"tStartMs": 70000},
    ]
    segments = parse_json3(json.dumps({"events": events}).encode())

    assert [(s.time, s.source) for s in segments] == [("00:01", "caption"), ("01:05", "caption")]
    assert segments[0].text == "성경의 비유는 " + "가" * 60
    assert segments[1].text == "마지막 줄"


def test_ocr_dedupe_keeps_first_appearance_of_each_text():
    frames = [
        (0, "오늘의 말씀 요한복음 3장 16절"),
        (3, "오늘의 말씀 요한복음 3장 16절"),
        (6, "오늘의 말씀 요한북음 3장 16절"),  # 같은 화면을 조금 다르게 읽은 경우
        (9, ""),
        (12, "오늘의 말씀 요한복음 3장 16절"),  # 화면에서 사라졌다가 다시 나오면 새 구간
        (15, "하나님이 세상을 이처럼 사랑하사"),
    ]
    assert [(s.time, s.text) for s in dedupe(frames)] == [
        ("00:00", "오늘의 말씀 요한복음 3장 16절"),
        ("00:12", "오늘의 말씀 요한복음 3장 16절"),
        ("00:15", "하나님이 세상을 이처럼 사랑하사"),
    ]


def test_pipeline_combines_three_sources_for_analysis():
    stages = []
    pipeline = TranscriptPipeline(FakeSource([CAPTION]), FakeStep([STT]), FakeStep([OCR]))
    result = pipeline.run(URL, stages.append)

    assert result.title == "제목" and result.duration == 240
    assert [s.source for s in result.segments] == ["caption", "stt", "ocr"]
    assert len(stages) == 2
    AnalysisRequest(segments=result.segments)  # 그대로 판별 요청이 된다


def test_pipeline_keeps_other_sources_when_one_fails():
    pipeline = TranscriptPipeline(
        FakeSource(warnings=["이 영상에는 한국어 자막이 없습니다."]), FakeStep([STT]), FakeStep(RuntimeError("모델 오류"))
    )
    result = pipeline.run(URL)

    assert result.segments == [STT]
    assert result.warnings == ["이 영상에는 한국어 자막이 없습니다.", "화면 글자 인식에 실패했습니다: 모델 오류"]


def test_pipeline_fails_when_nothing_is_extracted():
    with pytest.raises(AnalysisError, match="추출하지 못했습니다"):
        TranscriptPipeline(FakeSource(), FakeStep([]), FakeStep([])).run(URL)


@pytest.fixture
def make_client():
    def _make(pipeline):
        repository = InMemoryTranscriptRepository()
        app.dependency_overrides[get_pipeline] = lambda: pipeline
        app.dependency_overrides[get_transcript_repository] = lambda: repository
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def test_create_then_get_transcript(make_client):
    client = make_client(TranscriptPipeline(FakeSource([CAPTION]), FakeStep([STT]), FakeStep([OCR])))

    created = client.post("/transcripts", json={"url": URL})
    assert created.status_code == 202
    assert created.json()["status"] == "pending"

    # TestClient 는 응답을 돌려주기 전에 백그라운드 작업까지 끝낸다.
    body = client.get(f"/transcripts/{created.json()['id']}").json()
    assert body["status"] == "done"
    assert body["result"]["segments"][1] == {"time": "00:02", "text": "음성", "source": "stt"}


def test_download_failure_is_reported_as_failed_job(make_client):
    client = make_client(TranscriptPipeline(FakeSource(error=AnalysisError("영상이 너무 깁니다.")), FakeStep([]), FakeStep([])))

    body = client.get(f"/transcripts/{client.post('/transcripts', json={'url': URL}).json()['id']}").json()
    assert body["status"] == "failed"
    assert body["error"] == "영상이 너무 깁니다."


def test_unknown_transcript_is_404(make_client):
    assert make_client(None).get("/transcripts/없는-id").status_code == 404


@pytest.mark.parametrize("url", ["http://youtu.be/abc", "https://example.com/video.mp4", "file:///etc/passwd", ""])
def test_non_youtube_url_is_422(make_client, url):
    assert make_client(None).post("/transcripts", json={"url": url}).status_code == 422
