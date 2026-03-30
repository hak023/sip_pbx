# Frontend 아키텍처 설계서

**목적**: Next.js 기반 운영자 대시보드의 구조, 데이터 흐름, 주요 기능을 기술한다.
**작성일**: 2026-03-30

---

## 1. 기술 스택

| 영역 | 기술 | 버전 |
|---|---|---|
| 프레임워크 | Next.js (App Router) | 14.2 |
| UI | React + Tailwind CSS + Radix UI | 18.3 / 3.4 |
| 실시간 통신 | Socket.IO Client | 4.7 |
| HTTP | Axios + fetch (동적 선택) | - |
| 상태관리 | 컴포넌트 로컬 상태 + Zustand (일부) | - |
| 차트 | Recharts | - |
| 폼 | React Hook Form + Zod | - |
| 오디오 | WaveSurfer.js | - |
| 아이콘 | Lucide React | - |

---

## 2. 라우팅 구조

```
app/
├── page.tsx            → /login 리다이렉트
├── layout.tsx          → AppShell (헤더+본문 레이아웃)
├── login/page.tsx      → 로그인 (테넌트 선택)
├── dashboard/page.tsx  → 운영자 대시보드 (메인)
├── knowledge/page.tsx  → 지식베이스 관리
└── call-history/page.tsx → 통화이력 조회
```

**인증 흐름**:
1. `/login` 에서 테넌트(내선번호) 선택
2. `POST /api/auth/login` → `access_token` 발급
3. `localStorage`에 `access_token`, `tenant`, `tenant_id` 저장
4. `/dashboard` 로 이동

---

## 3. 페이지별 아키텍처

### 3.1 대시보드 (Dashboard)

운영자가 실시간으로 통화를 모니터링하고, AI 봇 응대를 관리하는 핵심 화면이다.

```
┌─────────────────────────────────────────────────────┐
│  Header (연결 상태 배지, 네비게이션)                  │
├─────────────────────────────────────────────────────┤
│  메트릭 카드 (4개)                                    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                │
│  │총 통화│ │AI 응대│ │HITL  │ │평균시간│               │
│  └──────┘ └──────┘ └──────┘ └──────┘                │
├─────────────────────────────────────────────────────┤
│  실시간 통화 카드                                     │
│  ┌───────────────────────────────────┐               │
│  │ 발신자: 010-xxxx │ AI 응대중 │ 1:23 │              │
│  │ [호 전환] 버튼 (AI 응대 통화만)   │               │
│  └───────────────────────────────────┘               │
├─────────────────────────────────────────────────────┤
│  STT/TTS 실시간 피드                                  │
│  ├─ 사용자: "오늘 날씨 알려줘"                        │
│  ├─ AI: "오늘 서울 지역은..."                         │
│  └─ (interim STT 구분자 표시)                         │
├─────────────────────────────────────────────────────┤
│  처리 로그 (카테고리 필터, 최대 500행/통화)            │
├─────────────────────────────────────────────────────┤
│  HITL 요청 카드                                       │
│  ┌───────────────────────────────────┐               │
│  │ 질문: "기상감정서 발급법"          │               │
│  │ [응답 입력] [전송]                │               │
│  └───────────────────────────────────┘               │
├─────────────────────────────────────────────────────┤
│  최근 통화이력 (20건)                                 │
└─────────────────────────────────────────────────────┘
```

#### Socket.IO 이벤트

**수신 (listen)**:

| 이벤트 | 처리 |
|---|---|
| `call_started` | 활성 통화 카드 추가, SIP phase 표시 |
| `call_ended` | 통화 카드 제거, 관련 피드/HITL 정리 |
| `stt_transcript` | 실시간 STT 표시 (interim/final 구분) |
| `tts_started` | AI 응답 텍스트 표시 |
| `ai_greeting` | AI 인사말 표시 |
| `hitl_requested` | HITL 카드 추가, 피드에 알림 |
| `hitl_resolved` | HITL 카드 제거 |
| `call_debug_trace` | CDR 행 추가 |
| `transfer_success` | 통화 카드 제거 (전환 완료) |
| `transfer_failed` | 전환 실패 알림 |

**송신 (emit)**:

| 이벤트 | 페이로드 | 용도 |
|---|---|---|
| `manual_transfer_request` | call_id, operator_id, operator_number | 호 전환 요청 |
| `submit_hitl_response` | call_id, response_text, original_question, save_to_kb | HITL 응답 전송 |

#### REST API 호출

| 메서드 | 엔드포인트 | 용도 |
|---|---|---|
| GET | `/api/calls/active` | 활성 통화 목록 (초기+폴링) |
| GET | `/api/call-history?owner&limit=20` | 최근 통화이력 |
| GET | `/api/metrics/dashboard?owner` | 메트릭 카드 데이터 |

#### 호 전환 버튼 표시 조건

- 통화 유형이 `ai_handled` 또는 AI 호(callee가 AI 내선)일 때만 표시
- `manual_transfer_request` emit → 백엔드에서 SIP REFER 처리

### 3.2 지식베이스 관리 (Knowledge)

ChromaDB에 저장된 지식 문서를 CRUD 관리하는 화면이다.

**기능**:
- 지식 목록 조회 (카테고리·doc_type·source 필터)
- 새 지식 추가 (텍스트 직접 입력)
- 지식 삭제
- TXT 파일 업로드 (`/knowledge/upload` 이동)
- 페르소나 설정 (이름, 설명, 범위 키워드, 잡담 템플릿)

**REST API**:

| 메서드 | 엔드포인트 | 용도 |
|---|---|---|
| GET | `/api/knowledge` | 지식 목록 |
| POST | `/api/knowledge` | 지식 추가 |
| DELETE | `/api/knowledge/{docId}` | 지식 삭제 |
| GET | `/api/persona/{owner}` | 페르소나 조회 |
| PUT | `/api/persona/{owner}` | 페르소나 수정 |

### 3.3 통화이력 (Call History)

전체 통화 기록을 조회하고, 상세 정보(녹음, 트랜스크립트, CDR)를 확인하는 화면이다.

**기능**:
- 통화이력 목록 (최대 200건)
- 행 확장 → 상세 패널:
  - 통화 요약 (AI 생성)
  - 혼합 녹음 재생 (WaveSurfer)
  - 트랜스크립트 전문
  - CDR 처리 로그 (최대 1200행)
  - AI 미해결 항목

**REST API**:

| 메서드 | 엔드포인트 | 용도 |
|---|---|---|
| GET | `/api/call-history?owner&limit&offset` | 통화이력 목록 |
| GET | `/api/call-history/{id}/debug-trace?limit=1200` | CDR 상세 |
| GET | `/api/call-history/{id}/transcript` | 트랜스크립트 |
| GET | `/api/call-history/{id}/media/mixed` | 혼합 녹음 오디오 |

### 3.4 로그인 (Login)

**기능**:
- 등록된 테넌트(내선번호) 목록 조회
- 테넌트 선택 → 토큰 발급 → 대시보드 이동

---

## 4. 실시간 통신 아키텍처

### 4.1 Socket.IO 연결

```
Frontend (대시보드)          Backend (FastAPI + Socket.IO)
        │                               │
        ├── io(WS_URL) ──────────────► port 8001
        │   reconnectionAttempts: 12     │
        │   reconnectionDelay: 1500      │
        │                               │
        │ ◄── call_started ─────────────┤
        │ ◄── stt_transcript ───────────┤
        │ ◄── tts_started ──────────────┤
        │ ◄── hitl_requested ───────────┤
        │                               │
        ├── manual_transfer_request ──► │
        ├── submit_hitl_response ─────► │
        │                               │
        │ (WS 끊김 시)                   │
        ├── GET /api/calls/active ────► │  (20초 폴링)
        │                               │
```

### 4.2 연결 해제 복구

- Socket.IO 자동 재연결 (최대 12회, 1.5초 간격)
- 재연결 실패 시: REST 폴링으로 활성 통화 갱신 (`POLL_MS = 20000`)
- 재연결 성공 시: 활성 통화 + 메트릭 전체 갱신

---

## 5. 상태 관리

| 영역 | 방식 | 설명 |
|---|---|---|
| 대시보드 | 컴포넌트 로컬 `useState` | 활성 통화, STT/TTS 피드, HITL, 메트릭 |
| 운영자 상태 | Zustand `useOperatorStore` | 응대가능/자리비움 토글 |
| 지식베이스 | 컴포넌트 로컬 `useState` | 지식 목록, 필터, 페르소나 |
| 통화이력 | 컴포넌트 로컬 `useState` | 통화 목록, 확장 상태 |

---

## 6. 컴포넌트 구조

```
components/
├── AppShell.tsx              # 전체 레이아웃 셸 (로그인 외 헤더 포함)
├── AppHeader.tsx             # 상단 네비게이션 + 로그아웃 + 운영자 토글
├── OperatorAvailabilityToggle.tsx  # 헤더 내 응대상태 토글
├── OperatorStatusToggle.tsx  # (레거시) 운영자 상태 카드
├── HITLDialog.tsx            # HITL 응답 모달 (미사용, 대시보드 인라인으로 대체)
├── LiveCallMonitor.tsx       # 통화별 실시간 트랜스크립트 (미사용)
├── RagSearchDoneDetail.tsx   # RAG 검색 결과 상세 표시
├── knowledge/                # 지식베이스 서브컴포넌트
│   ├── KnowledgeList.tsx
│   ├── KnowledgeSearch.tsx
│   └── ...
└── ui/                       # shadcn-style 공용 UI 컴포넌트
    ├── button.tsx
    ├── card.tsx
    ├── dialog.tsx
    ├── input.tsx
    ├── select.tsx
    ├── switch.tsx
    ├── tabs.tsx
    └── ...
```

---

## 7. API 프록시 설정

```
// next.config.mjs
rewrites: [
  { source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }
]
```

- 브라우저에서 `/api/*` 호출 → Next.js가 백엔드 `127.0.0.1:8000`으로 프록시
- CORS 이슈 없이 같은 도메인에서 API 호출 가능
- Socket.IO는 별도 포트 `8001`로 직접 연결

---

## 8. 환경 변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `''` (같은 도메인) | REST API 베이스 URL |
| `NEXT_PUBLIC_WS_URL` | `http://127.0.0.1:8001` | Socket.IO 서버 URL |
| `API_PROXY_TARGET` | `127.0.0.1:8000` | Next.js API 프록시 대상 |

---

## 9. 관련 파일 위치

| 내용 | 파일 |
|---|---|
| 대시보드 | `frontend/app/dashboard/page.tsx` |
| 지식베이스 | `frontend/app/knowledge/page.tsx` |
| 통화이력 | `frontend/app/call-history/page.tsx` |
| 로그인 | `frontend/app/login/page.tsx` |
| 레이아웃 | `frontend/app/layout.tsx` |
| 앱 셸 | `frontend/components/AppShell.tsx` |
| 헤더 | `frontend/components/AppHeader.tsx` |
| WebSocket 훅 | `frontend/hooks/useWebSocket.ts` |
| 운영자 상태 | `frontend/store/useOperatorStore.ts` |
| 타입 정의 | `frontend/types/index.ts`, `frontend/types/api.ts` |
| Next.js 설정 | `frontend/next.config.mjs` |
| Tailwind 설정 | `frontend/tailwind.config.ts` |
