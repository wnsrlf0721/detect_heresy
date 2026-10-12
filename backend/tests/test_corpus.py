import pytest

from app.rag.corpus import build_chunks, load_corpus, load_eval_cases
from app.schemas.reference import Verdict


def test_corpus_loads_and_refs_resolve():
    corpus = load_corpus()
    assert corpus.orthodox
    assert corpus.heresy
    assert all(case.orthodox_refs for case in corpus.heresy)


def test_chunks_cover_every_record():
    corpus = load_corpus()
    chunks = build_chunks(corpus)
    assert len(chunks) == len(corpus.orthodox) + len(corpus.heresy)
    assert len({c.id for c in chunks}) == len(chunks)


def test_heresy_chunk_text_excludes_refutation():
    corpus = load_corpus()
    case = corpus.heresy[0]
    chunk = next(c for c in build_chunks(corpus) if c.id == case.id)
    assert case.claim in chunk.text
    assert case.refutation not in chunk.text
    assert chunk.metadata["refutation"] == case.refutation


def test_eval_set_covers_all_verdicts():
    cases = load_eval_cases()
    assert {c.expected_verdict for c in cases} == set(Verdict)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


ORTHODOX = """
- id: o1
  source: 문서
  section: "1"
  topic: trinity
  text: 본문
"""

HERESY = """
- id: {id}
  group: 단체
  topic: trinity
  claim: 주장
  intent: 의도
  refutation: 반증
  orthodox_refs: [{ref}]
"""


def test_unknown_orthodox_ref_is_rejected(tmp_path):
    _write(tmp_path / "orthodox" / "a.yaml", ORTHODOX)
    _write(tmp_path / "heresy" / "a.yaml", HERESY.format(id="h1", ref="없는-id"))
    with pytest.raises(ValueError, match="orthodox_refs"):
        load_corpus(tmp_path)


def test_duplicate_id_is_rejected(tmp_path):
    _write(tmp_path / "orthodox" / "a.yaml", ORTHODOX)
    _write(tmp_path / "heresy" / "a.yaml", HERESY.format(id="o1", ref="o1"))
    with pytest.raises(ValueError, match="중복"):
        load_corpus(tmp_path)


def test_unknown_field_is_rejected(tmp_path):
    _write(tmp_path / "orthodox" / "a.yaml", ORTHODOX + "  오타필드: 값\n")
    _write(tmp_path / "heresy" / "a.yaml", "[]")
    with pytest.raises(ValueError, match="a.yaml"):
        load_corpus(tmp_path)
