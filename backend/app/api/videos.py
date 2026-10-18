from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response

from app.api.deps import (
    get_analysis_version,
    get_engine,
    get_pipeline,
    get_related_min_similarity,
    get_topic_service,
    get_video_repository,
)
from app.db.repository import VideoRepository
from app.errors import AnalysisError
from app.media import youtube_video_id
from app.media.pipeline import TranscriptPipeline
from app.rag.engine import AnalysisEngine
from app.rag.topic import TopicService
from app.schemas.analysis import JobStatus
from app.schemas.transcript import TranscriptResult
from app.schemas.video import VideoRequest, VideoResponse

router = APIRouter(prefix="/videos", tags=["videos"])

RELATED_LIMIT = 5


def run_video(
    job: VideoResponse,
    saved_transcript: TranscriptResult | None,
    pipeline: TranscriptPipeline,
    engine: AnalysisEngine,
    topics: TopicService,
    repository: VideoRepository,
) -> None:
    """추출(저장된 것이 있으면 재사용) → 판별 → 대주제 정리. 단계마다 저장해 GET 으로 진행 상황을 볼 수 있게 한다."""

    def save(**changes) -> None:
        nonlocal job
        job = job.model_copy(update=changes)
        repository.update(job)

    try:
        save(status=JobStatus.RUNNING)
        transcript = saved_transcript or pipeline.run(job.url, lambda stage: save(progress=stage))
        save(transcript=transcript)

        segments = [s for s in transcript.segments if s.source in job.sources]
        if not segments:
            raise AnalysisError("선택한 출처에서 추출된 텍스트가 없습니다.")
        result = engine.analyze(segments, lambda stage: save(progress=stage))

        save(result=result, progress="영상 대주제를 정리하는 중")
        # 대주제는 비슷한 영상을 잇는 부가 정보라, 실패해도 판별 결과는 그대로 저장한다.
        try:
            topic, embedding = topics.summarize(transcript)
        except AnalysisError:
            topic, embedding = None, None
        job = job.model_copy(update={"status": JobStatus.DONE, "progress": None, "topic": topic})
        repository.update(job, embedding)
    except AnalysisError as e:
        save(status=JobStatus.FAILED, progress=None, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        save(status=JobStatus.FAILED, progress=None, error=f"영상 분석 중 오류가 났습니다: {e}")


def _with_related(job: VideoResponse, repository: VideoRepository, min_similarity: float) -> VideoResponse:
    if job.status != JobStatus.DONE:
        return job
    return job.model_copy(update={"related": repository.related(job.id, min_similarity, RELATED_LIMIT)})


@router.post("", response_model=VideoResponse, status_code=202)
def create_video(
    request: VideoRequest,
    background: BackgroundTasks,
    response: Response,
    version: str = Depends(get_analysis_version),
    min_similarity: float = Depends(get_related_min_similarity),
    pipeline: TranscriptPipeline = Depends(get_pipeline),
    engine: AnalysisEngine = Depends(get_engine),
    topics: TopicService = Depends(get_topic_service),
    repository: VideoRepository = Depends(get_video_repository),
) -> VideoResponse:
    """영상을 분석한다. 같은 영상·출처·판별 버전의 분석이 있으면 바로 돌려주고, 없으면 pending 으로 응답하고 뒤에서 처리한다."""
    video_id = youtube_video_id(request.url)
    if not request.force:
        existing = repository.find(video_id, request.sources, version)
        if existing is not None:
            if existing.status == JobStatus.DONE:
                response.status_code = 200
                return _with_related(existing, repository, min_similarity).model_copy(update={"cached": True})
            return existing  # 같은 분석이 진행 중이면 그 작업을 같이 기다린다.

    # 판별 기준만 바뀐 경우에는 내려받기와 음성 인식을 다시 하지 않는다.
    saved_transcript = None if request.force else repository.find_transcript(video_id)
    job = VideoResponse(
        id=str(uuid4()),
        status=JobStatus.PENDING,
        url=request.url,
        sources=request.sources,
        created_at=datetime.now(UTC),
    )
    repository.create(job, video_id, version)
    background.add_task(run_video, job, saved_transcript, pipeline, engine, topics, repository)
    return job


@router.get("/{job_id}", response_model=VideoResponse)
def get_video(
    job_id: str,
    min_similarity: float = Depends(get_related_min_similarity),
    repository: VideoRepository = Depends(get_video_repository),
) -> VideoResponse:
    job = repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="영상 분석 결과를 찾을 수 없습니다.")
    return _with_related(job, repository, min_similarity)
