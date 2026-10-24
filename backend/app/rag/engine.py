"""판별 엔진: 구간 → (긴 입력이면) 1차 선별 → 관련 기준 데이터 검색 → LLM 비교 분석 → 결과 조립."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app import prompts
from app.errors import AnalysisError
from app.media import bigrams, parse_time
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

# 진행 과정(on_progress)에 남기는 문장의 길이. 화면에 한 줄로 보이게 줄인다.
LOG_QUOTE_CHARS = 40
LOG_REFERENCE_LABELS = 3
VERDICT_LABEL = {Verdict.SAFE: "안전", Verdict.CAUTION: "주의", Verdict.DANGER: "위험"}

Progress = Callable[[str], None]


def verdict_for(score: int) -> Verdict:
    if score >= DANGER_MIN:
        return Verdict.DANGER
    if score >= CAUTION_MIN:
        return Verdict.CAUTION
    return Verdict.SAFE


def reference_for(chunk: Chunk) -> Reference:
    """기준 데이터 청크를 화면에 보이는 근거 형태로 바꾼다. 저장된 적발을 다시 읽을 때도 쓴다."""
    m = chunk.metadata
    if chunk.kind == "orthodox":
        return Reference(id=chunk.id, kind="orthodox", label=f"{m['source']} {m['section']}", excerpt=m["text"])
    return Reference(id=chunk.id, kind="heresy", label=f"{m['group']} 교리 사례", excerpt=m["claim"])


def _same_speech(a: Finding, b: Finding) -> bool:
    """자막과 음성 인식에서 각각 적발된 같은 발언인지. 인식 결과가 조금씩 달라 글자 2-gram 겹침으로 비교한다."""
    if {a.source, b.source} != SPEECH_SOURCES or a.time is None or b.time is None:
        return False
    if abs(parse_time(a.time) - parse_time(b.time)) > SAME_SPEECH_SECONDS:
        return False
    x, y = bigrams(a.quote), bigrams(b.quote)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= SAME_SPEECH_OVERLAP


def _short(text: str) -> str:
    return text if len(text) <= LOG_QUOTE_CHARS else text[:LOG_QUOTE_CHARS] + "…"


def _finding_note(finding: Finding) -> str:
    where = f"[{finding.time}] " if finding.time else ""
    why = f"{finding.group}의 가르침과 닮았습니다" if finding.group else "정통 교리에서 벗어난 발언으로 보입니다"
    return f"{where}“{_short(finding.quote)}” — {why} ({finding.score}점)"


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

    def _screen_batch(self, system: str, start: int, batch: list[Segment], on_progress: Progress) -> list[int]:
        """한 묶음에서 고른 구간의 전체 번호. 선별이 실패하면 놓치지 않도록 묶음 전체를 정밀 분석한다."""
        try:
            selection = self._screener.screen(system, prompts.filter_user_prompt(list(enumerate(batch))))
        except AnalysisError:
            on_progress(f"1차 선별 일부가 실패해, 그 구간 {len(batch)}개는 빠짐없이 정밀 분석합니다.")
            return list(range(start, start + len(batch)))
        return sorted({start + i for i in selection.indices if 0 <= i < len(batch)})

    def _screen(self, segments: list[Segment], on_progress: Progress) -> list[int]:
        system = prompts.filter_system_prompt()
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            futures = [
                pool.submit(
                    self._screen_batch, system, start, segments[start : start + SEGMENTS_PER_SCREEN_CALL], on_progress
                )
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
            segment_index=targets[raw.segment_index].index,
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
            references=[reference_for(refs[i]) for i in dict.fromkeys(raw.reference_ids) if i in refs],
        )

    def _analyze_batch(
        self, system: str, name: str, batch: list[Target], embeddings: list[list[float]], on_progress: Progress
    ) -> tuple[str, list[Finding]]:
        refs = self._retrieve(embeddings)
        # 이단 사례를 먼저 보여 준다. 같은 단체의 사례는 이름이 같아 한 번만 적는다.
        heresy_first = sorted(refs.values(), key=lambda c: c.kind != "heresy")
        labels = list(dict.fromkeys(reference_for(c).label for c in heresy_first))
        shown = ", ".join(labels[:LOG_REFERENCE_LABELS]) + (" 등" if len(labels) > LOG_REFERENCE_LABELS else "")
        on_progress(f"{name}: 비슷한 기준 자료 {len(refs)}건({shown})을 찾았습니다. 정통 교리와 비교해 판단하는 중입니다.")
        user = prompts.user_prompt(list(enumerate(batch)), list(refs.values()))
        output = self._analyzer.analyze(system, user)
        findings = [f for raw in output.findings if (f := self._to_finding(raw, batch, refs))]
        for finding in findings:
            on_progress(_finding_note(finding))
        if not findings:
            on_progress(f"{name}: 정통 교리에서 벗어난 발언을 찾지 못했습니다.")
        return output.summary, findings

    def analyze(self, segments: list[Segment], on_progress: Progress = lambda _: None) -> AnalysisResult:
        """on_progress 로 단계마다 실제로 한 일을 알린다. 화면의 '진행 과정'에 그대로 쌓인다."""
        # 문맥은 선별 전에 붙여서, 선별에서 빠진 구간도 이웃 구간의 문맥으로는 쓰이게 한다.
        targets = with_context(segments)
        if self._screener and len(segments) > SCREEN_MIN_SEGMENTS:
            on_progress(f"구간이 {len(segments)}개로 많아, 교리를 다루는 발언을 먼저 고르는 중입니다.")
            targets = [targets[i] for i in self._screen(segments, on_progress)]
            if not targets:
                on_progress(NOTHING_TO_ANALYZE)
                return AnalysisResult(verdict=Verdict.SAFE, score=0, summary=NOTHING_TO_ANALYZE, findings=[])
            on_progress(f"교리와 관련 있어 보이는 구간 {len(targets)}개를 골랐습니다.")
        on_progress(f"구간 {len(targets)}개를 앞뒤 문맥과 함께 기준 자료에서 찾는 중입니다.")

        system = prompts.system_prompt()
        # 임베딩은 전체를 한 번에 요청해 호출 수를 줄인다. 검색에는 앞뒤 문맥까지 포함한 텍스트를 쓴다.
        embeddings = self._embedder.embed([t.window_text for t in targets], "query")
        starts = range(0, len(targets), SEGMENTS_PER_CALL)
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            futures = [
                pool.submit(
                    self._analyze_batch,
                    system,
                    f"묶음 {number}/{len(starts)}" if len(starts) > 1 else "검색 결과",
                    targets[start : start + SEGMENTS_PER_CALL],
                    embeddings[start : start + SEGMENTS_PER_CALL],
                    on_progress,
                )
                for number, start in enumerate(starts, 1)
            ]
            results = [future.result() for future in futures]  # 구간 순서를 유지한다

        found = [finding for _, batch_findings in results for finding in batch_findings]
        findings = merge_same_speech(found)
        if len(found) > len(findings):
            on_progress(f"자막과 음성에서 함께 적발된 같은 발언 {len(found) - len(findings)}건을 하나로 합쳤습니다.")
        score = max((f.score for f in findings), default=0)
        verdict = verdict_for(score)
        on_progress(f"판별을 마쳤습니다. 의심 발언 {len(findings)}건, 종합 의심 지수 {score}점({VERDICT_LABEL[verdict]}).")
        return AnalysisResult(
            verdict=verdict,
            score=score,
            summary=" ".join(summary for summary, _ in results),
            findings=findings,
        )
