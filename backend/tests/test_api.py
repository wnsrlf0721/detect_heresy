import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_engine, get_repository
from app.db.repository import InMemoryAnalysisRepository
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
        repository = InMemoryAnalysisRepository()
        app.dependency_overrides[get_repository] = lambda: repository
        return TestClient(app)  # with 없이 써서 lifespan(DB 초기화)을 건너뛴다

    yield _make
    app.dependency_overrides.clear()


def test_create_then_get_analysis(make_client):
    finding = llm_finding(quote="약속의 목자", reference_ids=["scj-promised-pastor"])
    client = make_client(LLMAnalysis(summary="요약", findings=[finding]))

    created = client.post("/analyses", json={"segments": [{"time": "02:15", "text": TEXT, "source": "stt"}]})
    assert created.status_code == 201
    body = created.json()
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

    fetched = client.get(f"/analyses/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_engine_failure_is_reported_as_failed_job(make_client):
    client = make_client(AnalysisError("LLM 서버에 연결하지 못했습니다."))
    body = client.post("/analyses", json={"segments": [{"text": TEXT}]}).json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] == "LLM 서버에 연결하지 못했습니다."
    assert client.get(f"/analyses/{body['id']}").json()["status"] == "failed"


def test_unknown_analysis_is_404(make_client):
    client = make_client(LLMAnalysis(summary="요약", findings=[]))
    assert client.get("/analyses/없는-id").status_code == 404


@pytest.mark.parametrize("payload", [{"segments": []}, {"segments": [{"text": TEXT, "source": "video"}]}, {}])
def test_invalid_request_is_422(make_client, payload):
    client = make_client(LLMAnalysis(summary="요약", findings=[]))
    assert client.post("/analyses", json=payload).status_code == 422
