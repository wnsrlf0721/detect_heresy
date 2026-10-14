from pathlib import Path
from typing import Protocol

import httpx

from app.errors import AnalysisError
from app.media import format_time
from app.schemas.analysis import Segment

SAMPLE_RATE = 16000


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> list[Segment]: ...


class OpenAITranscriber:
    """OpenAI 음성 인식 API. 구간별 시작 시각을 받으려고 verbose_json 으로 요청한다."""

    URL = "https://api.openai.com/v1/audio/transcriptions"
    MAX_BYTES = 25 * 1024 * 1024  # API의 파일 크기 한도

    def __init__(self, api_key: str | None, model: str):
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(timeout=600)

    def transcribe(self, audio_path: Path) -> list[Segment]:
        if not self._api_key:
            raise AnalysisError("OPENAI_API_KEY 가 설정되지 않았습니다.")
        if audio_path.stat().st_size > self.MAX_BYTES:
            raise AnalysisError("음성 파일이 25MB를 넘어 음성 인식 API로 보낼 수 없습니다.")
        try:
            with audio_path.open("rb") as audio:
                response = self._client.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files={"file": (audio_path.name, audio)},
                    data={
                        "model": self._model,
                        "language": "ko",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "segment",
                    },
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AnalysisError(f"음성 인식 요청 실패 ({e.response.status_code}): {e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise AnalysisError(f"음성 인식 요청 실패: {e}") from e
        return [
            Segment(time=format_time(s["start"]), text=text, source="stt")
            for s in response.json().get("segments", [])
            if (text := s["text"].strip())
        ]


def decode_audio(audio_path: Path):
    """오디오 파일을 Whisper 입력(16kHz 모노 float32)으로 바꾼다. PyAV를 직접 써서 ffmpeg 설치가 필요 없다."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(str(audio_path)) as container:
        for frame in container.decode(audio=0):
            chunks += [out.to_ndarray().reshape(-1) for out in resampler.resample(frame)]
        chunks += [out.to_ndarray().reshape(-1) for out in resampler.resample(None)]
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class WhisperTranscriber:
    """오픈소스 Whisper(faster-whisper)를 이 컴퓨터에서 돌린다. `uv sync --extra local` 로 설치해야 하고,
    모델은 처음 쓸 때 내려받는다. CPU로는 느리므로 GPU(device="cuda")가 있을 때 쓴다."""

    def __init__(self, model: str, device: str):
        self._model_name = model
        self._device = device
        self._model = None

    def transcribe(self, audio_path: Path) -> list[Segment]:
        if self._model is None:
            from faster_whisper import WhisperModel

            compute_type = "int8" if self._device == "cpu" else "float16"
            self._model = WhisperModel(self._model_name, device=self._device, compute_type=compute_type)
        # vad_filter 는 말이 없는 구간을 건너뛰어, 배경음악에서 없는 문장을 지어내는 일을 줄인다.
        segments, _ = self._model.transcribe(decode_audio(audio_path), language="ko", vad_filter=True)
        return [
            Segment(time=format_time(s.start), text=text, source="stt")
            for s in segments
            if (text := s.text.strip())
        ]
