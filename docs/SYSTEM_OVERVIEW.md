# 🏗️ AI SIP PBX 시스템 - 완전한 개요

## 📊 시스템 소개

**AI SIP PBX**는 Python 기반의 엔터프라이즈급 **B2BUA(Back-to-Back User Agent)** 통신 시스템으로, **AI 음성 비서 기능**과 **실시간 웹 제어 센터**를 통합한 차세대 통신 플랫폼입니다.

### ✨ 핵심 가치

- 🔄 **완전한 SIP B2BUA**: 표준 SIP 프로토콜 완벽 지원
- 🤖 **지능형 AI 응대**: 부재중 자동 응답, RAG 기반 지식 검색
- 🎯 **Human-in-the-Loop**: AI가 모르는 질문은 운영자에게 실시간 전달
- ⚡ **초저지연 RTP**: 5ms 이하 미디어 릴레이
- 🖥️ **실시간 웹 제어**: WebSocket 기반 통화 모니터링 및 제어
- 💰 **비용 효율**: Gemini 2.5 Flash로 월 100통화 ₩6,400

---

## 🏛️ 시스템 아키텍처

### 전체 구조도

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AI SIP PBX 통합 시스템                            │
└────────────────────────────────────────────────────────────────────────┘

┌──────────────────────┐       ┌──────────────────────┐       ┌──────────────────────┐
│   EXTERNAL USERS     │       │   FRONTEND CENTER    │       │   BACKEND SERVICES   │
├──────────────────────┤       ├──────────────────────┤       ├──────────────────────┤
│                      │       │                      │       │                      │
│  📞 SIP Callers      │◄─────►│  🖥️ Web Dashboard    │◄─────►│  🔄 SIP/RTP Engine   │
│  👤 Phone Users      │  SIP  │  (Next.js 14)        │  WS   │  (Python asyncio)    │
│                      │ 5060  │                      │ 8001  │                      │
│  • 일반 통화         │       │  Features:           │ REST  │  • B2BUA Core        │
│  • AI 자동 응대      │       │  • 실시간 모니터링   │ 8000  │  • RTP Relay         │
│  • 호 전환           │◄─────►│  • Live Transcript   │◄─────►│  • Call Manager      │
│                      │ RTP   │  • Knowledge CRUD    │       │  • Port Pool Mgr     │
│                      │10000  │  • HITL Interface    │       │                      │
│                      │-20000 │  • 통화 이력         │       │  🤖 AI Orchestrator  │
│                      │       │  • 운영자 상태       │◄─────►│  (Pipecat Pipeline) │
│                      │       │  • Call Controls     │       │                      │
│                      │       │    - 발신 시작       │       │  • STT/TTS Stream    │
│                      │       │    - 통화 종료       │       │  • LLM Processing    │
│                      │       │    - 호 전환         │       │  • VAD Barge-in      │
│                      │       │    - 녹음 다운로드   │       │  • RAG Search        │
│                      │       │                      │       │                      │
└──────────────────────┘       └──────────────────────┘       │  📚 Vector DB        │
                                                               │  (ChromaDB/Pinecone) │
                                                               │                      │
                                                               │  • 지식 베이스       │
                                                               │  • Capability 관리   │
                                                               │  • 임베딩 검색       │
                                                               │                      │
                                                               └──────┬───────────────┘
                                                                      │
                                                                      ↓
                                                            ┌──────────────────────┐
                                                            │   EXTERNAL AI APIs   │
                                                            ├──────────────────────┤
                                                            │  🎤 Google STT       │
                                                            │  🔊 Google TTS       │
                                                            │  💡 Gemini 2.5 Flash │
                                                            └──────────────────────┘
```

### 3계층 아키텍처

#### Layer 1: SIP PBX Core (통신 기반)
**역할**: 표준 SIP 통신 프로토콜 처리

- ✅ **SIP B2BUA 엔진**
  - INVITE/BYE/ACK/CANCEL (통화 제어)
  - REGISTER (사용자 등록)
  - PRACK/UPDATE (세션 업데이트)
  - OPTIONS (상태 확인)
  
- ✅ **RTP Relay**
  - Bypass 모드 (<5ms 지연)
  - 동적 포트 할당 (10,000-20,000)
  - Jitter Buffer 관리
  - 양방향 독립 스트림

- ✅ **통화 관리**
  - 독립적인 Caller/Callee leg 관리
  - Transaction 상태 추적
  - SDP 협상 및 미디어 조정
  - CDR 생성 (JSON Lines)

#### Layer 2: AI Voice Assistant (지능 확장)
**역할**: 지능형 음성 응대 및 자동화

- ✅ **AI 자동 응답**
  - 타이머 기반 (10초 무응답 시)
  - 수동 부재중 모드 (웹 설정)
  - 2-Phase 인사말 (고정 + Capability 가이드)

- ✅ **실시간 음성 처리**
  - Google Cloud STT (Telephony 모델, 16kHz)
  - Google Cloud TTS (Neural2 음성)
  - Pipecat 기반 스트리밍 파이프라인
  - PCM 큐 (maxsize=150, ~5초 버퍼)

- ✅ **지능형 대화**
  - Gemini 2.5 Flash LLM
  - RAG 기반 지식 검색
  - Vector DB (ChromaDB/Pinecone)
  - Sentence Transformers 임베딩

- ✅ **Barge-in 지원**
  - WebRTC VAD 기반 발화 감지
  - 사용자 발화 시 AI 응답 즉시 중단
  - 자연스러운 대화 흐름

- ✅ **통화 녹음 및 지식 추출**
  - 화자 분리 녹음 (WAV)
  - 자동 STT 전사
  - LLM 기반 지식 추출 (멀티스텝 파이프라인)
  - Vector DB 자동 저장

- ✅ **Human-in-the-Loop (HITL)**
  - AI 신뢰도 < 0.6 시 운영자 요청
  - 실시간 WebSocket 알림
  - 20초 timeout 자동 fallback
  - 운영자 부재중 모드 지원

#### Layer 3: Backend API Services (연동 및 제어)
**역할**: Frontend 연동 및 실시간 통신

- ✅ **FastAPI REST API Gateway** (Port 8000)
  - `/api/call-history` - 통화 이력 조회
  - `/api/calls/{call_id}/transcript` - 대화 내용
  - `/api/calls/{call_id}/hangup` - 통화 종료
  - `/api/calls/{call_id}/recording` - 녹음 다운로드
  - `/api/outbound/call` - 발신 시작
  - `/api/knowledge/*` - 지식 베이스 CRUD
  - `/api/operator/status` - 운영자 상태 관리
  - `/api/hitl/*` - HITL 요청 관리

- ✅ **Socket.IO WebSocket Server** (Port 8001)
  - `call:new` - 신규 통화 알림
  - `call:updated` - 통화 상태 변경
  - `call:ended` - 통화 종료
  - `transcript` - 실시간 대화 내용
  - `hitl:request` - HITL 요청
  - `hitl:response` - HITL 응답

- ✅ **Database Integration**
  - PostgreSQL: 통화 이력, HITL 요청, 사용자 데이터
  - Redis: 실시간 상태, WebSocket pub/sub
  - Vector DB: 지식 베이스 임베딩

---

## 🎯 주요 사용 시나리오

### 1️⃣ 일반 통화 (AI 미사용)

```
Caller → PBX → Callee (10초 내 응답)
        ↓
    RTP Relay (직접 중계, <5ms)
        ↓
    통화 종료 → CDR 생성
```

**특징**:
- 표준 SIP B2BUA 동작
- 저지연 RTP 직접 릴레이
- 통화 녹음 (선택)
- CDR 및 메트릭 수집

### 2️⃣ AI 자동 응답 (부재중 응대)

```
Caller → PBX → [10초 timeout] → AI Orchestrator 활성화
        ↓                              ↓
    RTP Relay                      STT/TTS/LLM
        ↓                              ↓
    AI 음성 전달 ←─────────────── RAG 검색 + 응답 생성
        ↓
    통화 종료 → 지식 추출 → Vector DB 저장
```

**워크플로우**:
1. Callee 10초 무응답
2. AI Orchestrator 시작
3. **Phase 1 인사말**: "안녕하세요, 무엇을 도와드릴까요?"
4. **Phase 2 Capability 가이드**: Vector DB에서 capability 로드 → 안내
5. 실시간 대화 (STT → RAG → LLM → TTS)
6. 통화 종료 → 전사 → 지식 추출 → 저장

**응답 시간**:
- High Confidence: **평균 0.9초**
- Medium Confidence: **평균 1.3초**
- HITL (운영자 개입): **평균 20초**

### 3️⃣ Human-in-the-Loop (낮은 신뢰도)

```
Caller → AI → [신뢰도 < 0.6] → HITL Request
               ↓                      ↓
          Hold Music          Frontend Alert (🔔)
               ↓                      ↓
          [대기 중...]         Operator Types Answer
               ↓                      ↓
          LLM Refinement ◄──────── Human Response
               ↓
          Final Answer → Caller
               ↓
       Save to Knowledge Base
```

**워크플로우**:
1. AI가 적절한 답변을 찾지 못함 (RAG score < 0.6)
2. 발신자: "잠시만 확인 중이니 기다려 주세요" + 대기 음악
3. Frontend: 🔔 알림 + 질문 표시
4. 운영자: 답변 입력 (20초 이내)
5. LLM: 답변 자연스럽게 다듬기
6. AI: 발신자에게 답변
7. 답변 Vector DB 저장 (재사용)

**Timeout 처리**:
- 20초 내 응답 없음 → "확인 후 다시 안내드리겠습니다" → 통화 종료
- 운영자 부재중 → 즉시 "확인 후 안내드리겠습니다" → 통화 종료

### 4️⃣ 통화 이력 관리 (Frontend)

```
Frontend Call History Page
  ↓
클릭하여 Rolldown (▶ → ▼)
  ↓
대화 내용 표시
  - 🤖 AI 응답 (파란색)
  - 👤 사용자 발화 (회색)
  - 타임스탬프

작업 버튼:
  📞 발신 - 해당 번호로 다시 전화
  ✖ 종료 - 진행 중인 통화 종료
  ⬇ 녹음 - 녹음 파일 다운로드
```

**기능**:
- 페이지네이션 (20개/페이지)
- 실시간 상태 표시 (진행중/완료)
- AI 응대 구분 (Badge)
- 대화 내용 Rolldown
- 발신/종료/녹음 원클릭

---

## 🔄 데이터 플로우

### 일반 통화 플로우

```
1. SIP 시그널링
   Caller → SIP Endpoint → Call Manager → SIP Endpoint → Callee

2. RTP 미디어 (Bypass 모드)
   Caller RTP → Port A (PBX) → RTP Relay → Port B (PBX) → Callee RTP

3. 통화 종료
   BYE → Call Manager → RTP Stop → CDR 생성 → Webhook 발송
```

### AI 응대 통화 플로우

```
1. AI 활성화
   Timeout/부재중 → Call Manager → AI Orchestrator Start → RTP Mode Switch

2. 음성 → 텍스트
   Caller RTP → RTP Worker → Pipecat → Google STT → Text

3. 지능형 응답
   Text → RAG Search (Vector DB) → LLM (Gemini) → Response Text

4. 텍스트 → 음성
   Response Text → Google TTS → PCM Queue (150 frames) → RTP Packets → Caller

5. 지식 추출 (통화 종료 후)
   전사 로드 → LLM 분석 → 지식 추출 → Vector DB 저장
```

### HITL 플로우

```
1. 신뢰도 낮음 감지
   RAG Score < 0.6 → HITL Trigger

2. 운영자 요청
   HITL Service → WebSocket → Frontend Alert (🔔)

3. 대기 음악
   AI → TTS("잠시만 기다려주세요") → Hold Music Loop

4. 운영자 응답
   Frontend Input → WebSocket → HITL Service → LLM Refine → TTS → Caller

5. 지식 저장
   Q&A Pair → Vector DB (자동 저장)
```

---

## 📊 성능 지표

### AI 응답 시간

| 시나리오 | 평균 | P95 | P99 |
|----------|------|-----|-----|
| **High Confidence** | 0.9초 | 1.2초 | 1.5초 |
| **Medium Confidence** | 1.3초 | 1.8초 | 2.2초 |
| **HITL (운영자 개입)** | 20초 | 35초 | 60초 |

**응답 시간 분해**:
- RAG 검색: ~75ms
- LLM 생성: ~413ms
- TTS 첫 청크: ~235ms
- **총합**: ~923ms

### 비용 분석 (월 100통화 기준)

| 서비스 | 일일 비용 | 월 비용 |
|--------|-----------|---------|
| **Gemini 2.5 Flash** | ₩46 | ₩1,400 |
| **Google STT** | ₩100 | ₩3,000 |
| **Google TTS** | ₩66 | ₩2,000 |
| **Vector DB (ChromaDB)** | ₩0 (local) | ₩0 |
| **총합** | **₩212** | **₩6,400** |

> 💡 Gemini Pro 사용 시: **₩23,400/월** (3.6배 더 비쌈)

### 시스템 용량

| 메트릭 | 용량 |
|--------|------|
| **동시 통화** | 100+ |
| **동시 AI 세션** | 50+ |
| **WebSocket 연결** | 1,000+ |
| **API 요청** | 10,000+/분 |
| **Vector DB 크기** | 1M+ documents |
| **RTP 지연** | <5ms |
| **통화 설정 시간** | ~200ms |

---

## 🛠️ 기술 스택

### Backend

| 카테고리 | 기술 |
|---------|-----|
| **언어** | Python 3.11+ |
| **프레임워크** | FastAPI, asyncio, aiohttp |
| **SIP/RTP** | 순수 Python 구현 |
| **WebSocket** | Socket.IO, python-socketio |
| **Database** | PostgreSQL (asyncpg), Redis |
| **AI/ML** | Google Gemini 2.5 Flash, Sentence Transformers, PyTorch |
| **Vector DB** | ChromaDB (dev), Pinecone (prod) |
| **Audio** | opuslib, G.711, WebRTC VAD |
| **모니터링** | Prometheus, structlog |

### Frontend

| 카테고리 | 기술 |
|---------|-----|
| **프레임워크** | Next.js 14, React 18 |
| **언어** | TypeScript |
| **스타일링** | TailwindCSS |
| **상태 관리** | Zustand |
| **WebSocket** | Socket.IO Client |
| **빌드** | Turbopack (Next.js 14) |

### External Services

| 서비스 | 용도 |
|--------|------|
| **Google Cloud STT** | 음성 → 텍스트 (Telephony 모델) |
| **Google Cloud TTS** | 텍스트 → 음성 (Neural2) |
| **Google Gemini 2.5 Flash** | LLM 대화 생성 (초저비용) |

---

## 📁 주요 컴포넌트

### Backend 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| **SIP Endpoint** | `src/sip_core/sip_endpoint.py` | SIP 메시지 파싱/생성, Transaction 관리 |
| **Call Manager** | `src/sip_core/call_manager.py` | B2BUA 로직, 통화 상태 추적 |
| **RTP Relay** | `src/media/rtp_relay.py` | RTP 패킷 중계, PCM 큐 관리 (maxsize=150) |
| **RTP Transport** | `src/ai_voicebot/pipecat/rtp_transport.py` | Pipecat → RTP, 재생 길이 동기화 |
| **AI Orchestrator** | `src/ai_voicebot/orchestrator.py` | AI 세션 관리, 파이프라인 제어 |
| **RAG Processor** | `src/ai_voicebot/pipecat/processors/rag_processor.py` | RAG 검색, LLM 응답 생성 |
| **HITL Service** | `src/services/hitl_service.py` | call_id별 큐, 20초 timeout, fallback |
| **API Gateway** | `src/api/main.py` | FastAPI REST API |
| **WebSocket Server** | `src/websocket/server.py` | Socket.IO 실시간 통신 |

### Frontend 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| **Call History** | `frontend/app/call-history/page.tsx` | 통화 이력, Rolldown, 작업 버튼 |
| **Live Monitor** | `frontend/app/dashboard/page.tsx` | 실시간 통화 모니터링 |
| **Knowledge Manager** | `frontend/app/knowledge/page.tsx` | 지식 베이스 CRUD |
| **HITL Interface** | `frontend/components/HITLDialog.tsx` | 운영자 응답 UI |
| **WebSocket Hook** | `frontend/hooks/useWebSocket.ts` | Socket.IO 연결 관리 |

---

## 🔐 보안 및 프라이버시

### 인증 및 권한

- ✅ **JWT 토큰** - API 인증
- ✅ **OAuth2** - 소셜 로그인
- ✅ **RBAC** - 역할 기반 접근 제어 (Admin/Operator/Viewer)
- ✅ **WebSocket 인증** - 토큰 기반

### 데이터 보안

- ✅ **TLS/SSL** - 모든 외부 연결 암호화
- ✅ **환경 변수** - 민감 정보 관리
- ✅ **Database 암호화** - 저장 데이터 암호화
- ✅ **로그 마스킹** - PII 정보 마스킹

### 컴플라이언스

- ✅ **통화 녹음 동의** - 설정 가능
- ✅ **GDPR 준수** - 데이터 보관 정책
- ✅ **감사 로그** - 운영자 작업 기록

---

## 📈 모니터링 및 관찰성

### Prometheus 메트릭

**통화 메트릭**:
- `active_calls_total` - 현재 활성 통화 수
- `call_duration_seconds` - 통화 시간 히스토그램
- `ai_activated_calls_total` - AI 응대 통화 수

**AI 메트릭**:
- `ai_response_time_seconds` - AI 응답 시간
- `ai_confidence_score` - AI 신뢰도 분포
- `rag_search_time_seconds` - RAG 검색 지연

**HITL 메트릭**:
- `hitl_requests_total` - HITL 요청 수
- `hitl_response_time_seconds` - 운영자 응답 시간
- `hitl_queue_size` - 대기 큐 크기

**비용 메트릭**:
- `llm_tokens_used_total` - LLM 토큰 사용량
- `stt_duration_seconds_total` - STT 오디오 길이
- `tts_characters_total` - TTS 문자 수

### 구조화된 로그 (structlog)

```json
{
  "timestamp": "2026-03-10T10:30:45.123Z",
  "level": "info",
  "event": "ai_response_time_breakdown",
  "call_id": "abc-123",
  "rag_search_ms": 75.2,
  "llm_generation_ms": 412.8,
  "tts_first_chunk_ms": 235.1,
  "total_response_ms": 923.5
}
```

---

## 🚀 배포 옵션

### 개발 환경

```bash
# 전체 시스템 실행
.\start-all.ps1

# Frontend: http://localhost:3000
# API: http://localhost:8000
# WebSocket: ws://localhost:8001
```

### 프로덕션 환경

**옵션 1: 단일 서버**
- Ubuntu 22.04 LTS
- 8 CPU, 16GB RAM
- Docker + Docker Compose
- Nginx reverse proxy

**옵션 2: Kubernetes**
- Frontend: Vercel / Netlify
- Backend: GKE / EKS
- Database: Cloud SQL / RDS
- Vector DB: Pinecone Cloud

**옵션 3: 하이브리드**
- Frontend: Vercel (CDN)
- Backend: On-premise VM
- AI Services: Google Cloud
- Vector DB: Self-hosted ChromaDB

---

## 📚 관련 문서

### 핵심 문서

| 문서 | 설명 |
|------|------|
| **[README.md](../README.md)** | 프로젝트 개요 및 빠른 시작 |
| **[INDEX.md](INDEX.md)** | 전체 문서 인덱스 |
| **[QUICK_START.md](QUICK_START.md)** | 5분 설치 가이드 |

### 아키텍처 문서

| 문서 | 설명 |
|------|------|
| **[architecture/ai-voicebot-architecture.md](architecture/ai-voicebot-architecture.md)** | AI Voicebot 완전한 설계 (5,000+ lines) |
| **[architecture/frontend-architecture.md](architecture/frontend-architecture.md)** | Frontend 상세 설계 (2,300+ lines) |
| **[architecture/voice-ai-conversation-engine.md](architecture/voice-ai-conversation-engine.md)** | Voice AI 대화 엔진 |

### 설계 문서

| 문서 | 설명 |
|------|------|
| **[design/TTS_RTP_AND_STT_QUEUE_DESIGN.md](design/TTS_RTP_AND_STT_QUEUE_DESIGN.md)** | TTS→RTP 파이프라인, PCM 큐 설계 |
| **[design/TTS_RTP_STRUCTURE_REVIEW.md](design/TTS_RTP_STRUCTURE_REVIEW.md)** | TTS→큐→RTP 구조 검토 및 이슈 분석 |
| **[design/OPERATOR-AWAY-MODE-DESIGN.md](design/OPERATOR-AWAY-MODE-DESIGN.md)** | 운영자 부재중 모드 상세 설계 |

### 가이드

| 문서 | 설명 |
|------|------|
| **[guides/USER_MANUAL.md](guides/USER_MANUAL.md)** | 사용자 매뉴얼 |
| **[guides/TROUBLESHOOTING.md](guides/TROUBLESHOOTING.md)** | 문제 해결 가이드 |
| **[guides/google-api-setup.md](guides/google-api-setup.md)** | Google Cloud API 설정 |

---

## 🎯 사용 사례

### 1. 소규모 기업 접수 자동화

**문제**: 영업시간 외 고객 문의 누락
**해결**: AI 자동 응답으로 24시간 응대
**효과**: 
- 고객 만족도 ↑
- 인건비 절감
- 지식 베이스 자동 구축

### 2. 콜센터 1차 응대

**문제**: 반복적인 FAQ 질문 처리 부담
**해결**: AI가 FAQ 자동 응답, 복잡한 질문만 상담원 전달
**효과**:
- 상담원 업무 부하 30% 감소
- 평균 응답 시간 60% 단축
- 고객 대기 시간 감소

### 3. 의료 기관 예약 안내

**문제**: 전화 예약 문의 집중 시간대 대응 어려움
**해결**: AI가 진료 시간, 예약 가능 시간 안내
**효과**:
- 예약 담당 인력 50% 감소
- 환자 편의성 향상
- 24시간 정보 제공

---

## 🔮 로드맵

### ✅ Phase 1: Core AI (완료)
- SIP B2BUA 구현
- AI 자동 응답
- STT/TTS/LLM 통합
- RAG 지식 검색
- 통화 녹음

### ✅ Phase 2: Frontend & HITL (완료)
- 웹 대시보드
- 실시간 모니터링
- 지식 베이스 관리
- Human-in-the-Loop
- 통화 이력 관리 (발신/종료/녹음)

### 🚧 Phase 3: 고급 기능 (진행중)
- [ ] 멀티 언어 지원
- [ ] 고급 분석 대시보드
- [ ] CRM 연동
- [ ] A/B 테스트 프레임워크
- [ ] 모바일 앱

### 🌟 Phase 4: Enterprise (계획)
- [ ] 멀티 테넌트 지원
- [ ] SSO 통합
- [ ] 커스텀 AI 모델 학습
- [ ] 화이트 라벨 프론트엔드
- [ ] Enterprise SLA

---

## 📞 지원 및 문의

- **Issues**: [GitHub Issues](https://github.com/hak023/sip_pbx/issues)
- **Discussions**: [GitHub Discussions](https://github.com/hak023/sip_pbx/discussions)
- **Email**: hak023@example.com

---

## 📄 라이선스

MIT License - 자세한 내용은 [LICENSE](../LICENSE) 참조

---

**Built with ❤️ by Winston (Architect) & Team**

*최종 업데이트: 2026-03-10*
