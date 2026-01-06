# AI Voicebot Frontend Control Center

실시간 AI 보이스봇 모니터링 및 Human-in-the-Loop(HITL) 시스템

## 🚀 기능

- **실시간 통화 모니터링**: 활성 통화 및 STT/TTS 트랜스크립트 확인
- **Human-in-the-Loop**: AI가 답변 못 할 때 운영자 개입
- **지식 베이스 관리**: Vector DB CRUD 작업
- **분석 대시보드**: 메트릭, 통계, 성능 추적

## 📦 기술 스택

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State Management**: Zustand
- **Real-time**: Socket.IO Client
- **Data Fetching**: TanStack Query (React Query)
- **Forms**: React Hook Form + Zod
- **Charts**: Recharts

## 🛠️ 설치 및 실행

```bash
# 의존성 설치
npm install

# 개발 서버 실행
npm run dev

# 프로덕션 빌드
npm run build

# 프로덕션 서버 실행
npm start
```

## ⚙️ 환경 변수

`.env.local` 파일을 생성하고 다음 변수를 설정하세요:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8001
NEXTAUTH_SECRET=your-secret-key
NEXTAUTH_URL=http://localhost:3000
```

## 📁 프로젝트 구조

```
frontend/
├── app/                    # Next.js App Router 페이지
│   ├── dashboard/          # 대시보드
│   ├── calls/              # 통화 관리
│   ├── knowledge/          # 지식 베이스
│   ├── hitl/               # HITL 큐
│   └── login/              # 로그인
├── components/             # React 컴포넌트
├── lib/                    # 유틸리티 함수
├── types/                  # TypeScript 타입 정의
├── hooks/                  # Custom React Hooks
└── store/                  # Zustand 상태 관리
```

## 🔗 관련 문서

- [System Overview](../docs/SYSTEM_OVERVIEW.md)
- [Frontend Architecture](../docs/frontend-architecture.md)
- [AI Voicebot Architecture](../docs/ai-voicebot-architecture.md)

## 📝 라이선스

MIT License

