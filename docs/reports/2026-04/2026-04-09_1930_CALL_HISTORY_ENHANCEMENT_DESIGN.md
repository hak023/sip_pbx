# 통화 이력 고도화 설계서

- **작성일**: 2026-04-09 19:30
- **상태**: 설계 완료 (구현 대기)
- **관련 문서**: `docs/reports/2026-04/2026-04-09_1400_VOICEBOT_TOOL_EXPANSION_BEYOND_BOOKING.md` (E-3)

---

## 1. 현황 분석

### 1-1. 현재 데이터 소스 구조

```
통화 이력 목록  ← recordings/{call_id}/metadata.json    (파일 스캔)
통화 상세 요약  ← recordings/{call_id}/call_insights.json
CDR 디버그     ← logs/call_data_record_YYYYMMDD.log    (JSONL 검색)
대본           ← recordings/{call_id}/transcript.txt
예약 정보      ← SQLite bookings 테이블 (call_id 컬럼 있음, 연결 미구현)
```

### 1-2. 현재 화면 표시 항목 (CallDetailPanel)

| 항목 | 문제점 |
|------|--------|
| 통화 요약 (call_summary) | 유지 |
| **착신자 시점 요약 (callee_summary)** | **불필요 → 제거** |
| 통화 ID | 내부용 → 목록 뷰에서 제거 (상세/디버그에는 유지) |
| CDR 로그 (raw JSON 타임라인) | 개발자용이나 개발 단계에선 유용 → 유저 친화적 뷰 추가 |
| AI 미처리 항목 | 하단에 답변 전송 기능 없음 → 추가 필요 |
| 예약 정보 | 미연결 → 연결 필요 |

### 1-3. CDR 이벤트 카테고리 (실제 로그 기준)

| category | 주요 event | 유저 표시 |
|----------|-----------|---------|
| `call_event` | `call_connected`, `call_disconnected`, `transfer_request_detected` | 통화 시작/종료/전환 |
| `stt` | `stt_final`, `stt_bypass_final`, `stt_post_filter_dropped` | 고객 발화 인식 |
| `tts` | `tts_text_pushed`, `greeting_phase1_sent` | AI 응답 발화 |
| `llm` | `llm_exchange`, `knowledge_judgement` | LLM 처리 |
| `rag` | `rag_search_done` | 지식 검색 |
| `knowledge` | `post_call_extraction_started/finished` | KB 추출 |
| `hitl` | `hitl_requested`, `hitl_response_received` | 인간 개입 |
| `timing` | `intent_classify`, `agent_graph_total` | 처리 시간 |

---

## 2. 고도화 요구사항 정리

| # | 요구사항 | 방향 |
|---|---------|------|
| 1 | DB로 통화 이력 관리 | SQLite `call_records` 테이블 신설 |
| 2 | 통화 ID를 뷰에서 제거 | 목록/기본 상세에서 숨기기, 디버그 탭에서만 노출 |
| 3 | 착신자 시점 요약 제거 | UI·API 응답에서 제거 |
| 4 | CDR을 유저 친화적으로 표시 | "처리 타임라인" 섹션 신설 |
| 5 | AI 미처리 → 답변 전송 | Textbox + 전송 버튼, 전송 후 비활성화 |
| 6 | 예약 정보 연결 | `bookings.call_id` 기준 JOIN |

---

## 3. DB 설계

### 3-1. `call_records` 테이블 (SQLite, booking DB와 동일 파일)

```sql
CREATE TABLE IF NOT EXISTS call_records (
    call_id         TEXT    PRIMARY KEY,
    owner           TEXT    NOT NULL DEFAULT '',   -- callee_id (테넌트)
    caller_id       TEXT    NOT NULL DEFAULT '',
    callee_id       TEXT    NOT NULL DEFAULT '',
    direction       TEXT    NOT NULL DEFAULT 'inbound',  -- inbound | outbound
    start_time      TEXT,                          -- ISO 8601
    end_time        TEXT,
    duration        REAL,                          -- 초
    call_summary    TEXT    DEFAULT '',            -- LLM 통화 요약
    is_ai_handled   INTEGER NOT NULL DEFAULT 0,   -- 0/1
    ai_unhandled_count  INTEGER NOT NULL DEFAULT 0,
    has_recording   INTEGER NOT NULL DEFAULT 0,
    has_transcript  INTEGER NOT NULL DEFAULT 0,
    recordings_dir  TEXT    DEFAULT '',            -- recordings 폴더 경로
    extra_data      TEXT    NOT NULL DEFAULT '{}', -- JSON: 예약 ID 등 확장
    created_at      TEXT    DEFAULT (datetime('now')),
    updated_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_call_records_owner     ON call_records(owner);
CREATE INDEX IF NOT EXISTS idx_call_records_start     ON call_records(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_call_records_caller    ON call_records(caller_id);
```

### 3-2. `call_unhandled_items` 테이블

AI가 응대하지 못한 항목별 관리 + 답변 전송 상태 추적.

```sql
CREATE TABLE IF NOT EXISTS call_unhandled_items (
    item_id         TEXT    PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    call_id         TEXT    NOT NULL REFERENCES call_records(call_id) ON DELETE CASCADE,
    question        TEXT    NOT NULL DEFAULT '',
    kind            TEXT    NOT NULL DEFAULT 'needs_follow_up',  -- needs_follow_up | hitl_escalation
    ai_confidence   REAL,
    reply_text      TEXT    DEFAULT '',   -- 운영자가 작성/수정한 답변
    reply_sent      INTEGER NOT NULL DEFAULT 0,   -- 0=미전송, 1=전송완료
    reply_sent_at   TEXT,
    reply_method    TEXT    DEFAULT '',   -- sms | email | manual
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_unhandled_call ON call_unhandled_items(call_id);
CREATE INDEX IF NOT EXISTS idx_unhandled_sent ON call_unhandled_items(reply_sent);
```

### 3-3. 기존 `bookings` 테이블 활용

`bookings.call_id` 컬럼이 이미 존재하므로 JOIN으로 연결 (스키마 변경 불필요).

```sql
-- 통화별 예약 조회
SELECT b.* FROM bookings b WHERE b.call_id = ?;
```

---

## 4. API 설계

### 4-1. 기존 파일 스캔 방식 유지 전략

완전 마이그레이션 대신 **하이브리드 전략**을 채택한다.
- 통화 시작/종료 시 `call_records` 테이블에 upsert
- 목록 조회는 DB 우선, DB에 없으면 파일 스캔 fallback
- 점진적 마이그레이션으로 기존 데이터 손실 없음

### 4-2. 신규/변경 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/call-history` | **DB 우선** + 파일 스캔 fallback (기존과 동일 응답 스키마) |
| `GET` | `/api/call-history/{call_id}` | 단건 상세 (call_id 뷰에서 제거, API에는 유지) |
| `GET` | `/api/call-history/{call_id}/debug-trace` | CDR 로그 (기존 유지) |
| `GET` | `/api/call-history/{call_id}/bookings` | **신규** — 통화 연결 예약 목록 |
| `GET` | `/api/call-history/{call_id}/unhandled` | **신규** — AI 미처리 항목 목록 |
| `PUT` | `/api/call-history/{call_id}/unhandled/{item_id}/reply` | **신규** — 답변 저장 + 전송 |

### 4-3. `PUT /api/call-history/{call_id}/unhandled/{item_id}/reply` 명세

```json
// 요청 Body
{
  "reply_text": "안녕하세요, 고객님이 문의하신 주차 관련 답변입니다...",
  "send": true   // true이면 발송 처리 (SMS/manual), false이면 저장만
}

// 응답
{
  "ok": true,
  "item_id": "abc123",
  "reply_sent": true,
  "reply_sent_at": "2026-04-09T19:30:00"
}
```

---

## 5. CDR 유저 친화적 뷰 설계 ("처리 타임라인")

### 5-1. 이벤트 → 유저 표시 매핑

CDR의 raw JSON을 파싱하여 유저가 이해할 수 있는 타임라인으로 변환한다.

| category | event | 타임라인 표시 | 아이콘 |
|----------|-------|-------------|--------|
| `call_event` | `call_connected` | 통화 시작 | 📞 |
| `call_event` | `call_disconnected` | 통화 종료 | 📵 |
| `call_event` | `transfer_request_detected` | 상담원 연결 요청 | 🔀 |
| `call_event` | `call_transfer_initiated` | 상담원 연결 완료 | ✅ |
| `stt` | `stt_final` / `stt_bypass_final` | 고객 발화: "..." | 🎙 |
| `tts` | `tts_text_pushed` | AI 응답: "..." | 🔊 |
| `tts` | `greeting_phase1_sent` | AI 오프닝 인사 | 👋 |
| `llm` | `llm_exchange` | AI 처리 (${agent_elapsed}초) | 🤖 |
| `rag` | `rag_search_done` | 지식 검색 (${result_count}건) | 🔍 |
| `hitl` | `hitl_requested` | 운영자 질문 전달 | 🙋 |
| `hitl` | `hitl_response_received` | 운영자 답변 수신 | 💬 |
| `knowledge` | `post_call_extraction_finished` | 통화 후 지식 추출 (${stored_count}건) | 📚 |
| `timing` | `intent_classify` | 의도 분류 (${elapsed_sec}초) | ⏱ |

### 5-2. 뷰 구성

```
[처리 타임라인 탭] | [원본 CDR 탭 - 개발자용]

처리 타임라인:
─────────────────────────────────────────────
13:14:43  📞  통화 시작 (수신 · 1004→1003)
13:14:48  👋  AI 오프닝 인사
13:15:01  🎙  고객: "예약하고 싶어요"
13:15:02  ⏱  의도 분류: 0.21초
13:15:03  🤖  AI 처리: 1.8초
13:15:05  🔊  AI: "네, 몇 분으로 예약해 드릴까요?"
13:15:12  🎙  고객: "3명이요"
...
13:16:30  📵  통화 종료 (106초)
─────────────────────────────────────────────
```

### 5-3. 처리 흐름 요약 카드

타임라인 상단에 통화 흐름을 요약 카드로 표시:

```
┌──────────────────────────────────────────────┐
│  통화 흐름 요약                               │
│  발화 횟수: 고객 8회 / AI 7회                │
│  평균 AI 응답: 2.1초   최대: 4.8초           │
│  지식 검색: 3회   히트: 2회                  │
│  의도: booking × 6, question × 2             │
└──────────────────────────────────────────────┘
```

---

## 6. AI 미처리 항목 답변 전송 설계

### 6-1. UI 흐름

```
AI가 응대하지 못한 내용 (2건)
┌─────────────────────────────────────────────┐
│ ① 주차 가능 여부                            │
│    [LLM이 생성한 답변 초안이 여기 표시됨]   │
│    ┌─────────────────────────────────────┐  │
│    │ 지하 1층에 무료 주차가 가능합니다.   │  │  ← 수정 가능 textarea
│    └─────────────────────────────────────┘  │
│    [📤 고객에게 전송]   [저장만]            │
│                                              │
│ ② 영업 종료 시간                            │
│    ┌─────────────────────────────────────┐  │
│    │ 오후 10시에 영업이 종료됩니다.       │  │  ← 수정 가능 textarea
│    └─────────────────────────────────────┘  │
│    [📤 고객에게 전송]   [저장만]            │
└─────────────────────────────────────────────┘
```

전송 완료 후:
```
│ ① 주차 가능 여부                  ✅ 전송 완료 (04-09 19:35)  │
│    지하 1층에 무료 주차가 가능합니다.   [textarea 비활성화]   │
```

### 6-2. LLM 답변 초안 생성

통화 상세 페이지 진입 시 미처리 항목에 대해 LLM이 자동으로 답변 초안 생성.

```
POST /api/call-history/{call_id}/unhandled/{item_id}/draft

// 응답
{
  "draft": "주차는 건물 지하 1층에서 2시간 무료로 이용하실 수 있습니다."
}
```

- KB RAG를 활용하여 정확한 답변 초안 생성
- 생성 불가 시 빈 textarea로 fallback (운영자 직접 작성)

### 6-3. 전송 처리

현재 개발 단계에서는 **"저장만"** 기능만 구현. 실제 발송(SMS/이메일)은 향후 연결.
- `reply_sent = 1`, `reply_method = "manual"` 로 기록
- 추후 `sip_sms_service`와 연결하여 실제 SMS 발송 가능

---

## 7. 예약 정보 연결 설계

### 7-1. 통화 상세에 예약 카드 표시

```
예약 정보
┌─────────────────────────────────────────────┐
│  예약번호: BK-20260409-001                  │
│  날짜: 2026-04-10 (토)   시간: 14:00        │
│  고객명: 홍길동    인원: 3명                │
│  상태: ✅ 확정                              │
└─────────────────────────────────────────────┘
```

- `GET /api/call-history/{call_id}/bookings` 에서 조회
- 예약이 없으면 해당 섹션 미표시

---

## 8. 목록 뷰 컬럼 변경

### 현재

| 방향 | 시작 시각 | 발신자 | 착신자 | 통화 요약 | AI여부 | 길이 | **통화ID** | 녹음 | 대본 | 미해결 |

### 변경 후

| 방향 | 시작 시각 | 발신자 | 착신자 | 통화 요약 | AI여부 | 길이 | 녹음 | 대본 | 미해결 | **예약** |

- **통화 ID** 컬럼 제거 (목록에서)
- **예약** 배지 추가 (예약 있으면 📅 배지)
- 상세 펼치기 탭에 `debug-trace`에서 통화 ID 확인 가능하도록 유지

---

## 9. 프론트엔드 컴포넌트 구조 변경

### 9-1. `CallDetailPanel` 탭 구조 도입

```
[📋 통화 요약] [📅 예약 정보] [🙋 미처리 항목] [🕐 처리 타임라인] [🔧 디버그 CDR]
```

- **통화 요약**: call_summary + 녹음 + 대본 (착신자 시점 요약 제거)
- **예약 정보**: `call_id` 기준 예약 카드 (없으면 "예약 없음")
- **미처리 항목**: AI 미처리 리스트 + 답변 textbox + 전송 버튼
- **처리 타임라인**: CDR을 유저 친화적으로 변환한 이벤트 타임라인
- **디버그 CDR**: 기존 raw CDR 테이블 (개발자용, 기본 접힘)

### 9-2. 미처리 항목 답변 State

```typescript
type UnhandledItemState = {
  item_id: string;
  question: string;
  kind: string;
  draft: string;           // LLM 초안
  replyText: string;       // 운영자 수정본
  replySent: boolean;
  replySentAt?: string;
  sending: boolean;
  draftLoading: boolean;
};
```

---

## 10. 구현 우선순위 (Phase)

| Phase | 작업 | 난이도 |
|-------|------|--------|
| **P1** | `착신자 시점 요약` 제거 (UI + API) | ★☆☆☆☆ |
| **P1** | 목록에서 `통화 ID` 컬럼 제거 | ★☆☆☆☆ |
| **P1** | CDR 처리 타임라인 뷰 (프론트 변환만) | ★★☆☆☆ |
| **P2** | AI 미처리 → 답변 textbox + 저장 API | ★★☆☆☆ |
| **P2** | LLM 답변 초안 생성 API | ★★☆☆☆ |
| **P2** | 예약 정보 연결 (bookings JOIN) | ★★☆☆☆ |
| **P3** | SQLite `call_records` 테이블 신설 | ★★★☆☆ |
| **P3** | 통화 시작/종료 시 DB upsert 연동 | ★★★☆☆ |
| **P3** | DB 기반 목록 조회 (파일 스캔 fallback 유지) | ★★★☆☆ |

---

## 11. 변경 이력

| 파일/컴포넌트 | 유형 | 요약 |
|--------------|------|------|
| `frontend/components/call-history/CallHistoryPanel.tsx` | 수정 | 통화 ID 컬럼 제거, 착신자 요약 제거, 탭 구조 도입, 미처리 답변 UI |
| `frontend/types/api.ts` | 수정 | `CallHistoryRecordItem`에서 `callee_summary` 제거, `UnhandledItem` 타입 추가 |
| `src/api/routers/call_history.py` | 수정 | `callee_summary` 응답 제거, `/bookings`, `/unhandled`, `/unhandled/{id}/reply`, `/draft` 신규 엔드포인트 |
| `src/booking/database.py` | 수정 | `call_records`, `call_unhandled_items` 테이블 추가 |
| `src/api/routers/call_history.py` | 수정 | DB 우선 목록 조회 (fallback: 파일 스캔) |
