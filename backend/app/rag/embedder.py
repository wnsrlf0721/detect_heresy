import time
from typing import Literal, Protocol

import httpx

from app.errors import AnalysisError

InputType = Literal["document", "query"]


class Embedder(Protocol):
    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


class VoyageEmbedder:
    URL = "https://api.voyageai.com/v1/embeddings"
    BATCH_SIZE = 100
    # 결제 수단을 등록하지 않은 계정은 분당 1만 토큰까지라, 요청 하나가 이를 넘으면 기다려도 계속 429 가 난다.
    # 한국어는 글자당 0.6토큰쯤이라(실측) 12,000자면 7천 토큰 남짓이다.
    MAX_BATCH_CHARS = 12_000
    MAX_ATTEMPTS = 6

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise AnalysisError("VOYAGE_API_KEY 가 설정되지 않았습니다.")
        self._model = model
        self._client = httpx.Client(headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for batch in _batches(texts, self.BATCH_SIZE, self.MAX_BATCH_CHARS):
            response = self._post({"input": batch, "model": self._model, "input_type": input_type})
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            embeddings.extend(item["embedding"] for item in data)
        return embeddings

    def _post(self, payload: dict) -> httpx.Response:
        """요청 한도(429)에 걸리면 기다렸다가 다시 보낸다. 무료 등급은 분당 요청 수가 적다."""
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                response = self._client.post(self.URL, json=payload)
                if response.status_code == 429 and attempt < self.MAX_ATTEMPTS - 1:
                    time.sleep(_retry_delay(response, attempt))
                    continue
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise AnalysisError(f"임베딩 요청 실패: {e}") from e
            return response
        raise AssertionError("unreachable")


def _batches(texts: list[str], max_count: int, max_chars: int) -> list[list[str]]:
    """순서를 유지하며 개수와 글자 수 한도 안으로 나눈다. 한도보다 긴 텍스트 하나는 혼자 보낸다."""
    batches: list[list[str]] = []
    size = 0
    for text in texts:
        if not batches or len(batches[-1]) >= max_count or size + len(text) > max_chars:
            batches.append([])
            size = 0
        batches[-1].append(text)
        size += len(text)
    return batches


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        return min(float(response.headers["retry-after"]), 60.0)
    except (KeyError, ValueError):
        return min(5.0 * 2**attempt, 60.0)
