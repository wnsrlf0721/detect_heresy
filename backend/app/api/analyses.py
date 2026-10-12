from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_engine, get_repository
from app.db.repository import AnalysisRepository
from app.errors import AnalysisError
from app.rag.engine import AnalysisEngine
from app.schemas.analysis import AnalysisRequest, AnalysisResponse, JobStatus

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.post("", response_model=AnalysisResponse, status_code=201)
def create_analysis(
    request: AnalysisRequest,
    engine: AnalysisEngine = Depends(get_engine),
    repository: AnalysisRepository = Depends(get_repository),
) -> AnalysisResponse:
    """텍스트 구간을 판별한다. MVP는 동기 처리라 응답의 status 는 done 또는 failed 다."""
    analysis_id = str(uuid4())
    try:
        result = engine.analyze(request.segments)
        response = AnalysisResponse(id=analysis_id, status=JobStatus.DONE, result=result)
    except AnalysisError as e:
        response = AnalysisResponse(id=analysis_id, status=JobStatus.FAILED, error=str(e))
    repository.save(request, response)
    return response


@router.get("/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: str, repository: AnalysisRepository = Depends(get_repository)
) -> AnalysisResponse:
    response = repository.get(analysis_id)
    if response is None:
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    return response
