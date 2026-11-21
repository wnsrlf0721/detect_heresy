"""분석 저장소. 영상 분석과 텍스트 판별이 같은 테이블을 쓴다. 테이블은 schema.sql, 설명은 docs/DATABASE.md 에 있다.

videos ─ transcripts ─ segments
              └─ analyses ─ findings ─ finding_refs ─ chunks
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from typing import Protocol
from uuid import uuid4

import psycopg

from app.rag.engine import reference_for
from app.rag.store import cosine_distance, vector_literal
from app.schemas.analysis import AnalysisResponse, AnalysisResult, Finding, JobStatus, Reference, Segment
from app.schemas.reference import Chunk
from app.schemas.transcript import TranscriptResult
from app.schemas.video import RelatedVideo, VideoResponse, VideoTopic


@dataclass
class StoredTranscript:
    """저장된 추출 결과. segment_ids 는 result.segments 와 같은 순서다."""

    id: str
    result: TranscriptResult
    segment_ids: list[int]
    topic: VideoTopic | None = None


class Repository(Protocol):
    def create_text_analysis(self, analysis_id: str, segments: list[Segment], version: str) -> list[int]:
        """직접 입력한 텍스트를 추출 결과(영상 없음)로 저장하고 판별 작업을 만든다. 구간 id 를 입력 순서대로 돌려준다."""

    def create_video_analysis(self, job: VideoResponse, video_id: str, version: str) -> None:
        """영상(처음 보면)과 판별 작업을 만든다. 추출 결과는 save_transcript / use_transcript 로 잇는다."""

    def set_status(
        self, analysis_id: str, status: JobStatus, progress: str | None = None, error: str | None = None
    ) -> None: ...

    def add_log(self, analysis_id: str, text: str) -> None:
        """진행 과정에 한 줄을 더하고, 진행 중인 단계(progress)도 그 줄로 바꾼다. 여러 스레드에서 불러도 된다."""

    def save_transcript(
        self, analysis_id: str, video_id: str, transcript: TranscriptResult, *, automatic_speech: bool = False
    ) -> StoredTranscript:
        """새로 추출한 결과를 저장하고 작업에 잇는다. 영상 제목과 길이도 채운다."""

    def use_transcript(self, analysis_id: str, transcript_id: str) -> None:
        """이미 저장된 추출 결과를 작업에 잇는다."""

    def save_result(self, analysis_id: str, result: AnalysisResult, segment_ids: list[int]) -> None:
        """판별 결과와 적발을 저장한다. segment_ids 는 판별에 넘긴 구간 순서이고, 적발의 segment_index 가 가리킨다."""

    def save_topic(self, transcript_id: str, topic: VideoTopic, embedding: list[float]) -> None: ...

    def get_text_analysis(self, analysis_id: str) -> AnalysisResponse | None: ...

    def get_video_analysis(self, analysis_id: str) -> VideoResponse | None: ...

    def find_video_analysis(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        """같은 영상·출처·버전의 가장 최근 작업. 끝났거나 아직 진행 중인 것만 찾는다.
        서버 재시작으로 끊긴 작업은 시작할 때 실패로 바뀌므로(app.db.fail_interrupted_jobs) 찾지 않는다."""

    def find_transcript(self, video_id: str, *, automatic_speech: bool = False) -> StoredTranscript | None:
        """이 영상에서 같은 추출 방식으로 저장한 가장 최근의 결과."""

    def related(self, analysis_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        """대주제가 비슷한 다른 영상의 최근 분석. 유사도가 높은 순서다."""


def _segment_id(finding: Finding, segment_ids: list[int]) -> int:
    if finding.segment_index is None or not 0 <= finding.segment_index < len(segment_ids):
        raise ValueError(f"적발이 판별한 구간을 가리키지 않습니다: {finding.quote}")
    return segment_ids[finding.segment_index]


def _response_sources(requested: list[str], stored: StoredTranscript | None) -> list[str]:
    # 빈 배열은 자동 선택 요청의 캐시 키다. 응답에는 저장된 구간의 출처를 표시한다.
    if requested or stored is None:
        return requested
    return sorted({segment.source for segment in stored.result.segments})


class PgRepository:
    def __init__(self, database_url: str):
        self._url = database_url

    def create_text_analysis(self, analysis_id: str, segments: list[Segment], version: str) -> list[int]:
        transcript_id = str(uuid4())
        with psycopg.connect(self._url) as conn:
            conn.execute("INSERT INTO transcripts (id) VALUES (%s)", (transcript_id,))
            segment_ids = self._insert_segments(conn, transcript_id, segments)
            conn.execute(
                "INSERT INTO analyses (id, transcript_id, sources, version, status) VALUES (%s, %s, %s, %s, %s)",
                (analysis_id, transcript_id, sorted({s.source for s in segments}), version, JobStatus.PENDING.value),
            )
        return segment_ids

    def create_video_analysis(self, job: VideoResponse, video_id: str, version: str) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "INSERT INTO videos (video_id, url) VALUES (%s, %s) ON CONFLICT (video_id) DO NOTHING",
                (video_id, job.url),
            )
            conn.execute(
                "INSERT INTO analyses (id, video_id, sources, version, status, progress, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (job.id, video_id, job.sources, version, job.status.value, job.progress, job.created_at),
            )

    def set_status(
        self, analysis_id: str, status: JobStatus, progress: str | None = None, error: str | None = None
    ) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE analyses SET status = %s, progress = %s, error = %s WHERE id = %s",
                (status.value, progress, error, analysis_id),
            )

    def add_log(self, analysis_id: str, text: str) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE analyses SET progress = %s, log = array_append(log, %s) WHERE id = %s",
                (text, text, analysis_id),
            )

    def save_transcript(
        self, analysis_id: str, video_id: str, transcript: TranscriptResult, *, automatic_speech: bool = False
    ) -> StoredTranscript:
        transcript_id = str(uuid4())
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE videos SET title = %s, duration = %s WHERE video_id = %s",
                (transcript.title, transcript.duration, video_id),
            )
            conn.execute(
                "INSERT INTO transcripts (id, video_id, warnings, automatic_speech) VALUES (%s, %s, %s, %s)",
                (transcript_id, video_id, transcript.warnings, automatic_speech),
            )
            segment_ids = self._insert_segments(conn, transcript_id, transcript.segments)
            conn.execute("UPDATE analyses SET transcript_id = %s WHERE id = %s", (transcript_id, analysis_id))
        return StoredTranscript(transcript_id, transcript, segment_ids)

    def use_transcript(self, analysis_id: str, transcript_id: str) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute("UPDATE analyses SET transcript_id = %s WHERE id = %s", (transcript_id, analysis_id))

    def save_result(self, analysis_id: str, result: AnalysisResult, segment_ids: list[int]) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE analyses SET verdict = %s, score = %s, summary = %s WHERE id = %s",
                (result.verdict.value, result.score, result.summary, analysis_id),
            )
            for position, finding in enumerate(result.findings):
                finding_id = conn.execute(
                    "INSERT INTO findings (analysis_id, position, segment_id, quote, score, group_name, topic, reason,"
                    " orthodox_refutation, heresy_intent, scripture)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        analysis_id,
                        position,
                        _segment_id(finding, segment_ids),
                        finding.quote,
                        finding.score,
                        finding.group,
                        finding.topic.value if finding.topic else None,
                        finding.reason,
                        finding.orthodox_refutation,
                        finding.heresy_intent,
                        finding.scripture,
                    ),
                ).fetchone()[0]
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO finding_refs (finding_id, position, chunk_id) VALUES (%s, %s, %s)",
                        [(finding_id, i, ref.id) for i, ref in enumerate(finding.references)],
                    )

    def save_topic(self, transcript_id: str, topic: VideoTopic, embedding: list[float]) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute(
                "UPDATE transcripts SET topic_title = %s, topic_summary = %s, topic_keywords = %s,"
                " topic_embedding = %s::vector WHERE id = %s",
                (topic.title, topic.summary, topic.keywords, vector_literal(embedding), transcript_id),
            )

    def get_text_analysis(self, analysis_id: str) -> AnalysisResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT id::text, status, error, verdict, score, summary, log FROM analyses"
                " WHERE id::text = %s AND video_id IS NULL",
                (analysis_id,),
            ).fetchone()
            if row is None:
                return None
            return AnalysisResponse(
                id=row[0], status=row[1], error=row[2], log=row[6], result=self._load_result(conn, row[0], *row[3:6])
            )

    def get_video_analysis(self, analysis_id: str) -> VideoResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT a.id::text, a.status, v.url, a.sources, a.created_at, a.progress, a.error,"
                " a.transcript_id::text, a.verdict, a.score, a.summary, a.log"
                " FROM analyses a JOIN videos v ON v.video_id = a.video_id WHERE a.id::text = %s",
                (analysis_id,),
            ).fetchone()
            if row is None:
                return None
            stored = self._load_transcript(conn, row[7]) if row[7] else None
            return VideoResponse(
                id=row[0],
                status=row[1],
                url=row[2],
                sources=_response_sources(row[3], stored),
                created_at=row[4],
                progress=row[5],
                log=row[11],
                error=row[6],
                transcript=stored.result if stored else None,
                topic=stored.topic if stored else None,
                result=self._load_result(conn, row[0], *row[8:11]),
            )

    def find_video_analysis(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT id::text FROM analyses WHERE video_id = %s AND sources = %s AND version = %s"
                " AND status <> 'failed' ORDER BY created_at DESC LIMIT 1",
                (video_id, sources, version),
            ).fetchone()
        return self.get_video_analysis(row[0]) if row else None

    def find_transcript(self, video_id: str, *, automatic_speech: bool = False) -> StoredTranscript | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute(
                "SELECT id::text FROM transcripts WHERE video_id = %s AND automatic_speech = %s"
                " ORDER BY created_at DESC LIMIT 1",
                (video_id, automatic_speech),
            ).fetchone()
            return self._load_transcript(conn, row[0]) if row else None

    def related(self, analysis_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        # 영상마다 대주제가 있는 가장 최근 분석 하나만 후보로 두고, 그중 유사도가 높은 것을 고른다.
        with psycopg.connect(self._url) as conn:
            rows = conn.execute(
                "WITH me AS (SELECT a.video_id, t.topic_embedding FROM analyses a"
                " JOIN transcripts t ON t.id = a.transcript_id"
                " WHERE a.id::text = %s AND t.topic_embedding IS NOT NULL)"
                " SELECT id, url, title, topic, verdict, score, similarity, created_at FROM ("
                " SELECT DISTINCT ON (a.video_id) a.id::text AS id, v.url, v.title, t.topic_title AS topic,"
                " a.verdict, a.score, 1 - (t.topic_embedding <=> me.topic_embedding) AS similarity, a.created_at"
                " FROM analyses a JOIN transcripts t ON t.id = a.transcript_id"
                " JOIN videos v ON v.video_id = a.video_id, me"
                " WHERE a.status = 'done' AND t.topic_embedding IS NOT NULL AND a.video_id <> me.video_id"
                " ORDER BY a.video_id, a.created_at DESC"
                ") latest WHERE similarity >= %s ORDER BY similarity DESC LIMIT %s",
                (analysis_id, min_similarity, limit),
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

    @staticmethod
    def _insert_segments(conn, transcript_id: str, segments: list[Segment]) -> list[int]:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO segments (transcript_id, position, source, time, text) VALUES (%s, %s, %s, %s, %s)",
                [(transcript_id, i, s.source, s.time, s.text) for i, s in enumerate(segments)],
            )
        rows = conn.execute(
            "SELECT id FROM segments WHERE transcript_id = %s ORDER BY position", (transcript_id,)
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _load_transcript(conn, transcript_id: str) -> StoredTranscript:
        row = conn.execute(
            "SELECT v.title, v.duration, t.warnings, t.topic_title, t.topic_summary, t.topic_keywords"
            " FROM transcripts t LEFT JOIN videos v ON v.video_id = t.video_id WHERE t.id = %s",
            (transcript_id,),
        ).fetchone()
        segments = conn.execute(
            "SELECT id, time, text, source FROM segments WHERE transcript_id = %s ORDER BY position",
            (transcript_id,),
        ).fetchall()
        result = TranscriptResult(
            title=row[0] or "",
            duration=row[1] or 0,
            segments=[Segment(time=s[1], text=s[2], source=s[3]) for s in segments],
            warnings=row[2],
        )
        topic = VideoTopic(title=row[3], summary=row[4], keywords=row[5]) if row[3] else None
        return StoredTranscript(transcript_id, result, [s[0] for s in segments], topic)

    @staticmethod
    def _load_result(conn, analysis_id: str, verdict, score, summary) -> AnalysisResult | None:
        if verdict is None:
            return None
        refs: dict[int, list[Reference]] = {}
        for finding_id, chunk_id, kind, text, metadata in conn.execute(
            "SELECT r.finding_id, c.id, c.kind, c.text, c.metadata FROM finding_refs r"
            " JOIN findings f ON f.id = r.finding_id JOIN chunks c ON c.id = r.chunk_id"
            " WHERE f.analysis_id = %s ORDER BY r.finding_id, r.position",
            (analysis_id,),
        ):
            refs.setdefault(finding_id, []).append(
                reference_for(Chunk(id=chunk_id, kind=kind, text=text, metadata=metadata))
            )
        findings = [
            Finding(
                time=r[1],
                source=r[2],
                quote=r[3],
                score=r[4],
                group=r[5],
                topic=r[6],
                reason=r[7],
                orthodox_refutation=r[8],
                heresy_intent=r[9],
                scripture=r[10],
                references=refs.get(r[0], []),
            )
            for r in conn.execute(
                "SELECT f.id, s.time, s.source, f.quote, f.score, f.group_name, f.topic, f.reason,"
                " f.orthodox_refutation, f.heresy_intent, f.scripture"
                " FROM findings f JOIN segments s ON s.id = f.segment_id"
                " WHERE f.analysis_id = %s ORDER BY f.position",
                (analysis_id,),
            )
        ]
        return AnalysisResult(verdict=verdict, score=score, summary=summary, findings=findings)


@dataclass
class _Analysis:
    id: str
    video_id: str | None
    sources: list[str]
    version: str
    status: JobStatus
    created_at: datetime
    seq: int  # 만든 시각이 같을 때 순서
    transcript_id: str | None = None
    progress: str | None = None
    log: list[str] = field(default_factory=list)
    error: str | None = None
    result: AnalysisResult | None = None


@dataclass
class _Video:
    url: str
    title: str | None = None
    duration: int | None = None


@dataclass
class _Transcript:
    stored: StoredTranscript
    video_id: str | None
    seq: int
    embedding: list[float] | None = None
    automatic_speech: bool = False


@dataclass
class InMemoryRepository:
    """테스트용. PgRepository 와 같은 규칙(적발은 판별한 구간을 가리켜야 함 등)을 따른다."""

    videos: dict[str, _Video] = field(default_factory=dict)
    transcripts: dict[str, _Transcript] = field(default_factory=dict)
    analyses: dict[str, _Analysis] = field(default_factory=dict)

    def __post_init__(self):
        self._ids = count(1)

    def create_text_analysis(self, analysis_id: str, segments: list[Segment], version: str) -> list[int]:
        stored = self._new_transcript(None, TranscriptResult(title="", duration=0, segments=segments))
        self._new_analysis(analysis_id, None, sorted({s.source for s in segments}), version, JobStatus.PENDING)
        self.analyses[analysis_id].transcript_id = stored.id
        return stored.segment_ids

    def create_video_analysis(self, job: VideoResponse, video_id: str, version: str) -> None:
        self.videos.setdefault(video_id, _Video(job.url))
        self._new_analysis(job.id, video_id, list(job.sources), version, job.status, job.created_at)

    def set_status(
        self, analysis_id: str, status: JobStatus, progress: str | None = None, error: str | None = None
    ) -> None:
        analysis = self.analyses[analysis_id]
        analysis.status, analysis.progress, analysis.error = status, progress, error

    def add_log(self, analysis_id: str, text: str) -> None:
        analysis = self.analyses[analysis_id]
        analysis.progress = text
        analysis.log.append(text)

    def save_transcript(
        self, analysis_id: str, video_id: str, transcript: TranscriptResult, *, automatic_speech: bool = False
    ) -> StoredTranscript:
        video = self.videos[video_id]
        video.title, video.duration = transcript.title, transcript.duration
        stored = self._new_transcript(video_id, transcript)
        self.transcripts[stored.id].automatic_speech = automatic_speech
        self.analyses[analysis_id].transcript_id = stored.id
        return stored

    def use_transcript(self, analysis_id: str, transcript_id: str) -> None:
        self.analyses[analysis_id].transcript_id = transcript_id

    def save_result(self, analysis_id: str, result: AnalysisResult, segment_ids: list[int]) -> None:
        for finding in result.findings:
            _segment_id(finding, segment_ids)
        # DB 에서 다시 읽은 것처럼 구간 번호는 남기지 않는다.
        findings = [f.model_copy(update={"segment_index": None}) for f in result.findings]
        self.analyses[analysis_id].result = result.model_copy(update={"findings": findings})

    def save_topic(self, transcript_id: str, topic: VideoTopic, embedding: list[float]) -> None:
        transcript = self.transcripts[transcript_id]
        transcript.stored.topic, transcript.embedding = topic, embedding

    def get_text_analysis(self, analysis_id: str) -> AnalysisResponse | None:
        a = self.analyses.get(analysis_id)
        if a is None or a.video_id is not None:
            return None
        return AnalysisResponse(id=a.id, status=a.status, result=a.result, error=a.error, log=list(a.log))

    def get_video_analysis(self, analysis_id: str) -> VideoResponse | None:
        a = self.analyses.get(analysis_id)
        if a is None or a.video_id is None:
            return None
        stored = self._stored(a)
        return VideoResponse(
            id=a.id,
            status=a.status,
            url=self.videos[a.video_id].url,
            sources=_response_sources(a.sources, stored),
            created_at=a.created_at,
            progress=a.progress,
            log=list(a.log),
            error=a.error,
            transcript=stored.result if stored else None,
            topic=stored.topic if stored else None,
            result=a.result,
        )

    def find_video_analysis(self, video_id: str, sources: list[str], version: str) -> VideoResponse | None:
        for a in self._latest_first():
            if (a.video_id, a.sources, a.version) == (video_id, sources, version) and a.status != JobStatus.FAILED:
                return self.get_video_analysis(a.id)
        return None

    def find_transcript(self, video_id: str, *, automatic_speech: bool = False) -> StoredTranscript | None:
        found = [
            t for t in self.transcripts.values()
            if t.video_id == video_id and t.automatic_speech == automatic_speech
        ]
        return max(found, key=lambda t: t.seq).stored if found else None

    def related(self, analysis_id: str, min_similarity: float, limit: int) -> list[RelatedVideo]:
        me = self.analyses.get(analysis_id)
        mine = self.transcripts.get(me.transcript_id) if me and me.transcript_id else None
        if mine is None or mine.embedding is None:
            return []
        latest: dict[str, tuple[_Analysis, _Transcript]] = {}
        for a in self._latest_first():
            t = self.transcripts.get(a.transcript_id) if a.transcript_id else None
            if a.status == JobStatus.DONE and t and t.embedding is not None and a.video_id not in (None, me.video_id):
                latest.setdefault(a.video_id, (a, t))
        found = []
        for a, t in latest.values():
            similarity = 1 - cosine_distance(mine.embedding, t.embedding)
            if similarity >= min_similarity:
                found.append(
                    RelatedVideo(
                        id=a.id,
                        url=self.videos[a.video_id].url,
                        title=self.videos[a.video_id].title or "",
                        topic=t.stored.topic.title,
                        verdict=a.result.verdict,
                        score=a.result.score,
                        similarity=round(similarity, 3),
                        created_at=a.created_at,
                    )
                )
        return sorted(found, key=lambda video: video.similarity, reverse=True)[:limit]

    def _new_analysis(self, analysis_id, video_id, sources, version, status, created_at=None) -> None:
        self.analyses[analysis_id] = _Analysis(
            analysis_id, video_id, sources, version, status, created_at or datetime.now(UTC), next(self._ids)
        )

    def _new_transcript(self, video_id: str | None, transcript: TranscriptResult) -> StoredTranscript:
        stored = StoredTranscript(str(uuid4()), transcript, [next(self._ids) for _ in transcript.segments])
        self.transcripts[stored.id] = _Transcript(stored, video_id, next(self._ids))
        return stored

    def _stored(self, analysis: _Analysis) -> StoredTranscript | None:
        return self.transcripts[analysis.transcript_id].stored if analysis.transcript_id else None

    def _latest_first(self) -> list[_Analysis]:
        return sorted(self.analyses.values(), key=lambda a: (a.created_at, a.seq), reverse=True)
