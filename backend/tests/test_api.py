import logging

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_engine, get_repository
from app.db.repository import InMemoryRepository
from app.errors import AnalysisError
from app.main import app
from app.rag.engine import AnalysisEngine
from app.schemas.llm import LLMAnalysis
from tests.conftest import FakeAnalyzer, llm_finding

TEXT = "예수님이 약속하신 보혜사는 오늘날 이 땅에 육체로 오신 약속의 목자입니다."


@pytest.fixture
def make_client(embedder, store):
    def _make(output):
        app.dependency_overrides[get_engine] = lambda: AnalysisEngine(embedder, store, FakeAnalyzer(output))
        repository = InMemoryRepository()
        app.dependency_overrides[get_repository] = lambda: repository
        client = TestClient(app)  # with 없이 써서 lifespan(DB 초기화)을 건너뛴다
        client.repository = repository
        return client

    yield _make
    app.dependency_overrides.clear()


def test_create_then_get_analysis(make_client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.api.analyses")
    finding = llm_finding(quote="약속의 목자", reference_ids=["scj-promised-pastor"])
    client = make_client(LLMAnalysis(summary="요약", findings=[finding]))

    created = client.post("/analyses", json={"segments": [{"time": "02:15", "text": TEXT, "source": "stt"}]})
    assert created.status_code == 202
    assert created.json()["status"] == "pending"

    # TestClient 는 응답을 돌려주기 전에 백그라운드 작업을 끝낸다.
    fetched = client.get(f"/analyses/{created.json()['id']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "done"
    assert body["result"]["verdict"] == "danger"
    assert body["result"]["findings"][0] | {"references": None} == {
        "time": "02:15",
        "source": "stt",
        "quote": "약속의 목자",
        "score": 80,
        "group": "신천지",
        "topic": "christology",
        "reason": "이유",
        "orthodox_refutation": "반증",
        "heresy_intent": "의도",
        "scripture": ["요 14:26"],
        "references": None,
    }
    assert body["result"]["findings"][0]["references"][0]["id"] == "scj-promised-pastor"
    assert body["log"][-1] == "판별을 마쳤습니다. 의심 발언 1건, 종합 의심 지수 80점(위험)."
    assert f"text_analysis.result_saved analysis_id={body['id']} verdict=danger score=80 findings=1" in caplog.text
    assert TEXT not in caplog.text


def test_text_is_saved_as_transcript_without_video(make_client):
    client = make_client(LLMAnalysis(summary="요약", findings=[]))
    segments = [{"text": TEXT}, {"time": "00:05", "text": "둘째 줄", "source": "stt"}]

    created = client.post("/analyses", json={"segments": segments}).json()

    analysis = client.repository.analyses[created["id"]]
    assert analysis.video_id is None
    assert analysis.sources == ["stt", "user"]
    transcript = client.repository.transcripts[analysis.transcript_id]
    assert [(s.time, s.source) for s in transcript.stored.result.segments] == [(None, "user"), ("00:05", "stt")]
    # 영상 분석 API 로는 찾지 않는다.
    assert client.get(f"/videos/{created['id']}").status_code == 404


def test_engine_failure_is_reported_as_failed_job(make_client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.app.timing")
    client = make_client(AnalysisError("LLM 서버에 연결하지 못했습니다."))
    created = client.post("/analyses", json={"segments": [{"text": TEXT}]}).json()
    body = client.get(f"/analyses/{created['id']}").json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] == "LLM 서버에 연결하지 못했습니다."
    assert f"text_analysis.failed analysis_id={created['id']} stage=analyze error=AnalysisError" in caplog.text
    assert "text_analysis.result_saved" not in caplog.text
    assert f"analysis.timing_summary analysis_id={created['id']} kind=text status=failed" in caplog.text


def test_unexpected_error_does_not_leave_job_running(make_client):
    client = make_client(RuntimeError("예상 못 한 오류"))
    created = client.post("/analyses", json={"segments": [{"text": TEXT}]}).json()
    body = client.get(f"/analyses/{created['id']}").json()
    assert body["status"] == "failed"
    assert "예상 못 한 오류" in body["error"]


def test_unknown_analysis_is_404(make_client):
    client = make_client(LLMAnalysis(summary="요약", findings=[]))
    assert client.get("/analyses/없는-id").status_code == 404


@pytest.mark.parametrize("payload", [{"segments": []}, {"segments": [{"text": TEXT, "source": "video"}]}, {}])
def test_invalid_request_is_422(make_client, payload):
    client = make_client(LLMAnalysis(summary="요약", findings=[]))
    assert client.post("/analyses", json=payload).status_code == 422
