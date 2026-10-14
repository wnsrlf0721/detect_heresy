from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import get_pipeline, get_transcript_repository
from app.db.repository import TranscriptRepository
from app.errors import AnalysisError
from app.media.pipeline import TranscriptPipeline
from app.schemas.analysis import JobStatus
from app.schemas.transcript import TranscriptRequest, TranscriptResponse

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def run_transcript(
    transcript_id: str, url: str, pipeline: TranscriptPipeline, repository: TranscriptRepository
) -> None:
    def on_progress(stage: str) -> None:
        repository.update(TranscriptResponse(id=transcript_id, status=JobStatus.RUNNING, progress=stage))

    try:
        result = pipeline.run(url, on_progress)
        response = TranscriptResponse(id=transcript_id, status=JobStatus.DONE, result=result)
    except AnalysisError as e:
        response = TranscriptResponse(id=transcript_id, status=JobStatus.FAILED, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        response = TranscriptResponse(
            id=transcript_id, status=JobStatus.FAILED, error=f"텍스트 추출 중 오류가 났습니다: {e}"
        )
    repository.update(response)


@router.post("", response_model=TranscriptResponse, status_code=202)
def create_transcript(
    request: TranscriptRequest,
    background: BackgroundTasks,
    pipeline: TranscriptPipeline = Depends(get_pipeline),
    repository: TranscriptRepository = Depends(get_transcript_repository),
) -> TranscriptResponse:
    """영상에서 텍스트를 추출한다. 오래 걸리므로 pending 으로 바로 응답하고 뒤에서 처리한다."""
    response = TranscriptResponse(id=str(uuid4()), status=JobStatus.PENDING)
    repository.create(request.url, response)
    background.add_task(run_transcript, response.id, request.url, pipeline, repository)
    return response


@router.get("/{transcript_id}", response_model=TranscriptResponse)
def get_transcript(
    transcript_id: str, repository: TranscriptRepository = Depends(get_transcript_repository)
) -> TranscriptResponse:
    response = repository.get(transcript_id)
    if response is None:
        raise HTTPException(status_code=404, detail="추출 결과를 찾을 수 없습니다.")
    return response
