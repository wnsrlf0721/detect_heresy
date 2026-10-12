"""기준 데이터와 평가셋을 검증하고 현황을 출력한다.

실행: uv run python -m scripts.validate_data
"""

from collections import Counter

from app.rag.corpus import build_chunks, load_corpus, load_eval_cases


def main() -> None:
    corpus = load_corpus()
    eval_cases = load_eval_cases()
    chunks = build_chunks(corpus)

    print(f"정통 교리 조항: {len(corpus.orthodox)}")
    for source, count in Counter(d.source for d in corpus.orthodox).items():
        print(f"  - {source}: {count}")
    print(f"이단 사례: {len(corpus.heresy)}")
    for group, count in Counter(c.group for c in corpus.heresy).items():
        print(f"  - {group}: {count}")
    print(f"청크: {len(chunks)}")

    print(f"평가 문장: {len(eval_cases)}")
    for verdict, count in Counter(c.expected_verdict.value for c in eval_cases).items():
        print(f"  - {verdict}: {count}")

    unverified = [r.id for r in corpus.orthodox + corpus.heresy if not r.verified]
    print(f"미검수(verified: false): {len(unverified)}")
    for record_id in unverified:
        print(f"  - {record_id}")


if __name__ == "__main__":
    main()
