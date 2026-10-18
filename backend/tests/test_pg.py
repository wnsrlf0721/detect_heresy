"""실제 Postgres(pgvector)가 떠 있을 때만 도는 통합 테스트. `docker compose up -d db` 후 실행한다.

개발 DB를 건드리지 않도록 임시 스키마 안에서만 동작한다.
"""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.config import get_settings
from app.db import INTERRUPTED, fail_interrupted_jobs, init_db
from app.db.repository import PgAnalysisRepository, PgVideoRepository
from app.rag.store import PgVectorStore
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, AnalysisResult, JobStatus, Segment
from app.schemas.reference import Chunk
from app.schemas.transcript import TranscriptResult
from app.schemas.video import VideoResponse, VideoTopic

SCHEMA = "pytest_tmp"


@pytest.fixture
def database_url():
    base = get_settings().database_url
    try:
        with psycopg.connect(base, connect_timeout=2) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
            conn.execute(f"CREATE SCHEMA {SCHEMA}")
    except psycopg.OperationalError:
        pytest.skip("Postgres 에 연결할 수 없음")
    url = f"{base}?options=-csearch_path%3D{SCHEMA},public"
    init_db(url)
    yield url
    with psycopg.connect(base) as conn:
        conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")


def _vector(*hot: int) -> list[float]:
    return [1.0 if i in hot else 0.0 for i in range(1024)]


def test_vector_store_roundtrip(database_url):
    store = PgVectorStore(database_url)
    chunks = [
        Chunk(id="h1", kind="heresy", text="이단 사례 1", metadata={"group": "단체", "orthodox_refs": ["o1"]}),
        Chunk(id="h2", kind="heresy", text="이단 사례 2", metadata={"group": "단체"}),
        Chunk(id="o1", kind="orthodox", text="정통 조항", metadata={"source": "문서"}),
    ]
    store.replace_all(chunks, [_vector(0), _vector(1), _vector(0)])

    assert [c.id for c in store.search(_vector(0, 2), "heresy", 2)] == ["h1", "h2"]
    assert [c.id for c in store.search(_vector(0), "orthodox", 5)] == ["o1"]
    assert store.get(["o1", "없는-id"])[0].metadata == {"source": "문서"}
    assert store.get([]) == []

    store.replace_all(chunks[:1], [_vector(0)])
    assert store.get(["h2", "o1"]) == []


def test_analysis_repository_roundtrip(database_url):
    repository = PgAnalysisRepository(database_url)
    request = AnalysisRequest.model_validate({"segments": [{"text": "발언"}]})
    result = AnalysisResult(verdict="safe", score=0, summary="요약", findings=[])
    done = AnalysisResponse(id="3f0c2a52-6a52-4c0e-9d5e-0d7b3b8f4a11", status="done", result=result)
    failed = AnalysisResponse(id="8a1b7c1e-2f43-4a6b-b0de-51c9f0a2d7c3", status="failed", error="오류")

    repository.create(request, AnalysisResponse(id=done.id, status="pending"))
    assert repository.get(done.id).status == "pending"
    repository.update(done)
    repository.create(request, AnalysisResponse(id=failed.id, status="pending"))
    repository.update(failed)

    assert repository.get(done.id) == done
    assert repository.get(failed.id) == failed
    assert repository.get("없는-id") is None


def _video(job_id, url, minutes_ago, status="done", sources=("caption", "ocr", "stt")):
    return VideoResponse(
        id=job_id,
        status=status,
        url=url,
        sources=list(sources),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def test_video_repository_roundtrip(database_url):
    repository = PgVideoRepository(database_url)
    transcript = TranscriptResult(title="제목", duration=60, segments=[Segment(time="00:01", text="발언", source="stt")])
    result = AnalysisResult(verdict="caution", score=40, summary="요약", findings=[])
    topic = VideoTopic(title="보혜사 강의", summary="요약", keywords=["보혜사"])

    a = _video("00000000-0000-0000-0000-00000000000a", "https://youtu.be/AAAAAAAAAAA", 30)
    repository.create(a, "AAAAAAAAAAA", "v1")
    assert repository.get(a.id) == a
    assert repository.find_transcript("AAAAAAAAAAA") is None

    a = a.model_copy(update={"status": JobStatus.RUNNING, "progress": "내려받는 중", "transcript": transcript})
    repository.update(a)
    assert repository.find("AAAAAAAAAAA", a.sources, "v1") == a  # 진행 중인 작업도 찾는다
    assert repository.find_transcript("AAAAAAAAAAA") == transcript

    a = a.model_copy(update={"status": JobStatus.DONE, "progress": None, "result": result, "topic": topic})
    repository.update(a, _vector(0))
    repository.update(a)  # 임베딩을 넘기지 않으면 그대로 둔다
    assert repository.get(a.id) == a
    assert repository.find("AAAAAAAAAAA", a.sources, "v1") == a
    assert repository.find("AAAAAAAAAAA", a.sources, "v2") is None
    assert repository.find("AAAAAAAAAAA", ["stt"], "v1") is None

    # 서버가 다시 뜨면 진행 중이던 작업은 실패로 바뀌고, 더는 찾지 않는다.
    stuck = _video("00000000-0000-0000-0000-00000000000f", "https://youtu.be/FFFFFFFFFFF", 1, status="running")
    repository.create(stuck, "FFFFFFFFFFF", "v1")
    assert repository.find("FFFFFFFFFFF", stuck.sources, "v1") is not None
    fail_interrupted_jobs(database_url)
    assert repository.find("FFFFFFFFFFF", stuck.sources, "v1") is None
    assert (repository.get(stuck.id).status, repository.get(stuck.id).error) == ("failed", INTERRUPTED)
    assert repository.get(a.id).status == "done"

    # 비슷한 주제: B(같은 방향), C(직교). B 는 두 번 분석했고 최근 것만 나온다.
    b_old = _video("00000000-0000-0000-0000-0000000000b1", "https://youtu.be/BBBBBBBBBBB", 20)
    b_new = _video("00000000-0000-0000-0000-0000000000b2", "https://youtu.be/BBBBBBBBBBB", 10)
    c = _video("00000000-0000-0000-0000-00000000000c", "https://youtu.be/CCCCCCCCCCC", 5)
    for job, video_id, embedding in ((b_old, "BBBBBBBBBBB", _vector(0)), (b_new, "BBBBBBBBBBB", _vector(0, 1)), (c, "CCCCCCCCCCC", _vector(2))):
        repository.create(job, video_id, "v1")
        repository.update(job.model_copy(update={"transcript": transcript, "result": result, "topic": topic}), embedding)

    related = repository.related(a.id, 0.5, 5)
    assert [r.id for r in related] == [b_new.id]
    assert (related[0].title, related[0].topic, related[0].verdict, related[0].score) == ("제목", "보혜사 강의", "caution", 40)
    assert related[0].similarity == pytest.approx(0.707, abs=0.001)
    assert repository.related(a.id, 0.9, 5) == []
    assert repository.related(stuck.id, 0.0, 5) == []  # 주제 임베딩이 없으면 찾지 않는다
