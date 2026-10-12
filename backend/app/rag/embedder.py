from typing import Literal, Protocol

import httpx

from app.errors import AnalysisError

InputType = Literal["document", "query"]


class Embedder(Protocol):
    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


class VoyageEmbedder:
    URL = "https://api.voyageai.com/v1/embeddings"
    BATCH_SIZE = 100

    def __init__(self, api_key: str | None, model: str):
        if not api_key:
            raise AnalysisError("VOYAGE_API_KEY 가 설정되지 않았습니다.")
        self._model = model
        self._client = httpx.Client(headers={"Authorization": f"Bearer {api_key}"}, timeout=60)

    def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
            try:
                response = self._client.post(
                    self.URL, json={"input": batch, "model": self._model, "input_type": input_type}
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise AnalysisError(f"임베딩 요청 실패: {e}") from e
            data = sorted(response.json()["data"], key=lambda item: item["index"])
            embeddings.extend(item["embedding"] for item in data)
        return embeddings
