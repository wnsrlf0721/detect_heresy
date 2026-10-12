"""실제 Postgres(pgvector)가 떠 있을 때만 도는 통합 테스트. `docker compose up -d db` 후 실행한다.

개발 DB를 건드리지 않도록 임시 스키마 안에서만 동작한다.
"""

import psycopg
import pytest

from app.config import get_settings
from app.db import init_db
from app.db.repository import PgAnalysisRepository
from app.rag.store import PgVectorStore
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, AnalysisResult
from app.schemas.reference import Chunk

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

    repository.save(request, done)
    repository.save(request, failed)

    assert repository.get(done.id) == done
    assert repository.get(failed.id) == failed
    assert repository.get("없는-id") is None
