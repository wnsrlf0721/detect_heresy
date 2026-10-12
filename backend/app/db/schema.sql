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
