from collections.abc import Iterator
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from app.errors import AnalysisError
from app.media import format_time
from app.schemas.analysis import Segment
from app.timing import measure

MIN_CONFIDENCE = 0.4
# 직전 구간과 이만큼 비슷하면 같은 화면 글자로 보고 다시 싣지 않는다.
SAME_TEXT_RATIO = 0.8
# 직전에 읽은 프레임과 픽셀 차이(0~255 평균)가 이보다 작으면 화면이 그대로라고 보고 건너뛴다.
SAME_FRAME_DIFF = 2.0
# API로 보내는 프레임의 긴 변 최대 길이
MAX_FRAME_SIDE = 1280


class FrameReader(Protocol):
    def read(self, video_path: Path) -> list[Segment]: ...


class VisionReader(Protocol):
    """이미지(JPEG) 여러 장에서 글자를 읽어, 같은 순서로 돌려준다."""

    def read_frames(self, images: list[bytes]) -> list[str]: ...


def dedupe(frames: list[tuple[float, str]]) -> list[Segment]:
    """(초, 글자) 목록에서 화면에 계속 떠 있는 같은 글자를 처음 나온 시점 하나로 줄인다."""
    segments: list[Segment] = []
    previous = ""
    for seconds, text in frames:
        text = " ".join(text.split())
        if not text:
            previous = ""
            continue
        if SequenceMatcher(None, previous, text).ratio() < SAME_TEXT_RATIO:
            segments.append(Segment(time=format_time(seconds), text=text[:2000], source="ocr"))
        previous = text
    return segments


def sample_frames(video_path: Path, interval_seconds: float) -> Iterator[tuple[float, object]]:
    """일정 간격으로 프레임을 뽑되, 직전에 뽑은 것과 화면이 그대로면 건너뛴다."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise AnalysisError("영상 화면을 열지 못했습니다.")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, round(fps * interval_seconds))
        index, last_thumb = 0, None
        while capture.grab():
            if index % step == 0:
                ok, frame = capture.retrieve()
                if ok:
                    thumb = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
                    if last_thumb is None or cv2.absdiff(thumb, last_thumb).mean() >= SAME_FRAME_DIFF:
                        last_thumb = thumb
                        yield index / fps, frame
            index += 1
    finally:
        capture.release()


def encode_jpeg(frame) -> bytes:
    import cv2

    height, width = frame.shape[:2]
    scale = MAX_FRAME_SIDE / max(height, width)
    if scale < 1:
        frame = cv2.resize(frame, (round(width * scale), round(height * scale)))
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise AnalysisError("프레임을 이미지로 바꾸지 못했습니다.")
    return buffer.tobytes()


class VisionFrameReader:
    """프레임을 뽑아 비전 API(VisionReader)로 읽는다."""

    def __init__(self, vision: VisionReader, interval_seconds: float):
        self._vision = vision
        self._interval = interval_seconds

    def read(self, video_path: Path) -> list[Segment]:
        with measure("ocr_frame_preparation"):
            frames = [(seconds, encode_jpeg(frame)) for seconds, frame in sample_frames(video_path, self._interval)]
        texts = self._vision.read_frames([image for _, image in frames])
        return dedupe([(seconds, text) for (seconds, _), text in zip(frames, texts, strict=True)])


class EasyOcrReader:
    """EasyOCR로 이 컴퓨터에서 읽는다. `uv sync --extra local` 로 설치해야 하고, 모델은 처음 쓸 때 내려받는다."""

    def __init__(self, interval_seconds: float, device: str):
        self._interval = interval_seconds
        self._gpu = device != "cpu"
        self._reader = None

    def read(self, video_path: Path) -> list[Segment]:
        if self._reader is None:
            import easyocr

            self._reader = easyocr.Reader(["ko", "en"], gpu=self._gpu, verbose=False)

        results: list[tuple[float, str]] = []
        for seconds, frame in sample_frames(video_path, self._interval):
            lines = self._reader.readtext(frame, paragraph=False)
            results.append((seconds, " ".join(text for _, text, confidence in lines if confidence >= MIN_CONFIDENCE)))
        return dedupe(results)
