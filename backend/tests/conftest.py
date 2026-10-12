import zlib

import pytest

from app.rag.corpus import build_chunks, load_corpus
from app.rag.store import InMemoryVectorStore
from app.schemas.llm import LLMAnalysis, LLMFinding

DIM = 256


class HashEmbedder:
    """외부 API 없이 쓰는 결정적 임베딩. 글자 2-gram 을 해시해 겹치는 표현이 많을수록 가깝게 만든다."""

    def embed(self, texts, input_type):
        vectors = []
        for text in texts:
            vector = [0.0] * DIM
            for i in range(len(text) - 1):
                vector[zlib.crc32(text[i : i + 2].encode()) % DIM] += 1.0
            vectors.append(vector)
        return vectors


class FakeAnalyzer:
    def __init__(self, output: LLMAnalysis | Exception):
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def analyze(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def llm_finding(**overrides) -> LLMFinding:
    values = dict(
        segment_index=0,
        quote="발언",
        score=80,
        group="신천지",
        topic="christology",
        reason="이유",
        orthodox_refutation="반증",
        heresy_intent="의도",
        scripture=["요 14:26"],
        reference_ids=[],
    )
    return LLMFinding(**(values | overrides))


@pytest.fixture
def embedder():
    return HashEmbedder()


@pytest.fixture
def store(embedder):
    chunks = build_chunks(load_corpus())
    store = InMemoryVectorStore()
    store.replace_all(chunks, embedder.embed([c.text for c in chunks], "document"))
    return store
