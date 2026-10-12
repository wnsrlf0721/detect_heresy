import pytest

from app.rag.engine import SEGMENTS_PER_CALL, AnalysisEngine, verdict_for
from app.schemas.analysis import Segment
from app.schemas.llm import LLMAnalysis
from app.schemas.reference import Verdict
from tests.conftest import FakeAnalyzer, llm_finding

PASTOR = "예수님이 약속하신 보혜사는 오늘날 이 땅에 육체로 오신 약속의 목자입니다."


def run(embedder, store, segments, findings):
    analyzer = FakeAnalyzer(LLMAnalysis(summary="요약", findings=findings))
    result = AnalysisEngine(embedder, store, analyzer).analyze(segments)
    return result, analyzer


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(0, Verdict.SAFE), (29, Verdict.SAFE), (30, Verdict.CAUTION), (69, Verdict.CAUTION), (70, Verdict.DANGER)],
)
def test_verdict_thresholds(score, verdict):
    assert verdict_for(score) == verdict


def test_no_findings_is_safe(embedder, store):
    result, _ = run(embedder, store, [Segment(text="오직 은혜로 구원받습니다.")], [])
    assert (result.verdict, result.score, result.findings) == (Verdict.SAFE, 0, [])


def test_overall_score_is_highest_finding(embedder, store):
    segments = [Segment(text="첫 발언"), Segment(text="둘째 발언")]
    findings = [llm_finding(segment_index=0, quote="첫 발언", score=40), llm_finding(segment_index=1, score=85)]
    result, _ = run(embedder, store, segments, findings)
    assert (result.score, result.verdict) == (85, Verdict.DANGER)


def test_time_and_source_come_from_segment(embedder, store):
    segments = [Segment(time="02:15", text=PASTOR, source="stt"), Segment(time="03:40", text="화면 글자", source="ocr")]
    findings = [llm_finding(segment_index=1, quote="화면 글자"), llm_finding(segment_index=0, quote="약속의 목자")]
    result, _ = run(embedder, store, segments, findings)
    assert [(f.time, f.source) for f in result.findings] == [("03:40", "ocr"), ("02:15", "stt")]


def test_low_score_and_invalid_index_are_dropped(embedder, store):
    findings = [llm_finding(score=10), llm_finding(segment_index=5), llm_finding(segment_index=-1)]
    result, _ = run(embedder, store, [Segment(text=PASTOR)], findings)
    assert result.findings == []
    assert result.verdict == Verdict.SAFE


def test_quote_not_in_segment_falls_back_to_segment_text(embedder, store):
    result, _ = run(embedder, store, [Segment(text=PASTOR)], [llm_finding(quote="구간에 없는 문장")])
    assert result.findings[0].quote == PASTOR


def test_retrieval_finds_matching_case_and_its_linked_orthodox_docs(embedder, store):
    _, analyzer = run(embedder, store, [Segment(text=PASTOR)], [])
    _, user = analyzer.calls[0]
    assert 'id="scj-promised-pastor"' in user
    # scj-promised-pastor 의 orthodox_refs
    assert 'id="wsc-21"' in user
    assert 'id="apostles-creed-3"' in user
    assert f'<segment index="0" source="user">\n{PASTOR}' in user


def test_only_retrieved_references_are_reported(embedder, store):
    findings = [llm_finding(quote="약속의 목자", reference_ids=["scj-promised-pastor", "지어낸-id", "wsc-21", "wsc-21"])]
    result, _ = run(embedder, store, [Segment(text=PASTOR)], findings)
    references = result.findings[0].references
    assert [r.id for r in references] == ["scj-promised-pastor", "wsc-21"]
    assert references[0].kind == "heresy"
    assert references[0].label == "신천지 교리 사례"
    assert references[1].label == "웨스트민스터 소요리문답 제21문"
    assert references[1].excerpt.startswith("하나님께서 택하신 자들의 유일한 구속자")


def test_many_segments_are_split_into_batches(embedder, store):
    segments = [Segment(text=f"발언 {i}") for i in range(SEGMENTS_PER_CALL + 1)]
    result, analyzer = run(embedder, store, segments, [llm_finding(segment_index=0, quote="발언", score=50)])
    assert len(analyzer.calls) == 2
    # 배치마다 index 가 0부터 다시 시작하므로 각 배치의 첫 구간이 적발된다.
    assert [f.quote for f in result.findings] == ["발언", "발언"]
    assert 'index="0"' in analyzer.calls[1][1]
