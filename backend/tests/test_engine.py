import pytest

from app.errors import AnalysisError
from app.rag.context import with_context
from app.rag.engine import (
    NOTHING_TO_ANALYZE,
    SCREEN_MIN_SEGMENTS,
    SEGMENTS_PER_CALL,
    AnalysisEngine,
    merge_same_speech,
    verdict_for,
)
from app.schemas.analysis import Finding, Segment
from app.schemas.llm import LLMAnalysis, SegmentSelection
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
    assert f'<segment index="0" source="user">\n<text>{PASTOR}</text>' in user


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


def test_all_segments_are_embedded_in_one_request(embedder, store):
    calls = []

    class CountingEmbedder:
        def embed(self, texts, input_type):
            calls.append(len(texts))
            return embedder.embed(texts, input_type)

    segments = [Segment(text=f"발언 {i}") for i in range(SEGMENTS_PER_CALL * 2 + 1)]
    run(CountingEmbedder(), store, segments, [])
    assert calls == [len(segments)]


def _finding(source, time, quote, score=80):
    return Finding(time=time, source=source, quote=quote, score=score, reason="이유", orthodox_refutation="반증")


def test_same_speech_from_caption_and_stt_is_merged_keeping_higher_score():
    caption = _finding("caption", "02:10", "보혜사는 오늘날 육체로 오신 약속의 목자입니다", score=75)
    stt = _finding("stt", "02:15", "보혜사는 오늘날 육체로 오신 약속에 목자입니다.", score=90)
    assert merge_same_speech([caption, stt]) == [stt]


@pytest.mark.parametrize(
    "other",
    [
        _finding("stt", "05:00", "보혜사는 오늘날 육체로 오신 약속의 목자입니다"),  # 시간이 멀다
        _finding("stt", "02:12", "기성교회는 배도하여 멸망받은 바벨론입니다"),  # 다른 발언
        _finding("caption", "02:12", "보혜사는 오늘날 육체로 오신 약속의 목자입니다"),  # 같은 출처
        _finding("ocr", "02:12", "보혜사는 오늘날 육체로 오신 약속의 목자입니다"),  # 화면 글자는 대상 아님
    ],
)
def test_different_speech_is_kept(other):
    caption = _finding("caption", "02:10", "보혜사는 오늘날 육체로 오신 약속의 목자입니다")
    assert merge_same_speech([caption, other]) == [caption, other]


def test_engine_merges_duplicates_before_scoring(embedder, store):
    segments = [
        Segment(time="02:10", text=PASTOR, source="caption"),
        Segment(time="02:14", text=PASTOR, source="stt"),
    ]
    findings = [llm_finding(segment_index=0, quote=PASTOR, score=72), llm_finding(segment_index=1, quote=PASTOR, score=88)]
    result, _ = run(embedder, store, segments, findings)
    assert [(f.source, f.score) for f in result.findings] == [("stt", 88)]
    assert result.score == 88


# --- 앞뒤 문맥 ---


def test_context_comes_from_neighbors_of_the_same_source():
    segments = [
        Segment(time="00:01", text="자막1", source="caption"),
        Segment(time="00:01", text="음성1", source="stt"),
        Segment(time="00:03", text="음성2", source="stt"),
        Segment(time="00:05", text="음성3", source="stt"),
        Segment(time="00:07", text="음성4", source="stt"),
        Segment(time="00:02", text="화면1", source="ocr"),
    ]
    targets = with_context(segments)
    assert (targets[3].before, targets[3].after) == (["음성1", "음성2"], ["음성4"])
    assert (targets[1].before, targets[1].after) == ([], ["음성2"])
    assert (targets[0].before, targets[0].after) == ([], [])
    assert targets[3].window_text == "음성1 음성2 음성3 음성4"


def test_prompt_shows_context_and_search_uses_it(embedder, store):
    texts = []

    class RecordingEmbedder:
        def embed(self, batch, input_type):
            texts.extend(batch)
            return embedder.embed(batch, input_type)

    segments = [Segment(text="약속하신 보혜사가 있죠.", source="stt"), Segment(text="그분이 바로 우리 선생님입니다.", source="stt")]
    _, analyzer = run(RecordingEmbedder(), store, segments, [])
    user = analyzer.calls[0][1]
    assert "<before>약속하신 보혜사가 있죠.</before>\n<text>그분이 바로 우리 선생님입니다.</text>" in user
    assert texts[1] == "약속하신 보혜사가 있죠. 그분이 바로 우리 선생님입니다."


def test_quote_from_context_falls_back_to_segment_text(embedder, store):
    segments = [Segment(text="약속하신 보혜사가 있죠.", source="stt"), Segment(text="그분이 바로 우리 선생님입니다.", source="stt")]
    result, _ = run(embedder, store, segments, [llm_finding(segment_index=1, quote="약속하신 보혜사가 있죠.")])
    assert result.findings[0].quote == "그분이 바로 우리 선생님입니다."


# --- 1차 선별 ---


class FakeScreener:
    def __init__(self, output):
        self.output = output
        self.calls: list[str] = []

    def screen(self, system, user):
        self.calls.append(user)
        if isinstance(self.output, Exception):
            raise self.output
        return SegmentSelection(indices=self.output)


def screened(embedder, store, segments, selection, findings=()):
    screener = FakeScreener(selection)
    analyzer = FakeAnalyzer(LLMAnalysis(summary="요약", findings=list(findings)))
    progress: list[str] = []
    result = AnalysisEngine(embedder, store, analyzer, screener).analyze(segments, progress.append)
    return result, analyzer, screener, progress


LONG = [Segment(time=f"00:{i:02d}", text=f"발언 {i}", source="stt") for i in range(SCREEN_MIN_SEGMENTS + 10)]


def test_only_selected_segments_are_analyzed(embedder, store):
    result, analyzer, screener, progress = screened(
        embedder, store, LONG, [25, 3, 3, 999, -1], [llm_finding(segment_index=1, quote="발언 25", score=80)]
    )
    assert len(screener.calls) == 1
    user = analyzer.calls[0][1]
    assert "<text>발언 3</text>" in user and "<text>발언 25</text>" in user
    assert "<text>발언 4</text>" not in user  # 선별되지 않은 구간은 문맥으로만 쓰인다
    assert "<after>발언 4</after>" in user
    # 선별된 구간 순서(3, 25)대로 번호가 매겨진다.
    assert [(f.time, f.quote) for f in result.findings] == [("00:25", "발언 25")]
    assert progress == ["구간 30개 중 의심 구간을 고르는 중", "구간 2개를 정통 교리와 비교하는 중"]


def test_nothing_selected_skips_detailed_analysis(embedder, store):
    result, analyzer, _, _ = screened(embedder, store, LONG, [])
    assert analyzer.calls == []
    assert (result.verdict, result.summary) == (Verdict.SAFE, NOTHING_TO_ANALYZE)


def test_screening_failure_falls_back_to_all_segments(embedder, store):
    _, analyzer, _, _ = screened(embedder, store, LONG, AnalysisError("요청 한도 초과"))
    analyzed = sum(user.count("<text>") for _, user in analyzer.calls)
    assert analyzed == len(LONG)


def test_short_input_is_not_screened(embedder, store):
    short = LONG[:SCREEN_MIN_SEGMENTS]
    _, analyzer, screener, _ = screened(embedder, store, short, [0])
    assert screener.calls == []
    assert sum(user.count("<text>") for _, user in analyzer.calls) == len(short)
