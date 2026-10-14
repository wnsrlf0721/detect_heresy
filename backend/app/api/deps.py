from functools import lru_cache

from app.config import get_settings
from app.db.repository import (
    AnalysisRepository,
    PgAnalysisRepository,
    PgTranscriptRepository,
    TranscriptRepository,
)
from app.media.downloader import YtDlpSource
from app.media.ocr import EasyOcrReader, VisionFrameReader
from app.media.pipeline import TranscriptPipeline
from app.media.stt import OpenAITranscriber, WhisperTranscriber
from app.rag.embedder import VoyageEmbedder
from app.rag.engine import AnalysisEngine
from app.rag.llm import ClaudeAnalyzer, ClaudeVision
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


@lru_cache
def get_pipeline() -> TranscriptPipeline:
    settings = get_settings()
    if settings.stt_backend == "local":
        transcriber = WhisperTranscriber(settings.local_stt_model, settings.local_device)
    else:
        transcriber = OpenAITranscriber(settings.openai_api_key, settings.stt_model)
    if settings.ocr_backend == "local":
        reader = EasyOcrReader(settings.ocr_interval_seconds, settings.local_device)
    else:
        vision = ClaudeVision(settings.anthropic_api_key, settings.ocr_model)
        reader = VisionFrameReader(vision, settings.ocr_interval_seconds)
    return TranscriptPipeline(
        source=YtDlpSource(settings.max_video_seconds), transcriber=transcriber, reader=reader
    )


@lru_cache
def get_transcript_repository() -> TranscriptRepository:
    return PgTranscriptRepository(get_settings().database_url)
