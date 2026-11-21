"""실제 Postgres(pgvector)가 떠 있을 때만 도는 통합 테스트. `docker compose up -d db` 후 실행한다.

개발 DB를 건드리지 않도록 임시 스키마 안에서만 동작한다.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.config import get_settings
from app.db import INTERRUPTED, fail_interrupted_jobs, init_db
from app.db.repository import PgRepository
from app.rag.store import PgVectorStore
from app.schemas.analysis import AnalysisResult, Finding, JobStatus, Reference, Segment
from app.schemas.reference import Chunk
from app.schemas.transcript import TranscriptResult
from app.schemas.video import VideoResponse, VideoTopic

@pytest.fixture
def database_url():
    base = get_settings().database_url
    # 동시에 도는 테스트가 서로의 스키마를 지우면 public 테이블을 쓸 수 있다.
    schema = f"pytest_{uuid4().hex}"
    try:
        with psycopg.connect(base, connect_timeout=2) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.OperationalError:
        pytest.skip("Postgres 에 연결할 수 없음")
    url = make_conninfo(base, options=f"-c search_path={schema},public")
    try:
        with psycopg.connect(url) as conn:
            assert conn.execute("SELECT current_schema()").fetchone() == (schema,)
        init_db(url)
        yield url
    finally:
        with psycopg.connect(base) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _vector(*hot: int) -> list[float]:
    return [1.0 if i in hot else 0.0 for i in range(1024)]


CHUNKS = [
    Chunk(id="h1", kind="heresy", text="이단 사례 1", metadata={"group": "단체", "claim": "주장 1", "orthodox_refs": ["o1"]}),
    Chunk(id="h2", kind="heresy", text="이단 사례 2", metadata={"group": "단체", "claim": "주장 2"}),
    Chunk(id="o1", kind="orthodox", text="정통 조항", metadata={"source": "문서", "section": "1조", "text": "조항 원문"}),
]


def test_vector_store_roundtrip(database_url):
    store = PgVectorStore(database_url)
    store.replace_all(CHUNKS, [_vector(0), _vector(1), _vector(0)])

    assert [c.id for c in store.search(_vector(0, 2), "heresy", 2)] == ["h1", "h2"]
    assert [c.id for c in store.search(_vector(0), "orthodox", 5)] == ["o1"]
    assert store.get(["o1", "없는-id"])[0].metadata["source"] == "문서"
    assert store.get([]) == []

    # 빠진 레코드는 지우지 않고 검색에서만 뺀다(지난 적발의 근거로 남아 있어야 한다).
    store.replace_all(CHUNKS[:1], [_vector(0)])
    assert store.get(["h2", "o1"]) == []
    assert [c.id for c in store.search(_vector(1), "heresy", 5)] == ["h1"]
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 3


def _finding(segment_index: int, quote: str, references: list[Reference]) -> Finding:
    return Finding(
        segment_index=segment_index,
        source="stt",
        quote=quote,
        score=80,
        group="신천지",
        topic="christology",
        reason="이유",
        orthodox_refutation="반증",
        heresy_intent="의도",
        scripture=["요 14:26"],
        references=references,
    )


def test_text_analysis_roundtrip(database_url):
    PgVectorStore(database_url).replace_all(CHUNKS, [_vector(0), _vector(1), _vector(0)])
    repository = PgRepository(database_url)
    segments = [Segment(text="첫 줄"), Segment(time="00:05", text="약속의 목자를 만나야 합니다", source="stt")]
    refs = [
        Reference(id="h1", kind="heresy", label="단체 교리 사례", excerpt="주장 1"),
        Reference(id="o1", kind="orthodox", label="문서 1조", excerpt="조항 원문"),
    ]
    result = AnalysisResult(verdict="danger", score=80, summary="요약", findings=[_finding(1, "약속의 목자", refs)])

    done_id = "3f0c2a52-6a52-4c0e-9d5e-0d7b3b8f4a11"
    segment_ids = repository.create_text_analysis(done_id, segments, "v1")
    assert len(segment_ids) == 2
    assert repository.get_text_analysis(done_id).status == "pending"
    repository.save_result(done_id, result, segment_ids)
    repository.set_status(done_id, JobStatus.DONE)

    done = repository.get_text_analysis(done_id)
    assert done.status == "done"
    finding = done.result.findings[0]
    # 시각과 출처는 가리키는 구간에서, 근거는 기준 데이터에서 다시 만든다.
    assert (finding.time, finding.source, finding.quote) == ("00:05", "stt", "약속의 목자")
    assert finding.references == refs
    expected = result.findings[0].model_copy(update={"time": "00:05", "segment_index": None})
    assert done.result == result.model_copy(update={"findings": [expected]})

    failed_id = "8a1b7c1e-2f43-4a6b-b0de-51c9f0a2d7c3"
    repository.create_text_analysis(failed_id, segments, "v1")
    repository.set_status(failed_id, JobStatus.FAILED, error="오류")
    failed = repository.get_text_analysis(failed_id)
    assert (failed.status, failed.result, failed.error) == ("failed", None, "오류")
    assert repository.get_text_analysis("없는-id") is None
    assert repository.get_video_analysis(done_id) is None  # 텍스트 판별은 영상 분석으로 찾지 않는다

    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT video_id, sources FROM analyses WHERE id = %s", (done_id,)).fetchone() == (
            None,
            ["stt", "user"],
        )
        assert conn.execute("SELECT count(*) FROM finding_refs").fetchone()[0] == 2

    with pytest.raises(ValueError):
        repository.save_result(failed_id, result.model_copy(update={"findings": [_finding(5, "x", [])]}), segment_ids)


def _job(job_id, url, minutes_ago, status=JobStatus.PENDING, sources=("caption", "ocr", "stt")):
    return VideoResponse(
        id=job_id,
        status=status,
        url=url,
        sources=list(sources),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def test_video_analysis_roundtrip(database_url):
    repository = PgRepository(database_url)
    transcript = TranscriptResult(
        title="제목",
        duration=60,
        segments=[Segment(time="00:01", text="자막", source="caption"), Segment(time="00:02", text="발언", source="stt")],
        warnings=["화면 글자 인식에 실패했습니다"],
    )
    result = AnalysisResult(verdict="caution", score=40, summary="요약", findings=[])
    topic = VideoTopic(title="보혜사 강의", summary="요약", keywords=["보혜사"])

    a = _job("00000000-0000-0000-0000-00000000000a", "https://youtu.be/AAAAAAAAAAA", 30)
    repository.create_video_analysis(a, "AAAAAAAAAAA", "v1")
    assert repository.get_video_analysis(a.id) == a
    assert repository.find_transcript("AAAAAAAAAAA") is None

    repository.set_status(a.id, JobStatus.RUNNING)
    repository.add_log(a.id, "영상을 내려받는 중입니다.")
    repository.add_log(a.id, "내려받는 중")
    stored = repository.save_transcript(a.id, "AAAAAAAAAAA", transcript)
    running = repository.find_video_analysis("AAAAAAAAAAA", a.sources, "v1")  # 진행 중인 작업도 찾는다
    assert (running.status, running.progress, running.transcript, running.result) == ("running", "내려받는 중", transcript, None)
    assert repository.get_video_status(a.id).model_dump() == {
        "id": a.id, "status": JobStatus.RUNNING, "progress": "내려받는 중",
    }
    assert repository.find_transcript("AAAAAAAAAAA", automatic_speech=True) is None
    assert running.log == ["영상을 내려받는 중입니다.", "내려받는 중"]
    assert len(running.log_times) == len(running.log)
    assert running.log_times[0] <= running.log_times[1]
    found = repository.find_transcript("AAAAAAAAAAA")
    assert (found.id, found.result, found.segment_ids, found.topic) == (stored.id, transcript, stored.segment_ids, None)

    repository.save_result(a.id, result, stored.segment_ids)
    repository.save_topic(stored.id, topic, _vector(0))
    repository.set_status(a.id, JobStatus.DONE)
    a = a.model_copy(
        update={
            "status": JobStatus.DONE, "transcript": transcript, "result": result, "topic": topic,
            "log": running.log, "log_times": running.log_times,
        }
    )
    assert repository.get_video_analysis(a.id) == a
    assert repository.find_video_analysis("AAAAAAAAAAA", a.sources, "v1") == a
    assert repository.find_video_analysis("AAAAAAAAAAA", a.sources, "v2") is None
    assert repository.find_video_analysis("AAAAAAAAAAA", ["stt"], "v1") is None

    # 같은 추출 결과를 다른 출처로 다시 판별한다. 영상과 추출 결과는 하나씩만 남는다.
    a2 = _job("00000000-0000-0000-0000-0000000000a2", "https://www.youtube.com/watch?v=AAAAAAAAAAA", 25, sources=["stt"])
    repository.create_video_analysis(a2, "AAAAAAAAAAA", "v1")
    repository.use_transcript(a2.id, stored.id)
    assert repository.get_video_analysis(a2.id).topic == topic
    assert repository.get_video_analysis(a2.id).url == "https://youtu.be/AAAAAAAAAAA"  # 처음 입력한 주소
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*), max(title) FROM videos").fetchone() == (1, "제목")
        assert conn.execute("SELECT count(*) FROM transcripts").fetchone()[0] == 1

    # 서버가 다시 뜨면 진행 중이던 작업은 실패로 바뀌고, 더는 찾지 않는다.
    stuck = _job("00000000-0000-0000-0000-00000000000f", "https://youtu.be/FFFFFFFFFFF", 1, status=JobStatus.RUNNING)
    repository.create_video_analysis(stuck, "FFFFFFFFFFF", "v1")
    assert repository.find_video_analysis("FFFFFFFFFFF", stuck.sources, "v1") is not None
    fail_interrupted_jobs(database_url)
    assert repository.find_video_analysis("FFFFFFFFFFF", stuck.sources, "v1") is None
    assert (repository.get_video_analysis(stuck.id).status, repository.get_video_analysis(stuck.id).error) == (
        "failed",
        INTERRUPTED,
    )
    assert repository.get_video_analysis(a.id).status == "done"

    # 비슷한 주제: B(같은 방향), C(직교). B 는 두 번 추출·분석했고 최근 것만 나온다.
    b_old = _job("00000000-0000-0000-0000-0000000000b1", "https://youtu.be/BBBBBBBBBBB", 20)
    b_new = _job("00000000-0000-0000-0000-0000000000b2", "https://youtu.be/BBBBBBBBBBB", 10)
    c = _job("00000000-0000-0000-0000-00000000000c", "https://youtu.be/CCCCCCCCCCC", 5)
    for job, video_id, embedding in (
        (b_old, "BBBBBBBBBBB", _vector(0)),
        (b_new, "BBBBBBBBBBB", _vector(0, 1)),
        (c, "CCCCCCCCCCC", _vector(2)),
    ):
        repository.create_video_analysis(job, video_id, "v1")
        saved = repository.save_transcript(job.id, video_id, transcript)
        repository.save_result(job.id, result, saved.segment_ids)
        repository.save_topic(saved.id, topic, embedding)
        repository.set_status(job.id, JobStatus.DONE)

    related = repository.related(a.id, 0.5, 5)
    assert [r.id for r in related] == [b_new.id]
    assert (related[0].title, related[0].topic, related[0].verdict, related[0].score) == ("제목", "보혜사 강의", "caution", 40)
    assert related[0].similarity == pytest.approx(0.707, abs=0.001)
    assert repository.related(a.id, 0.9, 5) == []
    assert repository.related(stuck.id, 0.0, 5) == []  # 주제 임베딩이 없으면 찾지 않는다
