from dataclasses import dataclass
from typing import Protocol

import psycopg

from app.rag.store import cosine_distance, vector_literal
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, JobStatus
from app.schemas.transcript import TranscriptResponse, TranscriptResult
from app.schemas.video import RelatedVideo, VideoResponse


class AnalysisRepository(Protocol):
    def create(self, request: AnalysisRequest, response: AnalysisResponse) -> None: ...

    def update(self, response: AnalysisResponse) -> None: ...

    def get(self, analysis_id: str) -> AnalysisResponse | None: ...


class PgAnalysisRepository:
    def __init__(self, database_url: str):
        self._url = database_url

    def create(self, request: AnalysisRequest, response: AnalysisResponse) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "INSERT INTO analyses (id, status, request) VALUES (%s, %s, %s::jsonb)",
                (response.id, response.status.value, request.model_dump_json()),
            )

    def update(self, response: AnalysisResponse) -> None:
        result = response.result.model_dump_json() if response.result else None
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE analyses SET status = %s, result = %s::jsonb, error = %s WHERE id = %s",
                (response.status.value, result, response.error, response.id),
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

    def create(self, request: AnalysisRequest, response: AnalysisResponse) -> None:
        self._items[response.id] = response

    def update(self, response: AnalysisResponse) -> None:
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


class VideoRepository(Protocol):
    def create(self, response: VideoResponse, video_id: str, version: str) -> None: ...

    def update(self, response: VideoResponse, topic_embedding: list[float] | None = None) -> None:
        """topic_embedding 을 넘기지 않으면 저장된 값을 그대로 둔다."""

    def get(self, job_id: str) -> VideoResponse | None: ...

    def find(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        """같은 영상·출처·버전의 가장 최근 작업. 끝났거나 아직 진행 중인 것만 찾는다.
        서버 재시작으로 끊긴 작업은 시작할 때 실패로 바뀌므로(app.db.fail_interrupted_jobs) 찾지 않는다."""

    def find_transcript(self, video_id: str) -> TranscriptResult | None:
        """출처나 버전과 상관없이, 이 영상에서 가장 최근에 추출한 텍스트."""

    def related(self, job_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        """대주제가 비슷한 다른 영상의 최근 분석. 유사도가 높은 순서다."""


_VIDEO_COLUMNS = "id::text, status, url, sources, created_at, progress, transcript, result, topic, error"


def _video_from_row(row) -> VideoResponse:
    return VideoResponse(
        id=row[0],
        status=row[1],
        url=row[2],
        sources=row[3].split(","),
        created_at=row[4],
        progress=row[5],
        transcript=row[6],
        result=row[7],
        topic=row[8],
        error=row[9],
    )


def _json(model) -> str | None:
    return model.model_dump_json() if model is not None else None


class PgVideoRepository:
    def __init__(self, database_url: str):
        self._url = database_url

    def create(self, response: VideoResponse, video_id: str, version: str) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "INSERT INTO video_analyses (id, video_id, url, sources, version, status, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    response.id,
                    video_id,
                    response.url,
                    ",".join(response.sources),
                    version,
                    response.status.value,
                    response.created_at,
                ),
            )

    def update(self, response: VideoResponse, topic_embedding: list[float] | None = None) -> None:
        embedding = vector_literal(topic_embedding) if topic_embedding is not None else None
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE video_analyses SET status = %s, progress = %s, transcript = %s::jsonb, result = %s::jsonb,"
                " topic = %s::jsonb, error = %s, topic_embedding = COALESCE(%s::vector, topic_embedding)"
                " WHERE id = %s",
                (
                    response.status.value,
                    response.progress,
                    _json(response.transcript),
                    _json(response.result),
                    _json(response.topic),
                    response.error,
                    embedding,
                    response.id,
                ),
            )

    def get(self, job_id: str) -> VideoResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(f"SELECT {_VIDEO_COLUMNS} FROM video_analyses WHERE id::text = %s", (job_id,)).fetchone()
        return _video_from_row(row) if row else None

    def find(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                f"SELECT {_VIDEO_COLUMNS} FROM video_analyses"
                " WHERE video_id = %s AND sources = %s AND version = %s AND status <> 'failed'"
                " ORDER BY created_at DESC LIMIT 1",
                (video_id, ",".join(sources), version),
            ).fetchone()
        return _video_from_row(row) if row else None

    def find_transcript(self, video_id: str) -> TranscriptResult | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT transcript FROM video_analyses WHERE video_id = %s AND transcript IS NOT NULL"
                " ORDER BY created_at DESC LIMIT 1",
                (video_id,),
            ).fetchone()
        return TranscriptResult.model_validate(row[0]) if row else None

    def related(self, job_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        # 영상마다 가장 최근 분석 하나만 후보로 두고, 그중 유사도가 높은 것을 고른다.
        with psycopg.connect(self._url) as conn:
            rows = conn.execute(
                "WITH me AS (SELECT video_id, topic_embedding FROM video_analyses"
                " WHERE id::text = %s AND topic_embedding IS NOT NULL)"
                " SELECT id, url, title, topic, verdict, score, similarity, created_at FROM ("
                " SELECT DISTINCT ON (v.video_id) v.id::text AS id, v.url, v.transcript->>'title' AS title,"
                " v.topic->>'title' AS topic, v.result->>'verdict' AS verdict, (v.result->>'score')::int AS score,"
                " 1 - (v.topic_embedding <=> me.topic_embedding) AS similarity, v.created_at"
                " FROM video_analyses v, me"
                " WHERE v.status = 'done' AND v.topic_embedding IS NOT NULL AND v.video_id <> me.video_id"
                " ORDER BY v.video_id, v.created_at DESC"
                ") latest WHERE similarity >= %s ORDER BY similarity DESC LIMIT %s",
                (job_id, min_similarity, limit),
            ).fetchall()
        return [
            RelatedVideo(
                id=r[0],
                url=r[1],
                title=r[2] or "",
                topic=r[3],
                verdict=r[4],
                score=r[5],
                similarity=round(r[6], 3),
                created_at=r[7],
            )
            for r in rows
        ]


@dataclass
class _VideoRow:
    response: VideoResponse
    video_id: str
    version: str
    embedding: list[float] | None = None


class InMemoryVideoRepository:
    def __init__(self):
        self._rows: dict[str, _VideoRow] = {}

    def create(self, response: VideoResponse, video_id: str, version: str) -> None:
        self._rows[response.id] = _VideoRow(response, video_id, version)

    def update(self, response: VideoResponse, topic_embedding: list[float] | None = None) -> None:
        row = self._rows[response.id]
        row.response = response
        if topic_embedding is not None:
            row.embedding = topic_embedding

    def get(self, job_id: str) -> VideoResponse | None:
        row = self._rows.get(job_id)
        return row.response if row else None

    def _latest_first(self) -> list[_VideoRow]:
        return sorted(self._rows.values(), key=lambda row: row.response.created_at, reverse=True)

    def find(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        for row in self._latest_first():
            r = row.response
            if (row.video_id, r.sources, row.version) == (video_id, sources, version) and r.status != JobStatus.FAILED:
                return r
        return None

    def find_transcript(self, video_id: str) -> TranscriptResult | None:
        for row in self._latest_first():
            if row.video_id == video_id and row.response.transcript is not None:
                return row.response.transcript
        return None

    def related(self, job_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        me = self._rows.get(job_id)
        if me is None or me.embedding is None:
            return []
        latest: dict[str, _VideoRow] = {}
        for row in self._latest_first():
            if row.response.status == JobStatus.DONE and row.embedding is not None and row.video_id != me.video_id:
                latest.setdefault(row.video_id, row)
        found = []
        for row in latest.values():
            similarity = 1 - cosine_distance(me.embedding, row.embedding)
            if similarity < min_similarity:
                continue
            r = row.response
            found.append(
                RelatedVideo(
                    id=r.id,
                    url=r.url,
                    title=r.transcript.title if r.transcript else "",
                    topic=r.topic.title if r.topic else "",
                    verdict=r.result.verdict,
                    score=r.result.score,
                    similarity=round(similarity, 3),
                    created_at=r.created_at,
                )
            )
        return sorted(found, key=lambda video: video.similarity, reverse=True)[:limit]
