# 프로젝트: 이단성 분석 서비스
영상/텍스트를 STT·OCR로 추출하고, 정통 신학 DB(RAG)와 비교해 이단성 의심 지표와 근거를 보여주는 웹 서비스.

상세 기획은 docs/PROJECT.md 참고.

## 폴더 구조
- backend/ : FastAPI. AI는 별도 폴더가 아니라 backend/app/rag, backend/app/prompts 모듈이다. 영상 → 텍스트 추출은 backend/app/media 다.
- frontend/ : Next.js. 화면 하나(app/page.tsx)에서 추출과 판별 API를 차례로 부른다. API 타입은 frontend/lib/api.ts 에 있고 백엔드 스키마와 손으로 맞춘다.
- data/ : 기준 데이터 원문. orthodox/(정통 교리), heresy/(이단 사례), eval/(평가셋) YAML
- 스키마는 backend/app/schemas/ 의 Pydantic 모델이 기준이다.
- DB 테이블과 jsonb 칸의 내용은 docs/DATABASE.md 에 정리돼 있다. schema.sql 이나 저장되는 스키마를 바꾸면 함께 고친다.

## 확정된 기술
- LLM: Claude (anthropic SDK, 기본 모델 claude-opus-5-5). 호출부는 backend/app/rag/llm.py 한 곳이다.
- 임베딩: Voyage API (voyage-4, 1024차원). backend/app/rag/embedder.py
- DB: PostgreSQL + pgvector 하나로 벡터 검색과 분석 결과 저장을 모두 처리한다. ORM 없이 psycopg 로 직접 쿼리한다.
- AI 작업은 모두 API로 한다. 영상 추출에서 음성은 OpenAI Whisper API(whisper-1, backend/app/media/stt.py), 화면 글자는 Claude 비전(claude-haiku-5-5, 호출부는 llm.py 의 ClaudeVision, 프롬프트는 prompts/ocr_system.md)이다. 다운로드와 자막은 yt-dlp, 프레임 추출은 OpenCV로 하며 ffmpeg 는 쓰지 않는다.
- 로컬 실행(faster-whisper, EasyOCR)은 GPU를 붙일 때를 위해 남겨 둔 선택 사항이다. `py -m uv sync --extra local` 로 설치하고(venv 를 끈 셸에서) STT_BACKEND / OCR_BACKEND 를 local 로 바꾼다. CPU로는 너무 느려서 기본으로 쓰지 않는다.
- 외부 의존(임베딩, 벡터 저장소, LLM, 저장소, 영상 다운로드, STT, OCR)은 Protocol 로 추상화돼 있고, 테스트는 가짜 구현으로 API 키와 DB 없이 돈다.

## API
- POST /analyses, GET /analyses/{id} : 화면의 텍스트 직접 입력이 쓰는 판별 API. POST 는 pending 으로 바로 응답하고 FastAPI BackgroundTasks 로 처리한다. Celery + Redis 는 아직 쓰지 않는다.
- POST /videos, GET /videos/{id} : 화면의 영상 분석이 쓰는 API. 추출 → 판별 → 대주제 정리를 한 작업으로 처리한다. 같은 영상 ID·출처·판별 버전(app/rag/version.py)이면 저장된 결과를 cached 로 바로 돌려주고, 버전만 다르면 추출한 텍스트를 재사용해 판별만 다시 한다. force 면 추출부터 다시 한다.
- 판별 버전은 data/orthodox·heresy YAML, 판별 프롬프트(prompts.ANALYSIS_PROMPT_FILES), 모델 설정, engine.py 의 ENGINE_REVISION 으로 만든다. 판별 결과가 달라지는 엔진 코드 변경을 하면 ENGINE_REVISION 을 올린다.
- 대주제는 Haiku(llm.py 의 ClaudeTopicWriter, prompts/topic_system.md)가 정리하고 Voyage 로 임베딩해 저장한다. GET 할 때마다 유사도 RELATED_MIN_SIMILARITY 이상인 다른 영상을 related 로 찾는다. 대주제는 화면 연결용이며 판별 근거로 LLM에 넘기지 않는다.
- 작업은 BackgroundTasks(서버 프로세스 안)에서 돌므로, 서버가 뜰 때 pending/running 작업을 모두 failed 로 바꾼다(app.db.fail_interrupted_jobs).
- 판별 엔진 흐름(engine.py): 구간마다 같은 출처의 앞 2개·뒤 1개 구간을 문맥으로 붙인다(rag/context.py) → 구간이 20개를 넘으면 Haiku 가 의심 구간을 먼저 고른다(ClaudeScreener, prompts/filter_system.md. 실패하면 전부 분석) → 문맥 포함 텍스트로 검색 → Opus 판별. 적발은 문맥이 아닌 그 구간의 말만 한다.
- 자막(caption)과 음성(stt)에서 같은 발언이 함께 적발되면 engine.py 의 merge_same_speech 가 점수 높은 쪽 하나만 남긴다.
- 추출 전용 API(/transcripts)는 화면이 쓰지 않아 없앴다. 추출 결과는 영상 분석 응답의 transcript 로 나간다.
- DB 저장(app/db/repository.py 의 PgRepository 하나): videos ─ transcripts ─ segments, transcripts ─ analyses ─ findings ─ finding_refs ─ chunks 로 나눠 저장하고, API 응답은 읽을 때 조립한다. 영상 분석과 텍스트 판별이 같은 analyses 테이블을 쓴다(텍스트는 video_id 가 없다). 대주제는 추출 결과(transcripts)마다 한 번 정리한다.
- 적발(Finding)은 판별에 넘긴 구간 번호(segment_index, 응답에서는 빠짐)로 segments 를 가리킨다. 적발의 시각·출처는 그 구간의 값이다.
- chunks 는 finding_refs 가 가리키므로 지우지 않는다. ingest 는 같은 id 를 갱신하고 data/ 에서 빠진 것은 active=false 로 검색에서 뺀다.
- schema.sql 은 CREATE IF NOT EXISTS 뿐이고 마이그레이션 도구가 없다. 테이블 구조를 바꾸면 개발 DB 의 테이블을 지우고 다시 만든 뒤 ingest 를 다시 한다.
- Voyage 는 결제 수단 없는 계정이라 분당 3회·1만 토큰 제한이다. embedder.py 가 요청을 글자 수(MAX_BATCH_CHARS)로 나누고 429 면 기다렸다 재시도한다.
- 구간의 source(user/stt/ocr/caption)와 time 은 요청부터 결과의 적발 문장까지 그대로 유지한다.
- LLM에게는 판단만 맡긴다. 시간, 출처, 근거 문서, 종합 점수와 등급은 코드(backend/app/rag/engine.py)가 채운다.
- 등급 기준(30 이상 주의, 70 이상 위험)은 engine.py 와 prompts/analyze_system.md 양쪽에 있으니 함께 바꾼다.

## 명령어 (backend/ 에서 실행)
- uv 는 가상환경(backend/.venv)을 만들고 패키지를 설치할 때만 쓴다. 앱 실행에는 필요 없다. uv 는 venv 가 아니라 사용자 Python 에 `pip install --user` 로 설치돼 있어 `uv` 명령이 PATH 에 없고, venv 안에도 없다.
- 패키지 설치: py -m uv sync (venv 를 끈 셸에서. pyproject.toml / uv.lock 이 바뀌었을 때만. 명령에 없는 extra 패키지는 지우므로 local extra 를 쓰면 --extra local 을 붙인다)
- 아래 명령은 venv 에서 실행한다. 사람은 `.venv\Scripts\Activate.ps1` 로 venv 를 켜고 `python -m pytest` 처럼 실행한다. Claude 의 셸은 명령마다 새로 열리므로 `.venv/Scripts/python.exe -m <모듈>` 로 venv 의 python 을 직접 부른다.
- DB 실행: docker compose up -d db (저장소 루트에서)
- 기준 데이터 적재: python -m scripts.ingest
- 서버 실행: python -m uvicorn app.main:app --reload
- 테스트: python -m pytest (test_pg.py 는 DB가 떠 있을 때만 실행되고 아니면 건너뛴다)
- 데이터 검증: python -m scripts.validate_data
- 평가: python -m scripts.evaluate (문장마다 LLM을 호출하므로 비용이 든다)
- 프론트 실행: npm run dev (frontend/ 에서, http://localhost:3000)

## 기준 데이터 규칙
- 레코드 하나(조항·사례)가 청크 하나다.
- 이단 사례는 claim + keywords 만 임베딩하고, intent / refutation 은 metadata 로 보관한다.
- 사람이 원출처와 대조하기 전까지 verified: false 로 둔다. AI가 임의로 true 로 바꾸지 않는다.

## 규칙
- 현재 단계: 텍스트 판별, 유튜브 영상 추출, 결과 화면, 영상 분석 저장·재사용, 대주제 연결, 1차 선별(Haiku)까지 연결된 상태다. 워커 큐, 이미지 업로드 OCR, 과거 분석 목록, 피드백 기능은 아직 없다.
- LLM 응답은 반드시 JSON 스키마로 검증한다.
- 프롬프트는 app/prompts/ 아래 별도 파일로 분리한다.
- API 키는 .env로만 관리하고 커밋하지 않는다.
- 새 기능에는 pytest 테스트를 함께 작성한다.
- 커밋 메시지는 docs/COMMIT_CONVENTION.md 의 형식(`타입(범위): 요약`)을 따른다.

## 프로젝트 개요

유튜브 영상 URL이나 미디어를 입력받아 음성(STT)과 화면 텍스트(OCR)를 추출하고, 정통 개신교 신학 자료 및 이단 교리 사례를 담은 Vector DB와 RAG로 비교해 이단 의심 점수와 판별 근거를 보여주는 웹 서비스.

핵심 제품 원칙: 단순히 "이단이다"라고 판정하지 않는다. 어떤 문장이 왜 정통 교리에 위배되는지 근거(적발 문장, 정통 교리의 반증, 해당 이단의 원래 의도)를 반드시 함께 제시한다.

## 계획된 아키텍처

모델을 직접 학습시키지 않고 Pre-trained AI API + RAG로 구성한다. 두 개의 파이프라인이 있다.

1. **데이터 수집 파이프라인**: URL 입력 → 영상/음원 다운로드(`yt-dlp`) → STT(Whisper, 타임스탬프 포함) + 프레임 샘플링 후 OCR → 정형화된 스크립트
2. **판별 엔진**: 스크립트를 문단 단위로 분할 → Vector DB에서 관련 정통 교리/이단 사례 검색 → LLM이 비교 분석 → JSON 결과(의심 점수, 적발 문장, 비교 분석 근거)

영상 분석은 오래 걸리므로 API 요청에서 동기 처리하지 않고 워커 큐(Celery + Redis)에서 비동기 작업으로 처리한다.

STT 결과의 표준 형태:

```json
[{ "time": "02:15", "text": "..." }]
```

타임스탬프는 프론트엔드 타임라인 뷰어(의심 발언 구간 하이라이트)까지 끝까지 유지되어야 한다.

### 기술 스택

| 작업 단위 | 기술 |
| --- | --- |
| Frontend | React / Next.js |
| Backend | Python (FastAPI) |
| 비동기 큐 | Celery + Redis |
| STT | OpenAI Whisper API (또는 오픈소스 Whisper) |
| OCR | Google Cloud Vision / EasyOCR |
| Vector DB | Pinecone / Chroma / Milvus |
| LLM | 미정 |
| 패키지 관리 | uv |


## 구현 순서와 범위

- **기준 데이터가 먼저다.** 정통 신학 자료(주요 교단 신앙고백서, 사도신경 해설, 조직신학)와 이단 교리/반증 자료를 청크로 나눠 임베딩해 Vector DB에 적재하는 것이 1단계이며, 판별 품질은 이 데이터에 달려 있다.
- **MVP는 영상 파이프라인을 포함하지 않는다.** 사용자가 올린 텍스트 문장이나 자막 스크린샷 이미지를 RAG로 판별하는 기능부터 만든다. 영상 다운로드/STT/비동기 처리는 그 이후 단계다.
- **비용 최적화 설계**: 영상 전체를 LLM에 보내지 않는다. 1차 키워드 필터링(정규식 또는 가벼운 오픈소스 모델)으로 의심 구간만 추려 LLM RAG로 정밀 분석한다.
- **피드백 루프**: 판별 결과에 대해 사용자가 맞다/틀리다를 피드백하고, 이를 프롬프트와 DB 보정에 활용하는 기능이 고도화 단계에 계획되어 있다.

## 결과 화면 요구사항

- 종합 의심 지수: 안전 / 주의 / 위험 (퍼센트 게이지)
- 타임라인 뷰어: 의심 발언이 나온 시점 하이라이트
- 교리 비교: 영상 속 발언 ↔ 정통 기독교의 반증 ↔ 이단의 원래 의도, 3단 비교
