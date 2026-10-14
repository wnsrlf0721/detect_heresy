"""추출 파이프라인: 영상 주소 → 내려받기 → 자막·음성·화면 글자 → 구간 목록."""

import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.errors import AnalysisError
from app.media.downloader import MediaSource
from app.media.ocr import FrameReader
from app.media.stt import Transcriber
from app.schemas.analysis import Segment
from app.schemas.transcript import TranscriptResult


class TranscriptPipeline:
    def __init__(self, source: MediaSource, transcriber: Transcriber, reader: FrameReader):
        self._source = source
        self._transcriber = transcriber
        self._reader = reader

    def run(self, url: str, on_progress: Callable[[str], None] = lambda _: None) -> TranscriptResult:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            on_progress("영상 내려받는 중")
            media = self._source.fetch(url, Path(workdir))
            warnings = list(media.warnings)

            # 둘 다 API 응답을 기다리는 일이라 동시에 돌린다.
            on_progress("음성과 화면 글자를 읽는 중")
            stt_warnings: list[str] = []
            ocr_warnings: list[str] = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                stt_job = pool.submit(
                    self._step, "음성 인식", lambda: self._transcriber.transcribe(media.audio_path), stt_warnings
                )
                ocr_job = pool.submit(
                    self._step, "화면 글자 인식", lambda: self._reader.read(media.video_path), ocr_warnings
                )
                stt, ocr = stt_job.result(), ocr_job.result()
            warnings += stt_warnings + ocr_warnings

        segments = media.captions + stt + ocr
        if not segments:
            raise AnalysisError("영상에서 텍스트를 추출하지 못했습니다. " + " ".join(warnings))
        return TranscriptResult(
            title=media.title, duration=media.duration, segments=segments, warnings=warnings
        )

    @staticmethod
    def _step(name: str, run: Callable[[], list[Segment]], warnings: list[str]) -> list[Segment]:
        """한 출처가 실패해도 나머지 출처의 결과는 살린다."""
        try:
            return run()
        except Exception as e:
            warnings.append(f"{name}에 실패했습니다: {e}")
            return []
