from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analyses, transcripts
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(get_settings().database_url)
    yield


app = FastAPI(title="이단성 분석 서비스", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analyses.router)
app.include_router(transcripts.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
