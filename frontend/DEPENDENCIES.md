# Frontend 의존성 추가 가이드

## 1. 필요한 패키지 설치

```bash
cd frontend
npm install date-fns
```

date-fns는 통화 이력 페이지에서 날짜 포맷팅에 사용됩니다.

## 2. 이미 설치된 패키지 확인

다음 패키지들이 이미 설치되어 있어야 합니다:
- zustand (상태 관리)
- axios (HTTP 클라이언트)
- sonner (토스트 알림)
- lucide-react (아이콘)

설치 여부 확인:
```bash
npm list zustand axios sonner lucide-react
```

## 3. 전체 의존성 재설치 (필요 시)

```bash
cd frontend
npm install
```

## 완료!

모든 의존성이 설치되면 개발 서버를 실행할 수 있습니다:
```bash
npm run dev
```

