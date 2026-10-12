"""평가셋을 판별 엔진에 돌려 정답과 비교한다. 문장마다 LLM을 한 번씩 호출하므로 비용이 든다.

실행: uv run python -m scripts.evaluate
"""

from collections import Counter

from app.api.deps import get_engine
from app.errors import AnalysisError
from app.rag.corpus import load_eval_cases
from app.schemas.analysis import Segment


def main() -> None:
    engine = get_engine()
    cases = load_eval_cases()
    correct = 0
    group_total = group_correct = 0
    confusion: Counter[tuple[str, str]] = Counter()

    for case in cases:
        try:
            result = engine.analyze([Segment(text=case.text)])
        except AnalysisError as e:
            print(f"[오류] {case.id}: {e}")
            confusion[(case.expected_verdict.value, "error")] += 1
            continue

        ok = result.verdict == case.expected_verdict
        correct += ok
        confusion[(case.expected_verdict.value, result.verdict.value)] += 1
        groups = {f.group for f in result.findings}
        if case.expected_group:
            group_total += 1
            group_correct += case.expected_group in groups
        print(
            f"[{'정답' if ok else '오답'}] {case.id}: 기대 {case.expected_verdict.value}"
            f" / 결과 {result.verdict.value} ({result.score}) {sorted(g for g in groups if g)}"
        )

    print(f"\n등급 정확도: {correct}/{len(cases)}")
    if group_total:
        print(f"단체 식별: {group_correct}/{group_total}")
    print("기대 → 결과")
    for (expected, actual), count in sorted(confusion.items()):
        print(f"  {expected} → {actual}: {count}")


if __name__ == "__main__":
    main()
