import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analyses, videos
from app.config import get_settings
from app.db import fail_interrupted_jobs, init_db

logger = logging.getLogger("uvicorn.error").getChild(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = get_settings().database_url
    init_db(database_url)
    interrupted = fail_interrupted_jobs(database_url)
    logger.info("database.ready interrupted_jobs=%d", interrupted)
    yield


app = FastAPI(title="이단성 분석 서비스", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analyses.router)
app.include_router(videos.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
