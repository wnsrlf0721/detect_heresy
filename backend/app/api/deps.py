from functools import lru_cache

from app.config import get_settings
from app.db.repository import (
    AnalysisRepository,
    PgAnalysisRepository,
    PgTranscriptRepository,
    PgVideoRepository,
    TranscriptRepository,
    VideoRepository,
)
from app.media.downloader import YtDlpSource
from app.media.ocr import EasyOcrReader, VisionFrameReader
from app.media.pipeline import TranscriptPipeline
from app.media.stt import OpenAITranscriber, WhisperTranscriber
from app.rag.embedder import VoyageEmbedder
from app.rag.engine import AnalysisEngine
from app.rag.llm import ClaudeAnalyzer, ClaudeScreener, ClaudeTopicWriter, ClaudeVision
from app.rag.store import PgVectorStore
from app.rag.topic import TopicService
from app.rag.version import analysis_version


@lru_cache
def get_embedder() -> VoyageEmbedder:
    settings = get_settings()
    return VoyageEmbedder(settings.voyage_api_key, settings.embedding_model)


@lru_cache
def get_engine() -> AnalysisEngine:
    settings = get_settings()
    return AnalysisEngine(
        embedder=get_embedder(),
        store=PgVectorStore(settings.database_url),
        analyzer=ClaudeAnalyzer(settings.anthropic_api_key, settings.llm_model, settings.llm_effort),
        screener=ClaudeScreener(settings.anthropic_api_key, settings.filter_model),
    )


@lru_cache
def get_topic_service() -> TopicService:
    settings = get_settings()
    return TopicService(ClaudeTopicWriter(settings.anthropic_api_key, settings.topic_model), get_embedder())


def get_analysis_version() -> str:
    # 캐시하지 않는다. 서버를 켠 채 기준 데이터나 프롬프트를 고쳐도 바로 반영되게 한다.
    return analysis_version(get_settings())


def get_related_min_similarity() -> float:
    return get_settings().related_min_similarity


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


@lru_cache
def get_video_repository() -> VideoRepository:
    return PgVideoRepository(get_settings().database_url)

