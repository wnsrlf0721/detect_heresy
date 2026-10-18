"""판별 엔진: 구간 → (긴 입력이면) 1차 선별 → 관련 기준 데이터 검색 → LLM 비교 분석 → 결과 조립."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app import prompts
from app.errors import AnalysisError
from app.rag.context import Target, with_context
from app.rag.embedder import Embedder
from app.rag.llm import Analyzer, Screener
from app.rag.store import VectorStore
from app.schemas.analysis import AnalysisResult, Finding, Reference, Segment
from app.schemas.llm import LLMFinding
from app.schemas.reference import Chunk, Verdict

# 판별 결과가 달라지는 코드 변경을 하면 올린다. 저장된 영상 분석을 다시 쓰지 않게 된다(app/rag/version.py).
ENGINE_REVISION = 2

# app/prompts/analyze_system.md 의 점수 기준과 같은 값이어야 한다.
CAUTION_MIN = 30
DANGER_MIN = 70

TOP_K_PER_KIND = 3
SEGMENTS_PER_CALL = 20
# 긴 영상은 배치가 여러 개라, LLM 호출을 이만큼씩 동시에 보낸다.
MAX_PARALLEL_CALLS = 4

# 구간이 한 번의 정밀 분석 호출보다 많을 때만 1차 선별을 한다. 짧은 입력은 바로 정밀 분석한다.
SCREEN_MIN_SEGMENTS = SEGMENTS_PER_CALL
SEGMENTS_PER_SCREEN_CALL = 100
NOTHING_TO_ANALYZE = "1차 선별에서 교리를 다루는 발언을 찾지 못해 정밀 분석을 하지 않았습니다."

# 자막과 음성 인식은 같은 말을 담고 있다. 두 출처의 적발이 이 시간 안에 있고 인용문이 이만큼
# 겹치면 같은 발언으로 보고 하나만 남긴다. 자막은 60자씩 묶여 시작 시각이 음성보다 앞설 수 있다.
SPEECH_SOURCES = {"caption", "stt"}
SAME_SPEECH_SECONDS = 20
SAME_SPEECH_OVERLAP = 0.5


def verdict_for(score: int) -> Verdict:
    if score >= DANGER_MIN:
        return Verdict.DANGER
    if score >= CAUTION_MIN:
        return Verdict.CAUTION
    return Verdict.SAFE


def _reference(chunk: Chunk) -> Reference:
    m = chunk.metadata
    if chunk.kind == "orthodox":
        return Reference(id=chunk.id, kind="orthodox", label=f"{m['source']} {m['section']}", excerpt=m["text"])
    return Reference(id=chunk.id, kind="heresy", label=f"{m['group']} 교리 사례", excerpt=m["claim"])


def _seconds(time: str) -> int:
    seconds = 0
    for part in time.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def _bigrams(text: str) -> set[str]:
    compact = "".join(text.split())
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _same_speech(a: Finding, b: Finding) -> bool:
    """자막과 음성 인식에서 각각 적발된 같은 발언인지. 인식 결과가 조금씩 달라 글자 2-gram 겹침으로 비교한다."""
    if {a.source, b.source} != SPEECH_SOURCES or a.time is None or b.time is None:
        return False
    if abs(_seconds(a.time) - _seconds(b.time)) > SAME_SPEECH_SECONDS:
        return False
    x, y = _bigrams(a.quote), _bigrams(b.quote)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= SAME_SPEECH_OVERLAP


def merge_same_speech(findings: list[Finding]) -> list[Finding]:
    """같은 발언이 자막과 음성에서 두 번 적발되면 점수가 높은 쪽 하나만 남긴다. 순서는 처음 나온 자리를 따른다."""
    merged: list[Finding] = []
    for finding in findings:
        duplicate = next((i for i, kept in enumerate(merged) if _same_speech(kept, finding)), None)
        if duplicate is None:
            merged.append(finding)
        elif finding.score > merged[duplicate].score:
            merged[duplicate] = finding
    return merged


class AnalysisEngine:
    def __init__(self, embedder: Embedder, store: VectorStore, analyzer: Analyzer, screener: Screener | None = None):
        self._embedder = embedder
        self._store = store
        self._analyzer = analyzer
        self._screener = screener

    def _screen_batch(self, system: str, start: int, batch: list[Segment]) -> list[int]:
        """한 묶음에서 고른 구간의 전체 번호. 선별이 실패하면 놓치지 않도록 묶음 전체를 정밀 분석한다."""
        try:
            selection = self._screener.screen(system, prompts.filter_user_prompt(list(enumerate(batch))))
        except AnalysisError:
            return list(range(start, start + len(batch)))
        return sorted({start + i for i in selection.indices if 0 <= i < len(batch)})

    def _screen(self, segments: list[Segment]) -> list[int]:
        system = prompts.filter_system_prompt()
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            futures = [
                pool.submit(self._screen_batch, system, start, segments[start : start + SEGMENTS_PER_SCREEN_CALL])
                for start in range(0, len(segments), SEGMENTS_PER_SCREEN_CALL)
            ]
            return [index for future in futures for index in future.result()]

    def _retrieve(self, embeddings: list[list[float]]) -> dict[str, Chunk]:
        """구간마다 이단 사례와 정통 조항을 따로 검색하고, 이단 사례에 연결된 정통 조항도 함께 가져온다."""
        found: dict[str, Chunk] = {}
        for embedding in embeddings:
            for kind in ("heresy", "orthodox"):
                for chunk in self._store.search(embedding, kind, TOP_K_PER_KIND):
                    found[chunk.id] = chunk
        linked = {
            ref
            for chunk in found.values()
            if chunk.kind == "heresy"
            for ref in chunk.metadata.get("orthodox_refs", [])
        }
        for chunk in self._store.get(sorted(linked - found.keys())):
            found[chunk.id] = chunk
        return found

    def _to_finding(self, raw: LLMFinding, targets: list[Target], refs: dict[str, Chunk]) -> Finding | None:
        if raw.score < CAUTION_MIN or not 0 <= raw.segment_index < len(targets):
            return None
        segment = targets[raw.segment_index].segment
        return Finding(
            time=segment.time,
            source=segment.source,
            # 구간에 없는 문장(앞뒤 문맥 포함)을 인용했다면 구간 원문으로 대체한다.
            quote=raw.quote if raw.quote in segment.text else segment.text,
            score=raw.score,
            group=raw.group,
            topic=raw.topic,
            reason=raw.reason,
            orthodox_refutation=raw.orthodox_refutation,
            heresy_intent=raw.heresy_intent,
            scripture=raw.scripture,
            # 검색되지 않은 id 는 버려서, 실재하는 기준 데이터만 근거로 표시되게 한다.
            references=[_reference(refs[i]) for i in dict.fromkeys(raw.reference_ids) if i in refs],
        )

    def _analyze_batch(
        self, system: str, batch: list[Target], embeddings: list[list[float]]
    ) -> tuple[str, list[Finding]]:
        refs = self._retrieve(embeddings)
        user = prompts.user_prompt(list(enumerate(batch)), list(refs.values()))
        output = self._analyzer.analyze(system, user)
        findings = [f for raw in output.findings if (f := self._to_finding(raw, batch, refs))]
        return output.summary, findings

    def analyze(self, segments: list[Segment], on_progress: Callable[[str], None] = lambda _: None) -> AnalysisResult:
        # 문맥은 선별 전에 붙여서, 선별에서 빠진 구간도 이웃 구간의 문맥으로는 쓰이게 한다.
        targets = with_context(segments)
        if self._screener and len(segments) > SCREEN_MIN_SEGMENTS:
            on_progress(f"구간 {len(segments)}개 중 의심 구간을 고르는 중")
            targets = [targets[i] for i in self._screen(segments)]
            if not targets:
                return AnalysisResult(verdict=Verdict.SAFE, score=0, summary=NOTHING_TO_ANALYZE, findings=[])
        on_progress(f"구간 {len(targets)}개를 정통 교리와 비교하는 중")

        system = prompts.system_prompt()
        # 임베딩은 전체를 한 번에 요청해 호출 수를 줄인다. 검색에는 앞뒤 문맥까지 포함한 텍스트를 쓴다.
        embeddings = self._embedder.embed([t.window_text for t in targets], "query")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            futures = [
                pool.submit(
                    self._analyze_batch,
                    system,
                    targets[start : start + SEGMENTS_PER_CALL],
                    embeddings[start : start + SEGMENTS_PER_CALL],
                )
                for start in range(0, len(targets), SEGMENTS_PER_CALL)
            ]
            results = [future.result() for future in futures]  # 구간 순서를 유지한다

        findings = merge_same_speech([finding for _, batch_findings in results for finding in batch_findings])
        score = max((f.score for f in findings), default=0)
        return AnalysisResult(
            verdict=verdict_for(score),
            score=score,
            summary=" ".join(summary for summary, _ in results),
            findings=findings,
        )
