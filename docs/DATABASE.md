# DB 구조

PostgreSQL 17 + pgvector 하나에 기준 데이터와 분석 결과를 모두 저장합니다. 테이블 정의는 [backend/app/db/schema.sql](../backend/app/db/schema.sql)이 기준입니다. 서버가 뜰 때 이 파일을 실행하므로 테이블을 따로 만들 필요는 없습니다.

## 접속 정보

`docker compose up -d db`로 띄운 DB의 기본값입니다(`docker-compose.yml`). `.env`의 `DATABASE_URL`로 바꿀 수 있습니다.

| 항목 | 값 |
| --- | --- |
| 접속 주소 | `postgresql://heresy:heresy@localhost:5432/heresy` |
| JDBC URL | `jdbc:postgresql://localhost:5432/heresy` |
| Host | `localhost` |
| Port | `5432` |
| Database | `heresy` |
| 사용자 / 비밀번호 | `heresy` / `heresy` |
| 스키마 | `public` |

### DBeaver로 접속하기

1. **새 데이터베이스 연결** → **PostgreSQL**을 고릅니다.
2. 위 표의 Host, Port, Database, 사용자, 비밀번호를 넣습니다. **URL**로 입력할 때는 JDBC URL을 붙여 넣습니다.
3. 처음이면 드라이버를 내려받으라는 창이 뜹니다. 내려받은 뒤 **연결 테스트**를 누릅니다.
4. `heresy` → `스키마` → `public` → `테이블`에서 아래 테이블을 봅니다. 테이블을 우클릭해 **ER 다이어그램 보기**를 하면 관계가 그림으로 나옵니다.

알아 둘 점:

- DB 컨테이너가 떠 있어야 접속됩니다. Docker Desktop을 켜고 저장소 루트에서 `docker compose up -d db`를 실행합니다.
- 로컬에 다른 PostgreSQL이 5432번 포트를 쓰고 있으면, 이 DB 대신 그쪽에 접속됩니다. 접속은 됐는데 테이블이 없다면 이 경우입니다.
- `vector` 칸(임베딩)은 DBeaver가 알지 못하는 형식이라 숫자 1024개가 든 긴 문자열로 보입니다. 열어 볼 필요는 없습니다.

## 관계

```
videos ──< transcripts ──< segments
   │            │              ▲
   │            └──< analyses ─┼──< findings ──< finding_refs >── chunks
   └───────────────────┘       └───────┘
```

| 흐름 | 쌓이는 행 |
| --- | --- |
| 영상 링크를 처음 넣음 | `videos` 1행(처음 보는 영상만), `analyses` 1행 |
| 영상에서 텍스트 추출 | `transcripts` 1행, `segments` 구간 수만큼 |
| 판별 | `analyses`에 등급·점수 채움, 적발마다 `findings` 1행, 적발의 근거마다 `finding_refs` 1행 |
| 대주제 정리 | `transcripts`의 `topic_*` 칸 채움(추출 결과마다 한 번) |
| 같은 영상을 다른 출처로 / 판별 기준이 바뀐 뒤 다시 넣음 | `analyses`만 새로 생기고 기존 `transcripts`·`segments`를 다시 씀 |
| 같은 영상·출처·판별 버전으로 다시 넣음 | 새 행 없이 저장된 `analyses`를 돌려줌 |
| **다시 분석** | `transcripts`·`segments`·`analyses`가 새로 생김 |
| 텍스트 직접 입력 | `transcripts` 1행(`video_id` 없음), 입력한 줄마다 `segments` 1행, `analyses` 1행 |

추출은 항상 자막·음성·화면 글자를 모두 하고, 화면에서 고른 출처는 판별에만 씁니다. 그래서 추출 결과 하나에 판별이 여러 개 있을 수 있습니다.

## 테이블

### `chunks` — 기준 데이터

판별할 때 검색해서 LLM에 넘기는 정통 교리 조항과 이단 사례입니다. 원본은 `data/`의 YAML이고, `scripts.ingest`가 넣습니다. 같은 id는 갱신하고, YAML에서 빠진 레코드는 지우지 않고 `active`를 끕니다. 지난 적발의 근거가 가리키고 있기 때문입니다.

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `id` | text, PK | 기준 데이터 id. 예: `wsc-33`, `scj-144000` |
| `kind` | text | `orthodox`(정통 교리) 또는 `heresy`(이단 사례) |
| `text` | text | 임베딩한 문장. 정통 교리는 `[출처 조항] 원문`, 이단 사례는 `[단체] 주장` 과 `키워드: …` 만 담고 반증과 의도는 `metadata`에 둠 |
| `metadata` | jsonb | 원본 YAML 레코드. 아래 표 참고 |
| `embedding` | vector(1024) | `text`의 Voyage 임베딩 |
| `active` | boolean | `false`면 검색에서 빠짐 |

`metadata`의 키:

| kind | 키 |
| --- | --- |
| `orthodox` | `source`(출처 문서), `section`(조항), `topic`, `text`(원문), `scripture`, `verified` |
| `heresy` | `group`(단체), `topic`, `claim`(주장), `keywords`, `intent`(원래 의도), `refutation`(반증), `scripture`, `orthodox_refs`(관련 정통 조항 id), `source`, `verified` |

`verified`는 사람이 원출처와 대조했는지를 나타냅니다. 지금은 모두 `false`입니다. 원본 YAML을 그대로 담는 칸이라 jsonb로 두었습니다.

### `videos` — 분석한 영상

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `video_id` | text, PK | 유튜브 영상 ID. 주소 형태(`youtu.be`, `watch?v=`, `shorts`)가 달라도 같은 값 |
| `url` | text | 처음 입력한 주소 |
| `title` | text | 영상 제목. 추출이 끝나면 채움 |
| `duration` | integer | 영상 길이(초) |
| `created_at` | timestamptz | 처음 분석한 시각 |

### `transcripts` — 추출 1회

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `id` | uuid, PK | |
| `video_id` | text, FK → `videos` | 텍스트 직접 입력이면 비어 있음 |
| `warnings` | text[] | 일부 출처를 추출하지 못한 이유. 예: 음성 인식 API 오류 |
| `topic_title`, `topic_summary`, `topic_keywords` | text, text, text[] | 영상 대주제. 정리에 실패하면 비어 있고, 다음 분석 때 다시 시도함 |
| `topic_embedding` | vector(1024) | 대주제 임베딩. 비슷한 주제의 영상을 찾는 데 씀 |
| `created_at` | timestamptz | 추출한 시각 |

### `segments` — 추출 결과의 구간

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `id` | bigserial, PK | |
| `transcript_id` | uuid, FK → `transcripts` | |
| `position` | integer | 추출 결과 안의 순서. 출처별로 시간순 |
| `source` | text | `caption`(자막), `stt`(음성), `ocr`(화면 글자), `user`(직접 입력) |
| `time` | text | `02:15` 형식. 직접 입력한 텍스트는 비어 있음 |
| `text` | text | 구간의 말 |

### `analyses` — 판별 1회

영상 분석과 텍스트 판별이 함께 씁니다. 화면과 API의 결과 id가 이 테이블의 `id`입니다.

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `id` | uuid, PK | `GET /videos/{id}`, `GET /analyses/{id}`의 id |
| `video_id` | text, FK → `videos` | 텍스트 판별이면 비어 있음. 추출이 끝나기 전에도 같은 영상의 진행 중인 분석을 찾을 수 있게 둠 |
| `transcript_id` | uuid, FK → `transcripts` | 판별한 추출 결과. 영상 분석은 추출이 끝나야 채워짐 |
| `sources` | text[] | 판별에 쓴 출처. 정렬된 값. 예: `{caption,ocr,stt}` |
| `version` | text | 판별 버전. 기준 데이터, 판별 프롬프트, 모델 설정, 엔진 코드로 만든 해시 |
| `status` | text | `pending` → `running` → `done` 또는 `failed` |
| `progress` | text | 진행 중인 단계(화면 표시용) |
| `error` | text | 실패 이유 |
| `verdict` | text | `safe` / `caution` / `danger`. 판별이 끝나면 채움 |
| `score` | integer | 종합 의심 지수 0~100. 적발 중 가장 높은 점수 |
| `summary` | text | 판별 요약 |
| `created_at` | timestamptz | 요청한 시각 |

- `(video_id, sources, version)`이 같은 `done` 행이 있으면, 같은 영상을 다시 넣을 때 그 결과를 그대로 돌려줍니다.
- `sources`는 고른 출처이지 실제로 성공한 출처가 아닙니다. 음성 인식이 실패해도 `stt`가 들어갑니다. 실제로 추출된 출처는 `segments.source`로, 실패 이유는 `transcripts.warnings`로 확인합니다.
- 서버가 재시작되면 `pending`/`running`이던 행은 `failed`로 바뀝니다.

### `findings` — 적발된 발언

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `id` | bigserial, PK | 나중에 맞다/틀리다 피드백을 붙일 때 가리킬 id |
| `analysis_id` | uuid, FK → `analyses` | |
| `position` | integer | 판별 결과 안의 순서 |
| `segment_id` | bigint, FK → `segments` | 적발된 구간. 발언 시각과 출처는 이 구간의 값 |
| `quote` | text | 적발된 발언 원문(구간 안의 일부) |
| `score` | integer | 이 발언의 의심 점수 30~100 |
| `group_name` | text | 비슷한 교리를 가르치는 단체. 없으면 비어 있음 |
| `topic` | text | 교리 분야. 예: `soteriology`(구원론), `christology`(기독론) |
| `reason` | text | 정통 교리에 어긋나는 이유 |
| `orthodox_refutation` | text | 정통 교리의 반증 |
| `heresy_intent` | text | 해당 이단의 원래 의도 |
| `scripture` | text[] | 관련 성경 구절 |

### `finding_refs` — 적발의 근거

| 칸 | 형식 | 내용 |
| --- | --- | --- |
| `finding_id` | bigint, FK → `findings` | |
| `position` | integer | 근거 순서 |
| `chunk_id` | text, FK → `chunks` | 근거로 쓴 기준 데이터 |

화면에 보이는 근거 문서의 제목과 발췌는 저장하지 않고, 읽을 때 `chunks`에서 만듭니다.

## 자주 쓰는 조회

최근 분석 목록:

```sql
select a.created_at, v.title, a.sources, a.status, a.verdict, a.score,
       (select count(*) from findings f where f.analysis_id = a.id) as findings,
       t.topic_title
from analyses a
left join videos v on v.video_id = a.video_id
left join transcripts t on t.id = a.transcript_id
order by a.created_at desc;
```

적발된 발언과 근거:

```sql
select v.title, s.time, s.source, f.score, f.group_name, f.quote,
       string_agg(r.chunk_id, ', ' order by r.position) as refs
from findings f
join analyses a on a.id = f.analysis_id
join segments s on s.id = f.segment_id
left join videos v on v.video_id = a.video_id
left join finding_refs r on r.finding_id = f.id
group by f.id, v.title, s.time, s.source, a.created_at
order by a.created_at desc, f.position;
```

어떤 기준 데이터가 근거로 많이 쓰였는지:

```sql
select c.id, c.kind, c.metadata->>'group' as "group", count(*) as used
from finding_refs r join chunks c on c.id = r.chunk_id
group by c.id
order by used desc;
```

추출 결과의 출처별 구간 수:

```sql
select v.title, t.created_at, s.source, count(*)
from transcripts t
join segments s on s.transcript_id = t.id
left join videos v on v.video_id = t.video_id
group by 1, 2, 3
order by 2 desc, 3;
```
