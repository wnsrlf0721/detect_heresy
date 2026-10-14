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
    MAX_ATTEMPTS = 6

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise AnalysisError("VOYAGE_API_KEY 가 설정되지 않았습니다.")
        self._model = model
        self._client = httpx.Client(headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
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


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        return min(float(response.headers["retry-after"]), 60.0)
    except (KeyError, ValueError):
        return min(5.0 * 2**attempt, 60.0)
