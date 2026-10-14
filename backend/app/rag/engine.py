"""판별 엔진: 구간 → 관련 기준 데이터 검색 → LLM 비교 분석 → 결과 조립."""

from concurrent.futures import ThreadPoolExecutor

from app import prompts
from app.rag.embedder import Embedder
from app.rag.llm import Analyzer
from app.rag.store import VectorStore
from app.schemas.analysis import AnalysisResult, Finding, Reference, Segment
from app.schemas.llm import LLMFinding
from app.schemas.reference import Chunk, Verdict

# app/prompts/analyze_system.md 의 점수 기준과 같은 값이어야 한다.
CAUTION_MIN = 30
DANGER_MIN = 70

TOP_K_PER_KIND = 3
SEGMENTS_PER_CALL = 20
# 긴 영상은 배치가 여러 개라, LLM 호출을 이만큼씩 동시에 보낸다.
MAX_PARALLEL_CALLS = 4


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


class AnalysisEngine:
    def __init__(self, embedder: Embedder, store: VectorStore, analyzer: Analyzer):
        self._embedder = embedder
        self._store = store
        self._analyzer = analyzer

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

    def _to_finding(self, raw: LLMFinding, segments: list[Segment], refs: dict[str, Chunk]) -> Finding | None:
        if raw.score < CAUTION_MIN or not 0 <= raw.segment_index < len(segments):
            return None
        segment = segments[raw.segment_index]
        return Finding(
            time=segment.time,
            source=segment.source,
            # 구간에 없는 문장을 인용했다면 구간 원문으로 대체한다.
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
        self, system: str, batch: list[Segment], embeddings: list[list[float]]
    ) -> tuple[str, list[Finding]]:
        refs = self._retrieve(embeddings)
        user = prompts.user_prompt(list(enumerate(batch)), list(refs.values()))
        output = self._analyzer.analyze(system, user)
        findings = [f for raw in output.findings if (f := self._to_finding(raw, batch, refs))]
        return output.summary, findings

    def analyze(self, segments: list[Segment]) -> AnalysisResult:
        system = prompts.system_prompt()
        # 임베딩은 전체를 한 번에 요청해 호출 수를 줄인다.
        embeddings = self._embedder.embed([s.text for s in segments], "query")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
            futures = [
                pool.submit(
                    self._analyze_batch,
                    system,
                    segments[start : start + SEGMENTS_PER_CALL],
                    embeddings[start : start + SEGMENTS_PER_CALL],
                )
                for start in range(0, len(segments), SEGMENTS_PER_CALL)
            ]
            results = [future.result() for future in futures]  # 구간 순서를 유지한다

        findings = [finding for _, batch_findings in results for finding in batch_findings]
        score = max((f.score for f in findings), default=0)
        return AnalysisResult(
            verdict=verdict_for(score),
            score=score,
            summary=" ".join(summary for summary, _ in results),
            findings=findings,
        )
