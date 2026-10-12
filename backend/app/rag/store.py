import json
import math
from typing import Protocol

import psycopg

from app.schemas.reference import Chunk


class VectorStore(Protocol):
    def replace_all(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def search(self, embedding: list[float], kind: str, k: int) -> list[Chunk]: ...

    def get(self, ids: list[str]) -> list[Chunk]: ...


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class PgVectorStore:
    def __init__(self, database_url: str):
        self._url = database_url

    def replace_all(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        with psycopg.connect(self._url) as conn:
            conn.execute("DELETE FROM chunks")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (id, kind, text, metadata, embedding)"
                    " VALUES (%s, %s, %s, %s::jsonb, %s::vector)",
                    [
                        (c.id, c.kind, c.text, json.dumps(c.metadata, ensure_ascii=False), _vector_literal(e))
                        for c, e in zip(chunks, embeddings, strict=True)
                    ],
                )

    def search(self, embedding: list[float], kind: str, k: int) -> list[Chunk]:
        with psycopg.connect(self._url) as conn:
            rows = conn.execute(
                "SELECT id, kind, text, metadata FROM chunks WHERE kind = %s"
                " ORDER BY embedding <=> %s::vector LIMIT %s",
                (kind, _vector_literal(embedding), k),
            ).fetchall()
        return [Chunk(id=r[0], kind=r[1], text=r[2], metadata=r[3]) for r in rows]

    def get(self, ids: list[str]) -> list[Chunk]:
        if not ids:
            return []
        with psycopg.connect(self._url) as conn:
            rows = conn.execute(
                "SELECT id, kind, text, metadata FROM chunks WHERE id = ANY(%s)", (ids,)
            ).fetchall()
        return [Chunk(id=r[0], kind=r[1], text=r[2], metadata=r[3]) for r in rows]


class InMemoryVectorStore:
    """테스트와 DB 없이 돌려 보는 용도."""

    def __init__(self):
        self._items: dict[str, tuple[Chunk, list[float]]] = {}

    def replace_all(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._items = {c.id: (c, e) for c, e in zip(chunks, embeddings, strict=True)}

    def search(self, embedding: list[float], kind: str, k: int) -> list[Chunk]:
        candidates = [(c, e) for c, e in self._items.values() if c.kind == kind]
        candidates.sort(key=lambda item: _cosine_distance(embedding, item[1]))
        return [c for c, _ in candidates[:k]]

    def get(self, ids: list[str]) -> list[Chunk]:
        return [self._items[i][0] for i in ids if i in self._items]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1 - dot / norm if norm else 1.0
