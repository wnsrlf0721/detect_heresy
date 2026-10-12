from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://heresy:heresy@localhost:5432/heresy"

    # 비워 두면 Anthropic SDK가 환경 변수나 로그인 프로필에서 자격 증명을 찾는다.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "high"

    voyage_api_key: str | None = None
    embedding_model: str = "voyage-4"  # 1024차원. 바꾸면 db/schema.sql 의 vector 차원도 맞춘다.

    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
