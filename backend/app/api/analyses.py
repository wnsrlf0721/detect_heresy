import logging
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import get_analysis_version, get_engine, get_repository
from app.db.repository import Repository
from app.errors import AnalysisError
from app.rag.engine import AnalysisEngine
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, JobStatus, Segment
from app.timing import measure, run_timed_job

router = APIRouter(prefix="/analyses", tags=["analyses"])
logger = logging.getLogger("uvicorn.error").getChild(__name__)


def run_analysis(
    analysis_id: str, segments: list[Segment], segment_ids: list[int], engine: AnalysisEngine, repository: Repository
) -> bool:
    def log(text: str) -> None:
        with measure("db_progress"):
            repository.add_log(analysis_id, text)

    started = monotonic()
    stage = "start"
    try:
        with measure("db_status"):
            repository.set_status(analysis_id, JobStatus.RUNNING)
        stage = "analyze"
        logger.info("text_analysis.started analysis_id=%s segments=%d", analysis_id, len(segments))
        with measure("verdict"):
            result = engine.analyze(segments, log)
        stage = "save_result"
        with measure("db_write_result"):
            repository.save_result(analysis_id, result, segment_ids)
        stage = "mark_done"
        with measure("db_status"):
            repository.set_status(analysis_id, JobStatus.DONE)
        logger.info(
            "text_analysis.result_saved analysis_id=%s verdict=%s score=%d findings=%d elapsed_s=%.2f",
            analysis_id, result.verdict.value, result.score, len(result.findings), monotonic() - started,
        )
        return True
    except AnalysisError as e:
        logger.warning("text_analysis.failed analysis_id=%s stage=%s error=%s", analysis_id, stage, type(e).__name__)
        with measure("db_status"):
            repository.set_status(analysis_id, JobStatus.FAILED, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        logger.error("text_analysis.failed analysis_id=%s stage=%s error=%s", analysis_id, stage, type(e).__name__)
        with measure("db_status"):
            repository.set_status(analysis_id, JobStatus.FAILED, error=f"판별 중 오류가 났습니다: {e}")
    return False


@router.post("", response_model=AnalysisResponse, status_code=202)
def create_analysis(
    request: AnalysisRequest,
    background: BackgroundTasks,
    version: str = Depends(get_analysis_version),
    engine: AnalysisEngine = Depends(get_engine),
    repository: Repository = Depends(get_repository),
) -> AnalysisResponse:
    """텍스트 구간을 판별한다. 긴 입력은 오래 걸리므로 pending 으로 바로 응답하고 뒤에서 처리한다."""
    response = AnalysisResponse(id=str(uuid4()), status=JobStatus.PENDING)
    segment_ids = repository.create_text_analysis(response.id, request.segments, version)
    logger.info("text_analysis.job_saved analysis_id=%s segments=%d", response.id, len(segment_ids))
    background.add_task(
        run_timed_job, "text", response.id, run_analysis, response.id, request.segments, segment_ids, engine, repository
    )
    return response


@router.get("/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str, repository: Repository = Depends(get_repository)) -> AnalysisResponse:
    response = repository.get_text_analysis(analysis_id)
    if response is None:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    return response
