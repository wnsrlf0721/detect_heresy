# Detect Heresy 프론트엔드

Next.js 화면에서 유튜브 링크나 문장을 입력하고, 분석 진행 과정과 판별 근거를 확인할 수 있습니다. Chrome 확장 프로그램은 저장된 영상 분석을 `/result?analysis=<분석 ID>`로 엽니다.

| 파일 | 역할 |
| --- | --- |
| `app/page.tsx` | 영상 링크·텍스트 분석 진입점 |
| `app/result/page.tsx` | 저장된 영상 분석 조회 화면 |
| `app/privacy/page.tsx` | Chrome 확장 프로그램 데이터 처리 안내 |
| `lib/api.ts` | FastAPI 요청과 응답 타입 |
| `next.config.ts` | 컨테이너의 `/api` 프록시와 standalone 빌드 설정 |

## 로컬 개발

백엔드와 DB를 [저장소 README](../README.md#로컬-개발-실행-방법)에 따라 시작한 뒤, `frontend/`에서 실행합니다.

```sh
npm ci
npm run dev
```

화면은 `http://localhost:3000`입니다. 백엔드가 기본 주소 `http://localhost:8000`과 다르면 `.env.local`에 `NEXT_PUBLIC_API_URL`을 지정합니다.

## 컨테이너에서의 API 연결

로컬 Compose와 Render에서는 브라우저가 같은 도메인의 `/api`를 호출합니다. Next.js가 이 요청을 빌드 시 설정된 `API_INTERNAL_URL`로 전달합니다. Compose의 내부 주소는 `http://backend:8000`, Render의 내부 주소는 `http://127.0.0.1:8000`입니다. DB 접속 정보와 외부 AI API 키는 백엔드 환경 변수로 관리합니다. [Render 배포 구조](../docs/DEPLOYMENT.md)
