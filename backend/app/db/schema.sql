CREATE EXTENSION IF NOT EXISTS vector;

-- 기준 데이터 청크. vector 차원은 임베딩 모델(config.embedding_model)과 맞아야 한다.
CREATE TABLE IF NOT EXISTS chunks (
    id        text PRIMARY KEY,
    kind      text NOT NULL,
    text      text NOT NULL,
    metadata  jsonb NOT NULL,
    embedding vector(1024) NOT NULL
);

-- 판별 작업. 요청과 결과는 API 스키마 그대로 jsonb 로 보관한다.
CREATE TABLE IF NOT EXISTS analyses (
    id         uuid PRIMARY KEY,
    status     text NOT NULL,
    request    jsonb NOT NULL,
    result     jsonb,
    error      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 영상 → 텍스트 추출 작업. 결과는 API 스키마 그대로 jsonb 로 보관한다.
CREATE TABLE IF NOT EXISTS transcripts (
    id         uuid PRIMARY KEY,
    status     text NOT NULL,
    url        text NOT NULL,
    progress   text,
    result     jsonb,
    error      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 영상 분석 작업(추출 → 판별 → 대주제). 같은 영상·출처·판별 버전이면 저장된 결과를 다시 쓴다.
CREATE TABLE IF NOT EXISTS video_analyses (
    id              uuid PRIMARY KEY,
    video_id        text NOT NULL,      -- 유튜브 영상 ID. 주소 형태가 달라도 같은 영상을 묶는다.
    url             text NOT NULL,
    sources         text NOT NULL,      -- 판별에 쓴 출처. 정렬해 쉼표로 이은 값 (예: caption,ocr,stt)
    version         text NOT NULL,      -- app/rag/version.py 의 판별 버전
    status          text NOT NULL,
    progress        text,
    transcript      jsonb,
    result          jsonb,
    topic           jsonb,
    topic_embedding vector(1024),       -- 대주제 임베딩. 비슷한 주제의 영상을 찾는 데 쓴다.
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS video_analyses_lookup ON video_analyses (video_id, sources, version, created_at DESC);
