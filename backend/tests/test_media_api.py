"""API 기반 추출기(OpenAI 음성 인식, 비전 OCR)를 실제 호출 없이 검증한다."""

import httpx
import numpy as np
import pytest

from app.errors import AnalysisError
from app.media import ocr
from app.media.ocr import VisionFrameReader, encode_jpeg
from app.media.stt import OpenAITranscriber


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "audio.webm"
    path.write_bytes(b"fake-audio")
    return path


def make_transcriber(response: httpx.Response, api_key="key"):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    transcriber = OpenAITranscriber(api_key, "whisper-1")
    transcriber._client = httpx.Client(transport=httpx.MockTransport(handler))
    return transcriber, requests


def test_openai_segments_become_stt_segments(audio):
    body = {"segments": [{"start": 4.2, "text": " 오늘의 주제는 욕심입니다."}, {"start": 135.0, "text": " "}, {"start": 3735.9, "text": "끝"}]}
    transcriber, requests = make_transcriber(httpx.Response(200, json=body))

    segments = transcriber.transcribe(audio)

    assert [(s.time, s.text, s.source) for s in segments] == [
        ("00:04", "오늘의 주제는 욕심입니다.", "stt"),
        ("1:02:15", "끝", "stt"),
    ]
    sent = requests[0].content
    assert requests[0].headers["authorization"] == "Bearer key"
    assert b"verbose_json" in sent and b"whisper-1" in sent and b"fake-audio" in sent


def test_openai_without_key_fails_before_any_request(audio):
    transcriber, requests = make_transcriber(httpx.Response(200, json={}), api_key=None)

    with pytest.raises(AnalysisError, match="OPENAI_API_KEY"):
        transcriber.transcribe(audio)
    assert requests == []


def test_openai_error_status_is_reported(audio):
    transcriber, _ = make_transcriber(httpx.Response(401, text="Incorrect API key"))

    with pytest.raises(AnalysisError, match="401"):
        transcriber.transcribe(audio)


def test_openai_rejects_file_over_size_limit(audio, monkeypatch):
    monkeypatch.setattr(OpenAITranscriber, "MAX_BYTES", 5)
    transcriber, requests = make_transcriber(httpx.Response(200, json={}))

    with pytest.raises(AnalysisError, match="25MB"):
        transcriber.transcribe(audio)
    assert requests == []


class FakeVision:
    def __init__(self, texts):
        self.texts = texts
        self.images: list[bytes] = []

    def read_frames(self, images):
        self.images = images
        return self.texts


def test_vision_reader_sends_jpegs_and_dedupes_texts(monkeypatch):
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    monkeypatch.setattr(ocr, "sample_frames", lambda path, interval: iter([(0.0, frame), (3.0, frame), (6.0, frame)]))
    vision = FakeVision(["요한복음 3장 16절", "요한복음 3장 16절", ""])

    segments = VisionFrameReader(vision, 3.0).read("video.mp4")

    assert [(s.time, s.text, s.source) for s in segments] == [("00:00", "요한복음 3장 16절", "ocr")]
    assert len(vision.images) == 3
    assert all(image.startswith(b"\xff\xd8") for image in vision.images)  # JPEG


def test_encode_jpeg_shrinks_large_frames():
    import cv2

    small = encode_jpeg(np.zeros((2160, 3840, 3), dtype=np.uint8))
    height, width = cv2.imdecode(np.frombuffer(small, np.uint8), cv2.IMREAD_COLOR).shape[:2]
    assert (width, height) == (1280, 720)
