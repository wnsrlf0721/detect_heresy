# 프로젝트: 이단성 분석 서비스
영상/텍스트를 STT·OCR로 추출하고, 정통 신학 DB(RAG)와 비교해 이단성 의심 지표와 근거를 보여주는 웹 서비스.

상세 기획은 docs/PROJECT.md 참고.

## 폴더 구조
- backend/ : FastAPI. AI는 별도 폴더가 아니라 backend/app/rag, backend/app/prompts 모듈이다. 영상 → 텍스트 추출은 backend/app/media 다.
- frontend/ : Next.js. 화면 하나(app/page.tsx)에서 추출과 판별 API를 차례로 부른다. API 타입은 frontend/lib/api.ts 에 있고 백엔드 스키마와 손으로 맞춘다.
- data/ : 기준 데이터 원문. orthodox/(정통 교리), heresy/(이단 사례), eval/(평가셋) YAML
- 스키마는 backend/app/schemas/ 의 Pydantic 모델이 기준이다.

## 확정된 기술
- LLM: Claude (anthropic SDK, 기본 모델 claude-opus-5-5). 호출부는 backend/app/rag/llm.py 한 곳이다.
- 임베딩: Voyage API (voyage-4, 1024차원). backend/app/rag/embedder.py
- DB: PostgreSQL + pgvector 하나로 벡터 검색과 분석 결과 저장을 모두 처리한다. ORM 없이 psycopg 로 직접 쿼리한다.
- AI 작업은 모두 API로 한다. 영상 추출에서 음성은 OpenAI Whisper API(whisper-1, backend/app/media/stt.py), 화면 글자는 Claude 비전(claude-haiku-5-5, 호출부는 llm.py 의 ClaudeVision, 프롬프트는 prompts/ocr_system.md)이다. 다운로드와 자막은 yt-dlp, 프레임 추출은 OpenCV로 하며 ffmpeg 는 쓰지 않는다.
- 로컬 실행(faster-whisper, EasyOCR)은 GPU를 붙일 때를 위해 남겨 둔 선택 사항이다. `uv sync --extra local` 로 설치하고 STT_BACKEND / OCR_BACKEND 를 local 로 바꾼다. CPU로는 너무 느려서 기본으로 쓰지 않는다.
- 외부 의존(임베딩, 벡터 저장소, LLM, 저장소, 영상 다운로드, STT, OCR)은 Protocol 로 추상화돼 있고, 테스트는 가짜 구현으로 API 키와 DB 없이 돈다.

## API
- POST /analyses, GET /analyses/{id} : 텍스트 구간(segments) 판별. 구현됨.
- POST /transcripts, GET /transcripts/{id} : 유튜브 URL → 자막(caption)·음성(stt)·화면 글자(ocr) 구간. 구현됨. POST 는 pending 으로 바로 응답하고 FastAPI BackgroundTasks 로 처리하며, 결과의 segments 는 그대로 POST /analyses 에 넘길 수 있다. Celery + Redis 는 아직 쓰지 않는다.
- 구간의 source(user/stt/ocr/caption)와 time 은 요청부터 결과의 적발 문장까지 그대로 유지한다.
- LLM에게는 판단만 맡긴다. 시간, 출처, 근거 문서, 종합 점수와 등급은 코드(backend/app/rag/engine.py)가 채운다.
- 등급 기준(30 이상 주의, 70 이상 위험)은 engine.py 와 prompts/analyze_system.md 양쪽에 있으니 함께 바꾼다.

## 명령어 (backend/ 에서 실행)
- DB 실행: docker compose up -d db (저장소 루트에서)
- 기준 데이터 적재: uv run python -m scripts.ingest
- 서버 실행: uv run uvicorn app.main:app --reload
- 테스트: uv run pytest (test_pg.py 는 DB가 떠 있을 때만 실행되고 아니면 건너뛴다)
- 데이터 검증: uv run python -m scripts.validate_data
- 평가: uv run python -m scripts.evaluate (문장마다 LLM을 호출하므로 비용이 든다)
- 프론트 실행: npm run dev (frontend/ 에서, http://localhost:3000)

## 기준 데이터 규칙
- 레코드 하나(조항·사례)가 청크 하나다.
- 이단 사례는 claim + keywords 만 임베딩하고, intent / refutation 은 metadata 로 보관한다.
- 사람이 원출처와 대조하기 전까지 verified: false 로 둔다. AI가 임의로 true 로 바꾸지 않는다.

## 규칙
- 현재 단계: 텍스트 판별, 유튜브 영상 추출, 결과 화면까지 한 번씩 연결된 상태다. 워커 큐, 1차 키워드 필터링, 이미지 업로드 OCR, 피드백 기능은 아직 없다.
- LLM 응답은 반드시 JSON 스키마로 검증한다.
- 프롬프트는 app/prompts/ 아래 별도 파일로 분리한다.
- API 키는 .env로만 관리하고 커밋하지 않는다.
- 새 기능에는 pytest 테스트를 함께 작성한다.

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
