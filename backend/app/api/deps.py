from functools import lru_cache

from app.config import get_settings
from app.db.repository import AnalysisRepository, PgAnalysisRepository
from app.rag.embedder import VoyageEmbedder
from app.rag.engine import AnalysisEngine
from app.rag.llm import ClaudeAnalyzer
from app.rag.store import PgVectorStore


@lru_cache
def get_engine() -> AnalysisEngine:
    settings = get_settings()
    return AnalysisEngine(
        embedder=VoyageEmbedder(settings.voyage_api_key, settings.embedding_model),
        store=PgVectorStore(settings.database_url),
        analyzer=ClaudeAnalyzer(settings.anthropic_api_key, settings.llm_model, settings.llm_effort),
    )


@lru_cache
def get_repository() -> AnalysisRepository:
    return PgAnalysisRepository(get_settings().database_url)
