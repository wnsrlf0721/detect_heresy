from typing import Protocol

import anthropic

from app.errors import AnalysisError
from app.schemas.llm import LLMAnalysis


class Analyzer(Protocol):
    def analyze(self, system: str, user: str) -> LLMAnalysis: ...


class ClaudeAnalyzer:
    def __init__(self, api_key: str | None, model: str, effort: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._effort = effort

    def analyze(self, system: str, user: str) -> LLMAnalysis:
        try:
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
        except anthropic.AuthenticationError as e:
            raise AnalysisError("Anthropic API 키가 올바르지 않습니다.") from e
        except anthropic.RateLimitError as e:
            raise AnalysisError("LLM 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.") from e
        except anthropic.APIStatusError as e:
            raise AnalysisError(f"LLM 요청 실패 ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AnalysisError("LLM 서버에 연결하지 못했습니다.") from e

        if response.stop_reason == "refusal":
            raise AnalysisError("LLM이 이 내용의 분석을 거절했습니다.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise AnalysisError("LLM 응답이 완성되지 않았습니다.")
        return response.parsed_output
