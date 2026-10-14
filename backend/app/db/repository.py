from typing import Protocol

import psycopg

from app.schemas.analysis import AnalysisRequest, AnalysisResponse
from app.schemas.transcript import TranscriptResponse


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


class TranscriptRepository(Protocol):
    def create(self, url: str, response: TranscriptResponse) -> None: ...

    def update(self, response: TranscriptResponse) -> None: ...

    def get(self, transcript_id: str) -> TranscriptResponse | None: ...


class PgTranscriptRepository:
    def __init__(self, database_url: str):
        self._url = database_url

    def create(self, url: str, response: TranscriptResponse) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "INSERT INTO transcripts (id, status, url) VALUES (%s, %s, %s)",
                (response.id, response.status.value, url),
            )

    def update(self, response: TranscriptResponse) -> None:
        result = response.result.model_dump_json() if response.result else None
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE transcripts SET status = %s, progress = %s, result = %s::jsonb, error = %s"
                " WHERE id = %s",
                (response.status.value, response.progress, result, response.error, response.id),
            )

    def get(self, transcript_id: str) -> TranscriptResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT id::text, status, progress, result, error FROM transcripts WHERE id::text = %s",
                (transcript_id,),
            ).fetchone()
        if row is None:
            return None
        return TranscriptResponse(id=row[0], status=row[1], progress=row[2], result=row[3], error=row[4])


class InMemoryTranscriptRepository:
    def __init__(self):
        self._items: dict[str, TranscriptResponse] = {}

    def create(self, url: str, response: TranscriptResponse) -> None:
        self._items[response.id] = response

    def update(self, response: TranscriptResponse) -> None:
        self._items[response.id] = response

    def get(self, transcript_id: str) -> TranscriptResponse | None:
        return self._items.get(transcript_id)
