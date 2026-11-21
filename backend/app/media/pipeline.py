"""추출 파이프라인: 영상 주소 → 내려받기 → 자막·음성·화면 글자 → 구간 목록."""

import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.errors import AnalysisError
from app.media import format_duration
from app.media.downloader import MediaSource
from app.media.ocr import FrameReader
from app.media.stt import Transcriber
from app.schemas.analysis import Segment
from app.schemas.transcript import TranscriptResult
from app.timing import measure, submit_timed


class TranscriptPipeline:
    def __init__(self, source: MediaSource, transcriber: Transcriber, reader: FrameReader):
        self._source = source
        self._transcriber = transcriber
        self._reader = reader

    def run(
        self, url: str, on_progress: Callable[[str], None] = lambda _: None, *, automatic_speech: bool = False
    ) -> TranscriptResult:
        """on_progress 로 단계마다 실제로 한 일을 알린다. 화면의 '진행 과정'에 그대로 쌓인다."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            on_progress("영상을 내려받는 중입니다.")
            media = self._source.fetch(url, Path(workdir), automatic_speech=automatic_speech)
            warnings = list(media.warnings)
            on_progress(f"‘{media.title}’ 영상({format_duration(media.duration)})을 내려받았습니다.")
            audio_path = None if automatic_speech and media.captions else media.audio_path
            if media.captions:
                on_progress(f"영상에 딸린 자막에서 {len(media.captions)}구간을 가져왔습니다.")
            elif automatic_speech:
                on_progress("사용할 수 있는 수동 한국어 자막이 없어 음성을 받아씁니다.")
            else:
                on_progress("영상에 딸린 한국어 자막이 없어, 말은 음성 인식으로 받아씁니다.")

            # 둘 다 API 응답을 기다리는 일이라 동시에 돌린다.
            stt_warnings: list[str] = []
            ocr_warnings: list[str] = []
            if audio_path is None:
                on_progress("수동 자막을 사용하고 화면 글자를 읽는 중입니다.")
                stt = []
                ocr = self._step("ocr", "화면 글자 인식", lambda: self._reader.read(media.video_path), ocr_warnings)
            else:
                on_progress("음성을 받아쓰고 화면 글자를 읽는 중입니다.")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    stt_job = submit_timed(
                        pool, self._step, "stt", "음성 인식", lambda: self._transcriber.transcribe(audio_path), stt_warnings
                    )
                    ocr_job = submit_timed(
                        pool, self._step, "ocr", "화면 글자 인식", lambda: self._reader.read(media.video_path), ocr_warnings
                    )
                    stt, ocr = stt_job.result(), ocr_job.result()
            warnings += stt_warnings + ocr_warnings
            if audio_path is not None and not stt_warnings:
                on_progress(f"음성 인식으로 {len(stt)}구간을 받아썼습니다.")
            if not ocr_warnings:
                on_progress(f"화면에서 글자 {len(ocr)}구간을 읽었습니다." if ocr else "화면에서 읽을 글자를 찾지 못했습니다.")
            for warning in stt_warnings + ocr_warnings:
                on_progress(warning)

        segments = media.captions + stt + ocr
        if not segments:
            raise AnalysisError("영상에서 텍스트를 추출하지 못했습니다. " + " ".join(warnings))
        return TranscriptResult(
            title=media.title, duration=media.duration, segments=segments, warnings=warnings
        )

    @staticmethod
    def _step(stage: str, name: str, run: Callable[[], list[Segment]], warnings: list[str]) -> list[Segment]:
        """한 출처가 실패해도 나머지 출처의 결과는 살린다."""
        try:
            with measure(stage):
                return run()
        except Exception as e:
            warnings.append(f"{name}에 실패했습니다: {e}")
            return []
