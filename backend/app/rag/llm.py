import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Protocol

import anthropic

from app import prompts
from app.errors import AnalysisError
from app.schemas.llm import FrameTexts, LLMAnalysis, SegmentSelection


class Analyzer(Protocol):
    def analyze(self, system: str, user: str) -> LLMAnalysis: ...


class Screener(Protocol):
    """긴 영상에서 정밀 분석할 구간을 먼저 골라낸다(1차 선별)."""

    def screen(self, system: str, user: str) -> SegmentSelection: ...


@contextmanager
def _api_errors():
    """SDK 예외를 화면에 그대로 보여 줄 수 있는 AnalysisError 로 바꾼다."""
    try:
        yield
    except anthropic.AuthenticationError as e:
        raise AnalysisError("Anthropic API 키가 올바르지 않습니다.") from e
    except anthropic.RateLimitError as e:
        raise AnalysisError("LLM 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIStatusError as e:
        raise AnalysisError(f"LLM 요청 실패 ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AnalysisError("LLM 서버에 연결하지 못했습니다.") from e


def _parsed(response):
    if response.stop_reason == "refusal":
        raise AnalysisError("LLM이 이 내용의 분석을 거절했습니다.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AnalysisError("LLM 응답이 완성되지 않았습니다.")
    return response.parsed_output


class ClaudeAnalyzer:
    def __init__(self, api_key: str | None, model: str, effort: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._effort = effort

    def analyze(self, system: str, user: str) -> LLMAnalysis:
        with _api_errors():
            # output_format 으로 넘긴 스키마에 맞춰 응답이 생성되고, SDK가 Pydantic 으로 다시 검증한다.
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self._effort},
                output_format=LLMAnalysis,
                # 안전 분류기가 요청을 거절하면 서버가 권장 대체 모델로 다시 실행한다.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        return _parsed(response)


class _ClaudeLight:
    """판단이 가벼운 보조 작업(1차 선별)을 저렴한 모델로 처리한다."""

    def __init__(self, api_key: str | None, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _parse(self, system: str, user: str, output_format):
        with _api_errors():
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low"},
                output_format=output_format,
            )
        return _parsed(response)


class ClaudeScreener(_ClaudeLight):
    def screen(self, system: str, user: str) -> SegmentSelection:
        return self._parse(system, user, SegmentSelection)


class ClaudeVision:
    """영상 프레임의 글자를 읽는다(OCR). 판단이 필요 없는 단순 작업이라 판별과 다른 가벼운 모델을 쓴다."""

    FRAMES_PER_CALL = 10
    MAX_PARALLEL_CALLS = 4

    def __init__(self, api_key: str | None, model: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _read_batch(self, images: list[bytes]) -> list[str]:
        content = []
        for index, image in enumerate(images):
            content.append({"type": "text", "text": f"프레임 {index}"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.standard_b64encode(image).decode(),
                    },
                }
            )
        with _api_errors():
            response = self._client.beta.messages.parse(
                model=self._model,
                max_tokens=16000,
                system=prompts.ocr_system_prompt(),
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "low"},
                output_format=FrameTexts,
            )
        texts = [""] * len(images)
        for frame in _parsed(response).frames:
            if 0 <= frame.index < len(images):
                texts[frame.index] = frame.text
        return texts

    def read_frames(self, images: list[bytes]) -> list[str]:
        batches = [images[i : i + self.FRAMES_PER_CALL] for i in range(0, len(images), self.FRAMES_PER_CALL)]
        with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_CALLS) as pool:
            return [text for batch in pool.map(self._read_batch, batches) for text in batch]
