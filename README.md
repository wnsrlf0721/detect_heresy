# 이단성 분석 서비스

유튜브 영상이나 문장을 정통 개신교 교리와 비교해, 어떤 발언이 왜 문제인지 근거와 함께 보여 주는 웹 서비스입니다. "이단이다"라고 판정하는 대신 적발 문장, 정통 교리의 반증, 해당 이단의 원래 의도를 나란히 제시합니다.

기획 배경은 [docs/PROJECT.md](docs/PROJECT.md)에 있습니다.

> 비교 기준이 되는 교리 자료(`data/`)는 아직 원출처와 대조하지 않은 초안입니다. 결과는 참고용으로만 보세요.

## 구성

| 폴더 | 내용 |
| --- | --- |
| `backend/` | FastAPI 서버. 영상에서 텍스트를 추출하고(`app/media`), 기준 데이터와 비교해 판별합니다(`app/rag`). |
| `frontend/` | Next.js 화면. 영상 링크나 문장을 입력하고 결과를 봅니다. |
| `data/` | 기준 데이터 원문(정통 교리, 이단 사례, 평가셋) YAML |
| `docker-compose.yml` | PostgreSQL + pgvector |

실행하면 세 가지가 뜹니다.

| 대상 | 주소 |
| --- | --- |
| 화면 | http://localhost:3000 |
| 백엔드 API | http://localhost:8000 (API 문서는 `/docs`) |
| DB | localhost:5432 |

## Docker Compose로 실행

Docker Desktop을 켜거나 Linux에서 Docker Engine과 Compose를 설치한 뒤, 저장소 루트에서 실행합니다.
분석 기능을 쓰려면 먼저 `.env.example`을 `.env`로 복사하고 `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`를 채웁니다. 음성 인식을 쓰려면 `OPENAI_API_KEY`도 넣습니다.

```sh
docker compose up --build -d --wait
```

화면은 http://localhost:3000, API 동작 확인은 http://localhost:3000/api/health 에서 할 수 있습니다.
같은 컴퓨터에서는 http://localhost:8000/docs 에서 API 문서를 열 수 있습니다.
DB 스키마는 백엔드가 시작할 때 초기화됩니다. 새 DB를 쓰거나 `data/`를 수정해 이미지를 다시 빌드한 경우 분석 전에 기준 데이터를 적재합니다. 이 명령은 Voyage API를 호출합니다.

```sh
docker compose exec backend python -m scripts.ingest
```

이미 이 저장소에서 `docker compose up -d db`로 쓰던 DB가 있다면 `pgdata` 볼륨을 그대로 사용합니다. `docker compose down`으로 종료해도 DB 데이터는 남습니다.
기본 컨테이너는 AI API를 사용하는 구성입니다. `STT_BACKEND=local`이나 `OCR_BACKEND=local`로 실행하려면 아래의 로컬 개발 방식을 사용합니다.

### 로그 확인

프론트와 백엔드의 표준 출력과 오류는 저장소 루트의 `log/frontend/`와 `log/backend/`에 `YYYY-MM-DD.log`로 쌓입니다. 날짜는 기본으로 한국 시간(`Asia/Seoul`)을 사용합니다. 다른 시간대를 쓰려면 루트 `.env`에 `LOG_TZ`를 설정합니다.

새 로그 줄에는 밀리초와 시간대가 포함된 시각이 붙습니다. 웹 화면의 분석 진행 기록에도 한국 시간으로 시각을 표시합니다.

Docker 실행 시 헬스체크와 분석 상태 조회 같은 일상적인 HTTP 접근 로그는 기록하지 않습니다. 백엔드 로그에서는 `analysis_id`로 작업 접수, 분석 시작, 추출·요약·결과 저장, 기존 결과 재사용과 실패 단계를 추적할 수 있습니다. 입력 문장과 분석 원문은 이 운영 로그에 넣지 않습니다. 화면의 상세 진행 과정은 DB에 계속 저장됩니다.

작업이 종료되면 `analysis.timing_summary`에 영상·텍스트 작업의 처리 시간이 기록됩니다. `elapsed_s`는 백그라운드 작업 전체 시간입니다. 단계별 `busy_s`는 **같은 단계에서** 겹쳐 실행한 시간을 한 번만 센 값, `sum_s`는 모든 호출 시간의 합, `max_s`는 가장 오래 걸린 호출 시간입니다. `calls`와 `failed`는 실행 횟수와 실패 횟수입니다. 추출 전체와 OCR처럼 상위·하위 단계가 있고 음성·OCR이나 요약·판정도 병렬로 실행되므로 단계별 시간은 합산하지 않습니다. 재사용이나 수동 자막 선택 때문에 건너뛴 단계는 목록에 나오지 않습니다.

```sh
log_date=$(TZ=Asia/Seoul date +%F)
tail -f "log/frontend/$log_date.log" "log/backend/$log_date.log"
```

PowerShell에서는 `Get-Content -Wait "log/backend/$(Get-Date -Format yyyy-MM-dd).log"`로 볼 수 있습니다(PC가 한국 시간인 경우). 자정 이후부터 로그는 새 날짜 파일에 기록되므로, 새 로그가 생기면 오늘 날짜로 `tail`을 다시 실행합니다. `docker compose logs -f frontend backend`도 사용할 수 있습니다.

## 로컬 개발 준비물

- Docker Desktop
- Python 3.12 이상과 [uv](https://docs.astral.sh/uv/). uv는 백엔드의 가상환경(`backend/.venv`)을 만들고 패키지를 설치할 때만 씁니다. `py -m pip install --user uv`로 설치합니다.
- Node.js 20 이상. 화면 실행뿐 아니라 백엔드의 유튜브 다운로드(yt-dlp)에도 쓰입니다.
- API 키 세 개
  - [Anthropic](https://console.anthropic.com/): 판별, 화면 글자 인식
  - [Voyage AI](https://www.voyageai.com/): 임베딩
  - [OpenAI](https://platform.openai.com/): 사용할 수 있는 수동 한국어 자막이 없는 영상의 음성 인식. 키가 없으면 사용할 수 있는 화면 글자만으로 판별합니다.

AI 작업은 모두 API로 처리하므로 GPU나 ffmpeg 설치가 필요 없습니다.

## 로컬 개발 실행 방법

### 1. 환경 변수

저장소 루트에서 `.env.example`을 `.env`로 복사하고 키를 채웁니다.

```
ANTHROPIC_API_KEY=...
VOYAGE_API_KEY=...
OPENAI_API_KEY=...
```

### 2. DB

저장소 루트에서 실행합니다.

```
docker compose up -d db
```

DBeaver 같은 도구로 직접 볼 때는 `localhost:5432`, DB·사용자·비밀번호 모두 `heresy`로 접속합니다(`postgresql://heresy:heresy@localhost:5432/heresy`). 테이블마다 어떤 데이터가 들어가는지는 [docs/DATABASE.md](docs/DATABASE.md)에 있습니다.

### 3. 백엔드

`backend/`에서 실행합니다. 먼저 가상환경을 만들고 패키지를 설치합니다. 처음 한 번, 그리고 `pyproject.toml`이나 `uv.lock`이 바뀐 뒤에 실행합니다.

```
py -m uv sync
```

pip로 설치한 uv는 실행 파일이 PATH에 없는 폴더에 들어가서 `uv` 명령을 찾지 못하므로 `py -m uv`로 실행합니다. venv가 켜진 터미널에서는 `py`가 venv의 python을 쓰고, 거기에는 uv가 없어서 `No module named uv`가 납니다. 이때는 `deactivate`로 venv를 끈 뒤 실행합니다.

`uv sync`는 venv를 lock 파일과 똑같이 맞추므로, 명령에 없는 선택 패키지는 지웁니다. GPU용 패키지(`--extra local`)를 설치해 두었다면 `py -m uv sync --extra local`로 실행해야 남습니다.

그다음 가상환경을 켜고 실행합니다. 켜지면 프롬프트 앞에 `(detect-heresy-backend)`가 붙습니다. 아래의 다른 백엔드 명령도 모두 venv를 켠 터미널에서 실행합니다.

```
.venv\Scripts\Activate.ps1
python -m scripts.ingest
uvicorn app.main:app --reload
```

- PowerShell에서 스크립트 실행이 막혀 있다고 나오면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 한 번 실행합니다. cmd에서는 `.venv\Scripts\activate.bat`입니다.
- `scripts.ingest`는 `data/`의 기준 데이터를 임베딩해 DB에 넣습니다. 처음 한 번, 그리고 `data/`를 고친 뒤에 실행합니다.
- 서버가 뜨면 http://localhost:8000/health 가 `{"status":"ok"}`를 돌려줍니다.

### 4. 프론트엔드

새 터미널을 열고 `frontend/`에서 실행합니다.

```
npm install
npm run dev
```

http://localhost:3000 을 엽니다. 백엔드 주소가 `http://localhost:8000`이 아니면 `frontend/.env.local`에 `NEXT_PUBLIC_API_URL`을 적습니다.

## 화면에서 해 볼 수 있는 것

### 영상 링크 분석

1. **영상 링크** 탭에서 유튜브 주소를 붙여 넣습니다. 예: `https://youtu.be/UeXJQ7cA7lo`
2. **분석 시작**을 누르면 다음 순서로 진행됩니다.
   - 사람이 작성한 한국어 자막을 가져올 수 있으면 자막과 화면 글자를 판별에 사용합니다. 수동 자막이 없거나 가져오지 못하면 음성 인식과 화면 글자를 사용합니다.
   - 정통 교리와 비교해 판별: 구간이 20개를 넘으면 먼저 의심 구간을 고르고, 고른 구간만 정밀 분석합니다.
   - 영상 대주제 정리
3. 웹 화면에서 경과 시간과 단계별 진행을 볼 수 있습니다.

분석한 영상은 DB에 저장됩니다.

- **같은 영상을 다시 넣으면** 저장된 결과를 바로 보여 줍니다. 주소 형태(`youtu.be/…`, `watch?v=…`, `shorts/…`)가 달라도 같은 영상으로 봅니다. 결과 위에 "저장된 분석 결과"와 분석 날짜가 나오고, **다시 분석**을 누르면 내려받기부터 새로 합니다.
- 자동 출처 선택으로 분석한 영상에는 해당 방식으로 추출한 텍스트를 재사용합니다. 같은 영상의 이전 방식으로 저장된 결과도 기존 결과 링크에서 열 수 있습니다.
- 기준 데이터(`data/orthodox`, `data/heresy`)나 판별 프롬프트, 모델 설정을 바꾸면 저장된 결과를 쓰지 않고 자동으로 다시 판별합니다. 이때도 추출한 텍스트는 다시 씁니다.
- 결과 화면 아래쪽에 **대주제가 비슷한 이전 분석**이 나오고, 누르면 그 분석을 엽니다.

알아 둘 점:

- 4분짜리 영상의 추출이 25초쯤 걸렸습니다(음성 인식 제외 측정). 그 뒤 판별이 이어집니다.
- 유튜브 주소만 받고, 30분 이하 영상만 처리합니다.
- 음성 인식은 말을 짧게 잘라 두므로, 각 구간을 앞 구간 두 개, 뒤 구간 한 개와 함께 검색하고 판별합니다. 적발하는 것은 그 구간의 말뿐입니다.
- 추출과 판별 모두 API를 호출하므로 비용이 듭니다. 의심 구간 고르기(Haiku)는 구간 100개마다 한 번, 정밀 분석(Opus)은 고른 구간 20개마다 한 번, 대주제 정리(Haiku)는 영상마다 한 번, 화면 글자 인식은 프레임 10장마다 한 번 호출합니다. 의심 구간 고르기가 실패하면 놓치지 않도록 모든 구간을 정밀 분석합니다.
- `OPENAI_API_KEY`가 없으면 결과 화면에 "음성 인식에 실패했습니다" 안내가 뜨고 음성 칸이 비어 있습니다. 키를 넣은 뒤에는 **다시 분석**을 눌러야 음성 인식을 새로 합니다.

### 텍스트 직접 입력

**텍스트 직접 입력** 탭에 문장을 붙여 넣고 **분석 시작**을 누릅니다. 한 줄이 한 구간이며 수십 초 안에 결과가 나옵니다. 화면 동작을 빠르게 확인하기 좋습니다.

시험해 볼 문장:

```
예수님이 약속하신 보혜사는 오늘날 이 땅에 육체로 오신 약속의 목자입니다. 그분에게 가야만 계시의 말씀을 받을 수 있습니다.
```

```
예수님이 약속하신 보혜사 성령께서 우리 안에 거하시며 진리로 인도하십니다.
```

첫 문장은 위험으로, 둘째 문장은 안전으로 나옵니다.

### 결과 화면 읽는 법

| 영역 | 내용 |
| --- | --- |
| 영상 대주제 | 영상이 다루는 주제를 한 줄 제목, 요약, 핵심어로 정리합니다. 비슷한 영상을 찾는 기준입니다. 영상 분석에서만 나옵니다. |
| 종합 의심 지수 | 0~100% 게이지와 등급. 30 미만 안전, 30 이상 주의, 70 이상 위험. 가장 높은 적발 문장의 점수가 종합 점수입니다. |
| 타임라인 | 의심 발언이 나온 시점을 영상 길이 위에 점으로 표시합니다. 점을 누르면 그 시점의 영상과 해당 근거로 이동합니다. 영상 분석에서만 나옵니다. |
| 교리 비교 | 적발 문장마다 영상 속 발언 ↔ 정통 교리의 반증 ↔ 이단의 원래 의도를 3단으로 보여 줍니다. 아래에 문제인 이유, 성경 구절, 근거 문서가 붙습니다. |
| 비슷한 주제의 이전 분석 | 대주제 유사도가 60% 이상인 다른 영상의 분석을 유사도 순으로 5개까지 보여 줍니다. 기준값은 `.env`의 `RELATED_MIN_SIMILARITY`(기본 0.6)로 바꿀 수 있으며, 실제 영상으로 맞춰 보지는 않았습니다. |
| 영상에서 추출한 텍스트 | 자막, 음성, 화면 글자를 나란히 보여 줍니다. 적발된 구간은 색으로 표시되고, 시간을 누르면 영상이 그 시점부터 재생됩니다. |

적발 문장이 없으면 교리 비교에 "정통 교리에서 벗어난 발언을 찾지 못했습니다"가 나옵니다.

## 화면 없이 API로 확인하기

http://localhost:8000/docs 에서 직접 호출해 볼 수 있습니다.

| API | 설명 |
| --- | --- |
| `POST /videos` | `{"url": "유튜브 주소", "sources": ["caption", "stt", "ocr"], "force": false}`. 영상 분석(추출 → 판별 → 대주제)을 한 작업으로 만듭니다. 저장된 분석이 있으면 `200`과 `done`, `cached: true`로 바로 돌려주고, 없으면 `202`와 `pending`으로 응답합니다. `sources`와 `force`는 생략할 수 있습니다. |
| `GET /videos/{id}` | 영상 분석 상태와 결과. 추출이 끝나면 판별 중에도 `transcript`가 채워지고, `done`이면 `result`, `topic`, `related`(비슷한 주제의 이전 분석)가 들어 있습니다. |
| `POST /analyses` | `{"segments": [{"text": "...", "time": "02:15", "source": "stt"}]}`를 판별하는 작업을 만들고 `pending`으로 바로 응답합니다. `time`과 `source`는 생략할 수 있습니다. |
| `GET /analyses/{id}` | 판별 상태와 결과. `status`가 `done`이면 `result`에 들어 있습니다. |

## 테스트와 평가

`backend/`에서 venv를 켜고 실행합니다.

```
pytest
python -m scripts.validate_data
python -m scripts.evaluate
```

- `pytest`는 API 키 없이 돕니다. DB가 떠 있으면 DB 통합 테스트도 함께 돕니다.
- `scripts.evaluate`는 `data/eval/cases.yaml`의 문장을 실제로 판별해 정확도를 냅니다. 문장마다 LLM을 호출해 1회에 약 $0.8가 듭니다.

## GPU로 직접 돌리기 (선택)

NVIDIA GPU가 있는 컴퓨터에서는 음성 인식과 화면 글자 인식을 API 대신 직접 돌릴 수 있습니다. `backend/`에서 venv를 끈 상태로 `py -m uv sync --extra local`을 실행해 패키지를 설치하고 `.env`에 아래를 적습니다.

```
STT_BACKEND=local
OCR_BACKEND=local
LOCAL_DEVICE=cuda
```

GPU에서는 아직 실행해 보지 않았습니다. CPU(`LOCAL_DEVICE=cpu`)로도 돌지만 4분 영상에 8분쯤 걸립니다.

## 문제가 생기면

| 증상 | 확인할 것 |
| --- | --- |
| 화면에 "서버에 연결하지 못했습니다" | 백엔드가 8000번 포트에서 실행 중인지 확인합니다. |
| 백엔드가 시작하다 DB 오류로 멈춤 | `docker compose up -d db`로 DB를 먼저 띄웁니다. |
| "영상을 가져오지 못했습니다 … 403" | 유튜브가 간헐적으로 다운로드를 막습니다. 다섯 번까지 자동으로 재시도하며, 그래도 실패하면 다시 시도합니다. |
| 판별 결과에 근거 문서가 비어 있음 | `python -m scripts.ingest`로 기준 데이터를 적재했는지 확인합니다. |
| "임베딩 요청 실패 … 429" | Voyage에 결제 수단을 등록하지 않은 계정은 분당 3회·1만 토큰으로 제한됩니다. 요청을 나눠 보내고 기다렸다 재시도하지만, 다른 작업(예: `scripts.ingest`)과 겹치면 실패할 수 있으니 잠시 뒤 다시 시도합니다. 결제 수단을 등록하면 한도가 풀립니다(무료 제공량은 그대로). |
| 긴 영상의 판별이 몇 분씩 걸림 | 위 Voyage 한도 때문에 임베딩 요청이 1분에 1만 토큰씩만 나갑니다. 14분 영상(의심 구간 214개)의 판별에 4분 반쯤 걸렸습니다. |
| "서버가 다시 시작되어 작업이 끊겼습니다" | 작업 중에 백엔드를 재시작하면(코드를 고쳐 `--reload`로 다시 뜬 경우 포함) 진행 중이던 작업이 끊깁니다. 분석을 다시 시작합니다. |

## 아직 없는 것

- 자막 스크린샷 이미지 업로드
- 과거 분석 전체 목록 화면 (지금은 비슷한 주제의 분석만 연결됩니다)
- 워커 큐(Celery + Redis). 지금은 작업이 백엔드 프로세스 안에서 돌아서, 재시작하면 끊깁니다.
- 판별 결과에 대한 맞다/틀리다 피드백
