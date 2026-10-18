CREATE EXTENSION IF NOT EXISTS vector;

-- 기준 데이터 청크. vector 차원은 임베딩 모델(config.embedding_model)과 맞아야 한다.
-- 적발의 근거(finding_refs)가 가리키므로 지우지 않는다. data/ 에서 빠진 레코드는 active 를 끄고 검색에서 뺀다.
CREATE TABLE IF NOT EXISTS chunks (
    id        text PRIMARY KEY,
    kind      text NOT NULL,
    text      text NOT NULL,
    metadata  jsonb NOT NULL,
    embedding vector(1024) NOT NULL,
    active    boolean NOT NULL DEFAULT true
);

-- 분석한 유튜브 영상. 주소 형태가 달라도 영상 ID 하나로 묶는다.
CREATE TABLE IF NOT EXISTS videos (
    video_id   text PRIMARY KEY,
    url        text NOT NULL,           -- 처음 입력한 주소
    title      text,                    -- 추출이 끝나면 채운다
    duration   integer,                 -- 초
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 추출 1회. 영상이면 자막·음성·화면 글자를 모두 추출한 결과이고, 직접 입력한 텍스트면 video_id 가 없다.
-- 같은 추출 결과를 출처나 판별 버전만 바꿔 여러 번 판별할 수 있다.
CREATE TABLE IF NOT EXISTS transcripts (
    id              uuid PRIMARY KEY,
    video_id        text REFERENCES videos (video_id),
    warnings        text[] NOT NULL DEFAULT '{}',   -- 일부 출처를 추출하지 못한 이유
    topic_title     text,                           -- 대주제. 영상만 있고, 정리에 실패하면 비어 있다
    topic_summary   text,
    topic_keywords  text[],
    topic_embedding vector(1024),                   -- 비슷한 주제의 영상을 찾는 데 쓴다
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS transcripts_video ON transcripts (video_id, created_at DESC);

-- 추출 결과의 구간 하나.
CREATE TABLE IF NOT EXISTS segments (
    id            bigserial PRIMARY KEY,
    transcript_id uuid NOT NULL REFERENCES transcripts (id) ON DELETE CASCADE,
    position      integer NOT NULL,     -- 추출 결과 안의 순서. 출처별로 시간순이다
    source        text NOT NULL,        -- caption / stt / ocr / user
    time          text,                 -- "02:15". 직접 입력한 텍스트는 없다
    text          text NOT NULL,
    UNIQUE (transcript_id, position)
);

-- 판별 1회(작업). 영상 분석과 텍스트 판별이 함께 쓴다.
-- 영상 분석은 추출이 끝나기 전까지 transcript_id 가 비어 있어서, 진행 중인 같은 분석을 찾도록 video_id 를 따로 둔다.
CREATE TABLE IF NOT EXISTS analyses (
    id            uuid PRIMARY KEY,
    video_id      text REFERENCES videos (video_id),            -- 텍스트 판별이면 없다
    transcript_id uuid REFERENCES transcripts (id),
    sources       text[] NOT NULL,      -- 판별에 쓴 출처. 정렬된 값 (예: {caption,ocr,stt})
    version       text NOT NULL,        -- app/rag/version.py 의 판별 버전
    status        text NOT NULL,        -- pending / running / done / failed
    progress      text,                 -- 진행 중인 단계 (화면 표시용)
    error         text,
    verdict       text,                 -- safe / caution / danger. 판별이 끝나면 채운다
    score         integer,              -- 종합 의심 지수 0~100
    summary       text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analyses_lookup ON analyses (video_id, version, created_at DESC);

-- 적발된 발언 하나. 시각과 출처는 가리키는 구간(segments)의 값이다.
CREATE TABLE IF NOT EXISTS findings (
    id                  bigserial PRIMARY KEY,
    analysis_id         uuid NOT NULL REFERENCES analyses (id) ON DELETE CASCADE,
    position            integer NOT NULL,   -- 판별 결과 안의 순서
    segment_id          bigint NOT NULL REFERENCES segments (id),
    quote               text NOT NULL,      -- 적발된 발언 원문
    score               integer NOT NULL,
    group_name          text,               -- 비슷한 교리를 가르치는 단체
    topic               text,               -- 교리 분야 (christology 등)
    reason              text NOT NULL,
    orthodox_refutation text NOT NULL,
    heresy_intent       text,
    scripture           text[] NOT NULL DEFAULT '{}',
    UNIQUE (analysis_id, position)
);

-- 적발의 근거로 쓴 기준 데이터.
CREATE TABLE IF NOT EXISTS finding_refs (
    finding_id bigint NOT NULL REFERENCES findings (id) ON DELETE CASCADE,
    position   integer NOT NULL,
    chunk_id   text NOT NULL REFERENCES chunks (id),
    PRIMARY KEY (finding_id, position)
);
CREATE INDEX IF NOT EXISTS finding_refs_chunk ON finding_refs (chunk_id);
