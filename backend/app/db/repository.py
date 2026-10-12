from typing import Protocol

import psycopg

from app.schemas.analysis import AnalysisRequest, AnalysisResponse


class AnalysisRepository(Protocol):
    def save(self, request: AnalysisRequest, response: AnalysisResponse) -> None: ...

    def get(self, analysis_id: str) -> AnalysisResponse | None: ...


class PgAnalysisRepository:
    def __init__(self, database_url: str):
        self._url = database_url

    def save(self, request: AnalysisRequest, response: AnalysisResponse) -> None:
        result = response.result.model_dump_json() if response.result else None
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "INSERT INTO analyses (id, status, request, result, error)"
                " VALUES (%s, %s, %s::jsonb, %s::jsonb, %s)",
                (response.id, response.status.value, request.model_dump_json(), result, response.error),
            )

    def get(self, analysis_id: str) -> AnalysisResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT id::text, status, result, error FROM analyses WHERE id::text = %s", (analysis_id,)
            ).fetchone()
        if row is None:
            return None
        return AnalysisResponse(id=row[0], status=row[1], result=row[2], error=row[3])


class InMemoryAnalysisRepository:
    def __init__(self):
        self._items: dict[str, AnalysisResponse] = {}

    def save(self, request: AnalysisRequest, response: AnalysisResponse) -> None:
        self._items[response.id] = response

    def get(self, analysis_id: str) -> AnalysisResponse | None:
        return self._items.get(analysis_id)
