from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import get_analysis_version, get_engine, get_repository
from app.db.repository import Repository
from app.errors import AnalysisError
from app.rag.engine import AnalysisEngine
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, JobStatus, Segment

router = APIRouter(prefix="/analyses", tags=["analyses"])


def run_analysis(
    analysis_id: str, segments: list[Segment], segment_ids: list[int], engine: AnalysisEngine, repository: Repository
) -> None:
    repository.set_status(analysis_id, JobStatus.RUNNING)
    try:
        repository.save_result(analysis_id, engine.analyze(segments), segment_ids)
        repository.set_status(analysis_id, JobStatus.DONE)
    except AnalysisError as e:
        repository.set_status(analysis_id, JobStatus.FAILED, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        repository.set_status(analysis_id, JobStatus.FAILED, error=f"판별 중 오류가 났습니다: {e}")


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
    background.add_task(run_analysis, response.id, request.segments, segment_ids, engine, repository)
    return response


@router.get("/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str, repository: Repository = Depends(get_repository)) -> AnalysisResponse:
    response = repository.get_text_analysis(analysis_id)
    if response is None:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    return response
