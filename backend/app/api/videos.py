from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response

from app.api.deps import (
    get_analysis_version,
    get_engine,
    get_pipeline,
    get_preview_source,
    get_related_min_similarity,
    get_repository,
    get_topic_service,
)
from app.db.repository import Repository, StoredTranscript
from app.errors import AnalysisError
from app.media import youtube_video_id
from app.media.pipeline import TranscriptPipeline
from app.media.preview import PreviewSource, VideoNotFound
from app.rag.engine import AnalysisEngine
from app.rag.topic import TopicService
from app.schemas.analysis import JobStatus, Segment
from app.schemas.transcript import check_youtube_url
from app.schemas.video import VideoPreview, VideoRequest, VideoResponse

router = APIRouter(prefix="/videos", tags=["videos"])

RELATED_LIMIT = 5

SOURCE_LABEL = {"caption": "자막", "stt": "음성", "ocr": "화면 글자"}


def _source_counts(segments: list[Segment]) -> str:
    counts = Counter(s.source for s in segments)
    return ", ".join(f"{label} {counts[source]}구간" for source, label in SOURCE_LABEL.items() if counts[source])


def summarize_topic(saved: StoredTranscript, topics: TopicService, repository: Repository, log) -> None:
    """영상 요약(대주제)은 추출 결과마다 한 번만 정리한다. 비슷한 영상을 잇는 부가 정보라, 실패해도 판별은 그대로 둔다."""
    log("영상 내용을 요약하는 중입니다.")
    try:
        topic, embedding = topics.summarize(saved.result)
    except AnalysisError:
        log("영상 요약을 만들지 못했습니다. 판별은 계속합니다.")
        return
    repository.save_topic(saved.id, topic, embedding)
    log(f"영상 요약을 정리했습니다: {topic.title}")


def run_video(
    job: VideoResponse,
    video_id: str,
    saved: StoredTranscript | None,
    pipeline: TranscriptPipeline,
    engine: AnalysisEngine,
    topics: TopicService,
    repository: Repository,
) -> None:
    """추출(저장된 것이 있으면 재사용) → 요약과 판별을 동시에. 단계마다 저장해 GET 으로 진행 과정을 볼 수 있게 한다."""

    def log(text: str) -> None:
        repository.add_log(job.id, text)

    try:
        repository.set_status(job.id, JobStatus.RUNNING)
        if saved is None:
            saved = repository.save_transcript(job.id, video_id, pipeline.run(job.url, log))
        else:
            repository.use_transcript(job.id, saved.id)
            log(f"이 영상에서 이전에 추출한 텍스트({_source_counts(saved.result.segments)})를 다시 씁니다.")
        log(f"자막·음성·화면 글자에서 겹치는 내용을 합쳐 {len(saved.result.merged)}줄로 정리했습니다.")

        picked = [(s, i) for s, i in zip(saved.result.segments, saved.segment_ids, strict=True) if s.source in job.sources]
        if not picked:
            raise AnalysisError("선택한 출처에서 추출된 텍스트가 없습니다.")
        log(f"판별에는 {_source_counts([s for s, _ in picked])}을 씁니다.")

        # 요약은 판별보다 빨리 끝나므로, 동시에 돌려 판별을 기다리는 동안 화면에 먼저 보여 준다.
        with ThreadPoolExecutor(max_workers=1) as pool:
            summary = pool.submit(summarize_topic, saved, topics, repository, log) if saved.topic is None else None
            result = engine.analyze([s for s, _ in picked], log)
            if summary is not None:
                summary.result()  # 요약 쪽의 예상하지 못한 오류도 작업 실패로 알린다
        repository.save_result(job.id, result, [i for _, i in picked])
        repository.set_status(job.id, JobStatus.DONE)
    except AnalysisError as e:
        repository.set_status(job.id, JobStatus.FAILED, error=str(e))
    except Exception as e:  # 백그라운드 작업이라, 여기서 놓치면 작업이 영영 running 으로 남는다.
        repository.set_status(job.id, JobStatus.FAILED, error=f"영상 분석 중 오류가 났습니다: {e}")


def _with_related(job: VideoResponse, repository: Repository, min_similarity: float) -> VideoResponse:
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
    repository: Repository = Depends(get_repository),
) -> VideoResponse:
    """영상을 분석한다. 같은 영상·출처·판별 버전의 분석이 있으면 바로 돌려주고, 없으면 pending 으로 응답하고 뒤에서 처리한다."""
    video_id = youtube_video_id(request.url)
    if not request.force:
        existing = repository.find_video_analysis(video_id, request.sources, version)
        if existing is not None:
            if existing.status == JobStatus.DONE:
                response.status_code = 200
                return _with_related(existing, repository, min_similarity).model_copy(update={"cached": True})
            return existing  # 같은 분석이 진행 중이면 그 작업을 같이 기다린다.

    # 판별 기준이나 출처만 바뀐 경우에는 내려받기와 음성 인식을 다시 하지 않는다.
    saved = None if request.force else repository.find_transcript(video_id)
    job = VideoResponse(
        id=str(uuid4()),
        status=JobStatus.PENDING,
        url=request.url,
        sources=request.sources,
        created_at=datetime.now(UTC),
    )
    repository.create_video_analysis(job, video_id, version)
    background.add_task(run_video, job, video_id, saved, pipeline, engine, topics, repository)
    return job


# /{job_id} 보다 먼저 등록해야 "preview" 가 작업 ID로 잡히지 않는다.
@router.get("/preview", response_model=VideoPreview)
def preview_video(
    url: str = Query(max_length=500),
    source: PreviewSource = Depends(get_preview_source),
) -> VideoPreview:
    """분석 전에 주소가 맞는 영상인지 확인한다. 화면이 주소를 입력할 때마다 부른다."""
    try:
        check_youtube_url(url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    video_id = youtube_video_id(url)
    if video_id is None:
        raise HTTPException(status_code=422, detail="유튜브 영상 주소에서 영상을 찾지 못했습니다.")
    try:
        return source.lookup(video_id)
    except VideoNotFound as e:
        raise HTTPException(status_code=404, detail="영상이 없거나 비공개 영상입니다.") from e
    except AnalysisError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/{job_id}", response_model=VideoResponse)
def get_video(
    job_id: str,
    min_similarity: float = Depends(get_related_min_similarity),
    repository: Repository = Depends(get_repository),
) -> VideoResponse:
    job = repository.get_video_analysis(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="영상 분석 결과를 찾을 수 없습니다.")
    return _with_related(job, repository, min_similarity)
