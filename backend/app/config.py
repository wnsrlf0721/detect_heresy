from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://heresy:heresy@localhost:5432/heresy"

    # 비워 두면 Anthropic SDK가 환경 변수나 로그인 프로필에서 자격 증명을 찾는다.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "high"

    # 긴 영상에서 의심 구간을 먼저 골라내는 1차 선별과 영상 대주제 정리. 판단이 가벼운 작업이라 저렴한 모델을 쓴다.
    filter_model: str = "claude-haiku-5-5"
    topic_model: str = "claude-haiku-5-5"
    # 대주제 임베딩의 코사인 유사도가 이 값 이상인 이전 분석을 '비슷한 주제'로 보여 준다.
    related_min_similarity: float = 0.6

    voyage_api_key: str | None = None
    embedding_model: str = "voyage-4"  # 1024차원. 바꾸면 db/schema.sql 의 vector 차원도 맞춘다.

    # 영상 → 텍스트 추출. 기본은 API이고, GPU가 있는 컴퓨터에서는 backend 를 "local" 로 바꿔 직접 돌릴 수 있다.
    # local 은 `uv sync --extra local` 로 패키지를 설치해야 한다.
    stt_backend: Literal["openai", "local"] = "openai"
    openai_api_key: str | None = None
    stt_model: str = "whisper-1"
    ocr_backend: Literal["claude", "local"] = "claude"
    ocr_model: str = "claude-haiku-5-5"
    local_stt_model: str = "large-v3-turbo"  # faster-whisper 모델 이름
    local_device: str = "cuda"  # local backend 가 쓸 장치 ("cuda" 또는 "cpu")
    ocr_interval_seconds: float = 3.0  # 화면 글자를 읽을 프레임 간격
    max_video_seconds: int = 30 * 60

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
