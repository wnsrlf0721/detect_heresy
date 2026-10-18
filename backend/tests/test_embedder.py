import httpx
import pytest

from app.errors import AnalysisError
from app.rag import embedder as embedder_module
from app.rag.embedder import VoyageEmbedder

OK = {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}


def make_embedder(monkeypatch, responses):
    """정해진 응답을 차례로 돌려주는 임베더와, 기다린 시간·요청 횟수 기록을 만든다."""
    sleeps: list[float] = []
    calls: list[httpx.Request] = []
    monkeypatch.setattr(embedder_module.time, "sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responses[min(len(calls), len(responses)) - 1]

    embedder = VoyageEmbedder("key", "voyage-4")
    embedder._client = httpx.Client(transport=httpx.MockTransport(handler))
    return embedder, sleeps, calls


def test_retries_after_rate_limit(monkeypatch):
    responses = [httpx.Response(429), httpx.Response(429), httpx.Response(200, json=OK)]
    embedder, sleeps, calls = make_embedder(monkeypatch, responses)

    assert embedder.embed(["문장"], "query") == [[0.1, 0.2]]
    assert len(calls) == 3
    assert sleeps == [5.0, 10.0]


def test_retry_after_header_is_used(monkeypatch):
    responses = [httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, json=OK)]
    embedder, sleeps, _ = make_embedder(monkeypatch, responses)

    embedder.embed(["문장"], "query")
    assert sleeps == [7.0]


def test_gives_up_when_rate_limit_persists(monkeypatch):
    embedder, _, calls = make_embedder(monkeypatch, [httpx.Response(429)])

    with pytest.raises(AnalysisError, match="429"):
        embedder.embed(["문장"], "query")
    assert len(calls) == VoyageEmbedder.MAX_ATTEMPTS


def test_other_errors_are_not_retried(monkeypatch):
    embedder, sleeps, calls = make_embedder(monkeypatch, [httpx.Response(401)])

    with pytest.raises(AnalysisError, match="401"):
        embedder.embed(["문장"], "query")
    assert len(calls) == 1
    assert sleeps == []


def test_batches_respect_count_and_character_limits():
    texts = ["가" * 4, "나" * 4, "다" * 4, "라" * 9, "마"]
    assert embedder_module._batches(texts, max_count=2, max_chars=10) == [
        ["가" * 4, "나" * 4],
        ["다" * 4],
        ["라" * 9, "마"],
    ]
    # 한도보다 긴 텍스트 하나는 혼자 보낸다.
    assert embedder_module._batches(["가" * 20, "나"], max_count=10, max_chars=10) == [["가" * 20], ["나"]]
