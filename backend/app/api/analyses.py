from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import get_engine, get_repository
from app.db.repository import AnalysisRepository
from app.errors import AnalysisError
from app.rag.engine import AnalysisEngine
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, JobStatus, Segment

router = APIRouter(prefix="/analyses", tags=["analyses"])


def run_analysis(
    analysis_id: str, segments: list[Segment], engine: AnalysisEngine, repository: AnalysisRepository
) -> None:
    repository.update(AnalysisResponse(id=analysis_id, status=JobStatus.RUNNING))
    try:
        result = engine.analyze(segments)
        response = AnalysisResponse(id=analysis_id, status=JobStatus.DONE, result=result)
    except AnalysisError as e:
        response = AnalysisResponse(id=analysis_id, status=JobStatus.FAILED, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        response = AnalysisResponse(id=analysis_id, status=JobStatus.FAILED, error=f"판별 중 오류가 났습니다: {e}")
    repository.update(response)


@router.post("", response_model=AnalysisResponse, status_code=202)
def create_analysis(
    request: AnalysisRequest,
    background: BackgroundTasks,
    engine: AnalysisEngine = Depends(get_engine),
    repository: AnalysisRepository = Depends(get_repository),
) -> AnalysisResponse:
    """텍스트 구간을 판별한다. 긴 영상은 오래 걸리므로 pending 으로 바로 응답하고 뒤에서 처리한다."""
    response = AnalysisResponse(id=str(uuid4()), status=JobStatus.PENDING)
    repository.create(request, response)
    background.add_task(run_analysis, response.id, request.segments, engine, repository)
    return response


@router.get("/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: str, repository: AnalysisRepository = Depends(get_repository)
) -> AnalysisResponse:
    response = repository.get(analysis_id)
    if response is None:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    return response
