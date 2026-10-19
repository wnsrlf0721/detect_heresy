# 커밋 메시지 규칙

[Conventional Commits](https://www.conventionalcommits.org/ko/v1.0.0/) 형식을 따르고, 설명은 한국어로 쓴다.

## 형식

```
<타입>(<범위>): <요약>

<본문>

<꼬리말>
```

- 첫 줄(제목)은 `타입(범위): 요약` 한 줄이다. 범위는 생략할 수 있다.
- 요약은 무엇을 했는지 짧게 쓰고 끝에 마침표를 찍지 않는다. 예: `fix(rag): Voyage 임베딩 요청 한도(429) 초과 시 재시도`
- 본문은 제목과 한 줄 띄우고, 왜 바꿨는지와 무엇이 달라지는지를 쓴다. 바뀐 점이 여러 개면 `- ` 목록으로 쓴다.
- 꼬리말에는 `Co-Authored-By:` 같은 정보를 둔다.

## 타입

| 타입 | 언제 쓰나 | 예 |
| --- | --- | --- |
| `feat` | 사용자나 API 가 쓸 수 있는 기능을 새로 넣거나 넓힐 때 | 새 API, 화면 기능, 판별 단계 추가 |
| `fix` | 잘못 동작하던 것을 고칠 때 | 429 로 판별이 실패하던 문제 |
| `perf` | 결과는 같고 속도·호출 수·비용만 줄일 때 | 임베딩 일괄 요청, LLM 병렬 호출 |
| `refactor` | 동작(응답 형식)은 같고 코드·DB 구조를 바꿀 때 | 저장 구조를 테이블로 나눔 |
| `docs` | 문서만 바꿀 때 | README, docs/, CLAUDE.md |
| `test` | 테스트만 추가하거나 고칠 때 | |
| `data` | 기준 데이터(data/ 의 YAML)만 바꿀 때 | 교리 조항 추가, verified 갱신 |
| `prompt` | 프롬프트(backend/app/prompts/)만 바꿀 때 | 판별 지침 보강 |
| `chore` | 의존성, 설정, 빌드, 스크립트 등 위에 없는 잡일 | uv.lock 갱신, .gitignore |

- 한 커밋이 여러 타입에 걸치면 가장 주된 변경의 타입을 쓴다. 기능에 딸린 테스트·문서·프롬프트는 그 기능 커밋(`feat`)에 함께 넣는다.
- `data` 나 `prompt` 변경은 판별 버전(app/rag/version.py)을 바꿔 저장된 결과를 다시 판별하게 하므로, 본문에 그 영향을 적는다.

## 범위

바뀐 곳이 한 부분에 몰려 있으면 범위를 붙인다. 여러 부분에 걸쳐 있으면 생략한다.

| 범위 | 대상 |
| --- | --- |
| `api` | backend/app/api/, 요청·응답 스키마 |
| `rag` | backend/app/rag/ (임베딩, 검색, 판별 엔진, LLM 호출) |
| `media` | backend/app/media/ (다운로드, STT, OCR) |
| `db` | backend/app/db/, schema.sql |
| `frontend` | frontend/ |
| `scripts` | backend/scripts/ (ingest, validate_data, evaluate) |

## 호환되지 않는 변경

API 응답 형식이 바뀌거나 엔드포인트를 없애는 등 기존 사용처가 깨지면 타입 뒤에 `!` 를 붙이고 꼬리말에 `BREAKING CHANGE:` 로 설명한다.

```
refactor(api)!: /transcripts API 제거

BREAKING CHANGE: 추출 결과는 /videos 응답의 transcript 로만 받는다.
```
