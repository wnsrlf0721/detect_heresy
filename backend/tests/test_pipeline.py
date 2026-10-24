import json
from pathlib import Path

import pytest

from app.errors import AnalysisError
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
    assert stages == [
        "영상을 내려받는 중입니다.",
        "‘제목’ 영상(4분 0초)을 내려받았습니다.",
        "영상에 딸린 자막에서 1구간을 가져왔습니다.",
        "음성을 받아쓰고 화면 글자를 읽는 중입니다.",
        "음성 인식으로 1구간을 받아썼습니다.",
        "화면에서 글자 1구간을 읽었습니다.",
    ]
    AnalysisRequest(segments=result.segments)  # 그대로 판별 요청이 된다


def test_pipeline_keeps_other_sources_when_one_fails():
    pipeline = TranscriptPipeline(
        FakeSource(warnings=["이 영상에는 한국어 자막이 없습니다."]), FakeStep([STT]), FakeStep(RuntimeError("모델 오류"))
    )
    stages = []
    result = pipeline.run(URL, stages.append)

    assert result.segments == [STT]
    assert result.warnings == ["이 영상에는 한국어 자막이 없습니다.", "화면 글자 인식에 실패했습니다: 모델 오류"]
    assert stages[2] == "영상에 딸린 한국어 자막이 없어, 말은 음성 인식으로 받아씁니다."
    assert stages[-2:] == ["음성 인식으로 1구간을 받아썼습니다.", "화면 글자 인식에 실패했습니다: 모델 오류"]


def test_pipeline_fails_when_nothing_is_extracted():
    with pytest.raises(AnalysisError, match="추출하지 못했습니다"):
        TranscriptPipeline(FakeSource(), FakeStep([]), FakeStep([])).run(URL)

