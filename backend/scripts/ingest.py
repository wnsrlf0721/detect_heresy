"""기준 데이터를 임베딩해 Vector DB에 적재한다. 기존 청크는 모두 교체된다.

실행: uv run python -m scripts.ingest
"""

from app.config import get_settings
from app.db import init_db
from app.rag.corpus import build_chunks, load_corpus
from app.rag.embedder import VoyageEmbedder
from app.rag.store import PgVectorStore


def main() -> None:
    settings = get_settings()
    chunks = build_chunks(load_corpus())
    embedder = VoyageEmbedder(settings.voyage_api_key, settings.embedding_model)
    embeddings = embedder.embed([c.text for c in chunks], "document")

    init_db(settings.database_url)
    PgVectorStore(settings.database_url).replace_all(chunks, embeddings)
    print(f"청크 {len(chunks)}개 적재 완료 ({settings.embedding_model})")


if __name__ == "__main__":
    main()
