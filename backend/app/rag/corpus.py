"""기준 데이터와 평가셋을 YAML에서 읽어 검증하고, 임베딩용 청크로 변환한다."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.schemas.reference import Chunk, EvalCase, HeresyCase, OrthodoxDoc

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[3] / "data"))

T = TypeVar("T", bound=BaseModel)


@dataclass
class Corpus:
    orthodox: list[OrthodoxDoc]
    heresy: list[HeresyCase]


def _load_records(directory: Path, model: type[T]) -> list[T]:
    records: list[T] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        try:
            records.extend(TypeAdapter(list[model]).validate_python(raw))
        except ValidationError as e:
            raise ValueError(f"{path.name}: {e}") from e
    return records


def _check_unique(ids: list[str], label: str) -> None:
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{label} id 중복: {duplicates}")


def load_corpus(data_dir: Path = DATA_DIR) -> Corpus:
    orthodox = _load_records(data_dir / "orthodox", OrthodoxDoc)
    heresy = _load_records(data_dir / "heresy", HeresyCase)
    _check_unique([d.id for d in orthodox] + [c.id for c in heresy], "기준 데이터")

    known = {d.id for d in orthodox}
    for case in heresy:
        missing = [ref for ref in case.orthodox_refs if ref not in known]
        if missing:
            raise ValueError(f"{case.id}: 존재하지 않는 orthodox_refs {missing}")
    return Corpus(orthodox=orthodox, heresy=heresy)


def load_eval_cases(data_dir: Path = DATA_DIR) -> list[EvalCase]:
    cases = _load_records(data_dir / "eval", EvalCase)
    _check_unique([c.id for c in cases], "평가셋")
    return cases


def build_chunks(corpus: Corpus) -> list[Chunk]:
    """레코드 하나가 청크 하나다. 조항·사례 단위로 이미 나뉘어 있어 추가 분할은 하지 않는다."""
    chunks = [
        Chunk(
            id=doc.id,
            kind="orthodox",
            text=f"[{doc.source} {doc.section}] {doc.text}",
            metadata=doc.model_dump(mode="json", exclude={"id"}),
        )
        for doc in corpus.orthodox
    ]
    # 이단 사례는 발언과 닮은 부분(주장·키워드)만 임베딩한다.
    # 반증과 의도까지 섞으면 정통 발언이 이단 사례와 가깝게 검색된다.
    chunks += [
        Chunk(
            id=case.id,
            kind="heresy",
            text=f"[{case.group}] {case.claim}\n키워드: {', '.join(case.keywords)}",
            metadata=case.model_dump(mode="json", exclude={"id"}),
        )
        for case in corpus.heresy
    ]
    return chunks
