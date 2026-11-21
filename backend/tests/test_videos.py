import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_analysis_version,
    get_engine,
    get_pipeline,
    get_related_min_similarity,
    get_repository,
    get_topic_service,
)
from app.db.repository import InMemoryRepository
from app.errors import AnalysisError
from app.main import app
from app.media import youtube_video_id
from app.media.downloader import Media
from app.media.pipeline import TranscriptPipeline
from app.rag.engine import AnalysisEngine
from app.rag.topic import TopicService
from app.schemas.analysis import JobStatus, Segment
from app.schemas.llm import LLMAnalysis, LLMTopic
from app.schemas.video import VideoResponse
from tests.conftest import FakeAnalyzer, llm_finding

PASTOR = "예수님이 약속하신 보혜사는 오늘날 이 땅에 육체로 오신 약속의 목자입니다."
VIDEO_A = "https://youtu.be/AAAAAAAAAAA"
VIDEO_B = "https://youtu.be/BBBBBBBBBBB"
VIDEO_C = "https://youtu.be/CCCCCCCCCCC"

TITLES = {"AAAAAAAAAAA": "보혜사 강의 1", "BBBBBBBBBBB": "보혜사 강의 2", "CCCCCCCCCCC": "산상수훈 설교"}
TOPICS = {
    "보혜사 강의 1": "오늘날 육체로 온 보혜사와 약속의 목자를 다루는 강의",
    "보혜사 강의 2": "오늘날 육체로 온 보혜사와 약속의 목자를 다루는 강의",
    "산상수훈 설교": "마태복음 오장의 팔복으로 제자의 삶을 설명하는 설교",
}


class FakeSource:
    def __init__(self, error=None):
        self.fetched: list[str] = []
        self.error = error

    def fetch(self, url, workdir, *, automatic_speech=False):
        self.fetched.append(url)
        if self.error:
            raise self.error
        captions = [Segment(time="00:10", text=PASTOR, source="caption")]
        return Media(TITLES[youtube_video_id(url)], 240, Path(workdir) / "a.m4a", Path(workdir) / "v.mp4", captions, [])


class FakeStep:
    def __init__(self, segments):
        self.segments = segments

    def _run(self, path):
        return self.segments

    transcribe = read = _run


class FakeTopicWriter:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def write(self, system, user):
        self.calls += 1
        if self.fail:
            raise AnalysisError("요청 한도 초과")
        title = next(t for t in TITLES.values() if f"<title>{t}</title>" in user)
        return LLMTopic(title=TOPICS[title], summary=TOPICS[title], keywords=["보혜사"])


@pytest.fixture
def make_client(embedder, store):
    def _make(findings=(), topic_fail=False, download_error=None):
        state = {"version": "v1"}
        source = FakeSource(download_error)
        stt = [Segment(time="00:11", text=PASTOR, source="stt")]
        analyzer = FakeAnalyzer(LLMAnalysis(summary="요약", findings=list(findings)))
        writer = FakeTopicWriter(topic_fail)
        repository = InMemoryRepository()
        app.dependency_overrides[get_pipeline] = lambda: TranscriptPipeline(source, FakeStep(stt), FakeStep([]))
        app.dependency_overrides[get_engine] = lambda: AnalysisEngine(embedder, store, analyzer)
        app.dependency_overrides[get_topic_service] = lambda: TopicService(writer, embedder)
        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_analysis_version] = lambda: state["version"]
        app.dependency_overrides[get_related_min_similarity] = lambda: 0.9
        client = TestClient(app)
        client.source, client.analyzer, client.state, client.repository = source, analyzer, state, repository
        client.writer = writer
        return client

    yield _make
    app.dependency_overrides.clear()


def analyze(client, url, sources=("caption", "ocr", "stt"), **body):
    """POST 후 (TestClient 가 끝낸) 백그라운드 작업의 결과를 GET 으로 가져온다."""
    if sources is not None:
        body["sources"] = sources
    created = client.post("/videos", json={"url": url, **body})
    assert created.status_code in (200, 202), created.text
    return created, client.get(f"/videos/{created.json()['id']}").json()


def test_video_is_extracted_analyzed_and_summarized(make_client, caplog):
    caplog.set_level("INFO", logger="uvicorn.error.app.api.videos")
    caplog.set_level("INFO", logger="uvicorn.error.app.timing")
    client = make_client([llm_finding(segment_index=0, quote="약속의 목자", score=85)])

    created, body = analyze(client, VIDEO_A)

    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    assert body["status"] == "done"
    assert body["cached"] is False
    assert body["sources"] == ["caption", "ocr", "stt"]
    assert body["transcript"]["title"] == "보혜사 강의 1"
    # 자막과 음성에서 같은 발언이 적발돼 하나로 합쳐진다.
    assert [(f["time"], f["score"]) for f in body["result"]["findings"]] == [("00:10", 85)]
    assert body["topic"]["title"] == TOPICS["보혜사 강의 1"]
    assert body["progress"] is None
    assert f"video_analysis.transcript_saved analysis_id={body['id']}" in caplog.text
    assert f"video_analysis.topic_saved analysis_id={body['id']}" in caplog.text
    assert f"video_analysis.result_saved analysis_id={body['id']}" in caplog.text
    summary = next(message for message in caplog.messages if message.startswith("analysis.timing_summary "))
    assert f"analysis_id={body['id']} kind=video status=done" in summary
    stages = json.loads(summary.split(" stages=", 1)[1])
    assert all(stages[key]["calls"] == 1 for key in (
        "stt", "ocr", "topic_llm", "topic_embedding", "query_embedding", "reference_search", "verdict_llm", "db_write_result",
    ))
    assert len(body["log_times"]) == len(body["log"])


def test_same_video_returns_saved_analysis(make_client):
    client = make_client()
    _, first = analyze(client, VIDEO_A)

    # 주소 형태가 달라도 같은 영상이다.
    created, _ = analyze(client, "https://www.youtube.com/watch?v=AAAAAAAAAAA&t=30s")

    assert created.status_code == 200
    assert created.json()["id"] == first["id"]
    assert created.json()["cached"] is True
    assert created.json()["result"] == first["result"]
    assert len(client.source.fetched) == 1
    assert len(client.analyzer.calls) == 1


def test_automatic_analysis_uses_its_own_transcript_and_cache(make_client):
    client = make_client()
    _, legacy = analyze(client, VIDEO_A)
    created, first = analyze(client, VIDEO_A, sources=None)
    assert created.status_code == 202 and first["id"] != legacy["id"]
    assert first["sources"] == ["caption"]
    assert {s["source"] for s in first["transcript"]["segments"]} == {"caption"}
    assert 'source="stt"' not in client.analyzer.calls[-1][1]
    assert len(client.source.fetched) == 2
    assert client.get(f"/videos/{first['id']}/status").json() == {
        "id": first["id"], "status": "done", "progress": None,
    }

    cached, _ = analyze(client, VIDEO_A, sources=None)
    assert cached.status_code == 200 and cached.json()["id"] == first["id"]
    client.state["version"] = "v2"
    _, reanalyzed = analyze(client, VIDEO_A, sources=None)
    assert reanalyzed["id"] != first["id"] and reanalyzed["sources"] == ["caption"]
    assert len(client.source.fetched) == 2


def test_different_sources_reuse_extracted_text(make_client):
    client = make_client()
    _, first = analyze(client, VIDEO_A)

    created, body = analyze(client, VIDEO_A, sources=["stt"])

    assert created.status_code == 202
    assert body["id"] != first["id"]
    assert body["status"] == "done"
    assert len(client.source.fetched) == 1  # 내려받기와 음성 인식을 다시 하지 않는다
    assert len(client.analyzer.calls) == 2
    assert "<text>" + PASTOR + "</text>" in client.analyzer.calls[1][1]
    assert 'source="caption"' not in client.analyzer.calls[1][1]
    # 같은 추출 결과를 쓰므로 대주제도 다시 정리하지 않는다.
    assert client.writer.calls == 1
    assert body["topic"] == first["topic"]
    assert len(client.repository.transcripts) == 1


def test_changed_reference_data_reanalyzes(make_client):
    client = make_client()
    analyze(client, VIDEO_A)

    client.state["version"] = "v2"
    created, _ = analyze(client, VIDEO_A)

    assert created.status_code == 202
    assert len(client.source.fetched) == 1
    assert len(client.analyzer.calls) == 2


def test_force_extracts_again(make_client):
    client = make_client()
    analyze(client, VIDEO_A)

    created, _ = analyze(client, VIDEO_A, force=True)

    assert created.status_code == 202
    assert len(client.source.fetched) == 2
    assert len(client.repository.transcripts) == 2
    assert len(client.repository.videos) == 1


def test_findings_point_to_their_segment(make_client):
    # 1차 선별 없이 구간 두 개(자막, 음성)를 판별하고, 음성 구간만 적발한다.
    client = make_client([llm_finding(segment_index=1, quote="약속의 목자", score=85)])

    _, body = analyze(client, VIDEO_A)

    assert [(f["time"], f["source"]) for f in body["result"]["findings"]] == [("00:11", "stt")]
    assert "segment_index" not in body["result"]["findings"][0]


def test_download_failure_is_reported_as_failed_job(make_client):
    client = make_client(download_error=AnalysisError("영상이 너무 깁니다."))
    _, body = analyze(client, VIDEO_A)
    assert body["status"] == "failed"
    assert body["error"] == "영상이 너무 깁니다."
    assert body["transcript"] is None


def test_running_job_is_shared(make_client):
    client = make_client()
    running = VideoResponse(
        id="11111111-1111-1111-1111-111111111111",
        status=JobStatus.RUNNING,
        url=VIDEO_A,
        sources=[],
        created_at=datetime.now(UTC),
    )
    client.repository.create_video_analysis(running, "AAAAAAAAAAA", "v1")

    created = client.post("/videos", json={"url": VIDEO_A})

    assert created.json()["id"] == running.id
    assert client.source.fetched == []


def test_related_videos_have_similar_topics(make_client):
    client = make_client()
    _, a = analyze(client, VIDEO_A)
    analyze(client, VIDEO_C)
    _, b = analyze(client, VIDEO_B)

    assert [r["id"] for r in b["related"]] == [a["id"]]
    related = b["related"][0]
    assert (related["title"], related["topic"], related["verdict"]) == ("보혜사 강의 1", TOPICS["보혜사 강의 1"], "safe")
    assert related["similarity"] == pytest.approx(1.0)
    # 먼저 분석한 영상도 조회할 때 나중에 분석한 비슷한 영상을 찾는다.
    assert [r["id"] for r in client.get(f"/videos/{a['id']}").json()["related"]] == [b["id"]]


def test_topic_failure_keeps_analysis(make_client):
    client = make_client(topic_fail=True)
    _, body = analyze(client, VIDEO_A)
    assert body["status"] == "done"
    assert body["topic"] is None
    assert body["related"] == []


def test_no_text_in_selected_sources_fails(make_client):
    client = make_client()
    _, body = analyze(client, VIDEO_A, sources=["ocr"])
    assert body["status"] == "failed"
    assert body["error"] == "선택한 출처에서 추출된 텍스트가 없습니다."


def test_unknown_video_is_404(make_client):
    assert make_client().get("/videos/없는-id").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"url": "https://youtube.com/channel/abc"},
        {"url": "https://example.com/watch?v=AAAAAAAAAAA"},
        {"url": "http://youtu.be/AAAAAAAAAAA"},
        {"url": "file:///etc/passwd"},
        {"url": ""},
        {"url": VIDEO_A, "sources": []},
        {"url": VIDEO_A, "sources": ["user"]},
    ],
)
def test_invalid_request_is_422(make_client, body):
    assert make_client().post("/videos", json=body).status_code == 422


@pytest.mark.parametrize(
    ("url", "video_id"),
    [
        ("https://youtu.be/UeXJQ7cA7lo", "UeXJQ7cA7lo"),
        ("https://youtu.be/UeXJQ7cA7lo?si=abc", "UeXJQ7cA7lo"),
        ("https://www.youtube.com/watch?v=UeXJQ7cA7lo&t=10s", "UeXJQ7cA7lo"),
        ("https://m.youtube.com/watch?v=UeXJQ7cA7lo", "UeXJQ7cA7lo"),
        ("https://youtube.com/shorts/UeXJQ7cA7lo", "UeXJQ7cA7lo"),
        ("https://www.youtube.com/live/UeXJQ7cA7lo", "UeXJQ7cA7lo"),
        ("https://www.youtube.com/watch?v=short", None),
        ("https://www.youtube.com/@channel", None),
    ],
)
def test_youtube_video_id(url, video_id):
    assert youtube_video_id(url) == video_id


def test_log_records_each_step_and_merged_text(make_client):
    client = make_client([llm_finding(segment_index=0, quote="약속의 목자", score=85)])

    _, body = analyze(client, VIDEO_A)

    log = body["log"]
    assert log[:3] == ["영상을 내려받는 중입니다.", "‘보혜사 강의 1’ 영상(4분 0초)을 내려받았습니다.", "영상에 딸린 자막에서 1구간을 가져왔습니다."]
    assert "자막·음성·화면 글자에서 겹치는 내용을 합쳐 1줄로 정리했습니다." in log
    assert "판별에는 자막 1구간, 음성 1구간을 씁니다." in log
    assert f"영상 요약을 정리했습니다: {TOPICS['보혜사 강의 1']}" in log
    assert "[00:10] “약속의 목자” — 신천지의 가르침과 닮았습니다 (85점)" in log
    assert log[-1] == "판별을 마쳤습니다. 의심 발언 1건, 종합 의심 지수 85점(위험)."
    # 자막과 음성은 같은 말이라, 합친 텍스트에는 자막만 남는다.
    assert [(s["time"], s["source"]) for s in body["transcript"]["merged"]] == [("00:10", "caption")]


class WaitingAnalyzer(FakeAnalyzer):
    """요약이 저장될 때까지 판별을 붙잡아 두고, 그동안 화면이 받는 응답을 기록한다."""

    def __init__(self, repository):
        super().__init__(LLMAnalysis(summary="요약", findings=[]))
        self.repository = repository
        self.seen: VideoResponse | None = None

    def analyze(self, system, user):
        (job_id,) = self.repository.analyses
        deadline = time.monotonic() + 5
        while (seen := self.repository.get_video_analysis(job_id)).topic is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.seen = seen
        return super().analyze(system, user)


def test_summary_is_shown_while_analysis_runs(make_client, embedder, store):
    client = make_client()
    analyzer = WaitingAnalyzer(client.repository)
    app.dependency_overrides[get_engine] = lambda: AnalysisEngine(embedder, store, analyzer)

    _, body = analyze(client, VIDEO_A)

    assert body["status"] == "done"
    assert (analyzer.seen.status, analyzer.seen.result) == (JobStatus.RUNNING, None)
    assert analyzer.seen.topic.title == TOPICS["보혜사 강의 1"]
    assert analyzer.seen.transcript.merged


def test_reused_text_is_noted_in_log(make_client):
    client = make_client()
    analyze(client, VIDEO_A)

    _, body = analyze(client, VIDEO_A, sources=["stt"])

    assert body["log"][0] == "이 영상에서 이전에 추출한 텍스트(자막 1구간, 음성 1구간)를 다시 씁니다."
    assert not any("요약" in line for line in body["log"])  # 요약은 추출 결과마다 한 번만 한다


def test_topic_failure_is_noted_in_log(make_client):
    client = make_client(topic_fail=True)
    _, body = analyze(client, VIDEO_A)
    assert "영상 요약을 만들지 못했습니다. 판별은 계속합니다." in body["log"]
