# 모르는 내용 응답 및 후처리(확인 필요) 설계

## 1. 개요

- **목적**: AI가 답을 모를 때 고정 문구로 응답하고, "확인 후 연락드리겠다"는 플로우를 유도한 뒤, 운영자가 나중에 **후처리(확인·연락)** 할 수 있도록 기록·노출한다.
- **범위**: LLM 응답 문구 통일, 후처리 저장/조회 API, 대시보드 "확인 필요" 목록 및 상태 변경.

---

## 2. 모르는 내용 응답 문구 (TTS_RTP_AND_HITL_DESIGN.md와 연동)

### 2.1 고정 멘트 (TTS/사용자 청취)

**설계**: 모르는 내용 시 **"잠시만 기다려 주세요"** 한 문장만 TTS로 재생한 뒤 **HITL 요청**을 보낸다 (담당자 개입).

- **문구**:  
  `해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요.`
- **의도**: 사용자에게 짧게 안내한 뒤 HITL로 운영자에게 문의하고, 동시에 후처리(확인 필요) 항목으로 저장한다.

### 2.2 적용 위치

- **`generate_response.py`**
  - 시스템 프롬프트: 모르는 내용일 때 위 문구("해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요.")만 사용하라고 명시.
  - **고정 fallback**: (RAG 없음/에러/API 오류 등으로) 모르는 내용용 응답을 할 때는 위 문구를 그대로 반환.
  - 이때 **needs_follow_up=True** 로 설정.
- **`hitl_alert.py`**
  - **needs_follow_up** 가 True이면 **needs_human=True** 로 HITL 요청 (설계: 잠시만 기다려 주세요 후 HITL).
  - confidence &lt; 0.3 또는 transfer/complaint 등 기존 조건도 유지.

---

## 3. 후처리(확인 필요) 플로우

### 3.1 시나리오

1. 사용자: "○○ 예약 가능한가요?"
2. AI: (지식 없음) → 위 고정 멘트 TTS 재생.
3. 시스템: 이 턴을 **"확인 필요"** 로 기록 (call_id, 사용자 발화, AI 응답문, 시각).
4. 운영자: 대시보드 **"확인 필요"** 목록에서 해당 건을 보고, 메모·연락 완료·처리 완료 등으로 후처리.

### 3.2 데이터 모델

**테이블: `pending_follow_ups`**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | UUID PK | 요청 ID |
| call_id | VARCHAR(255) | 통화 ID |
| caller_id | VARCHAR(100) | 발신자 식별 (선택) |
| callee_id | VARCHAR(100) | 착신자(테넌트) |
| user_question | TEXT | 사용자가 물어본 내용 (확인할 사항) |
| ai_response | TEXT | AI가 한 응답 (고정 멘트) |
| status | VARCHAR(20) | pending \| noted \| contacted \| resolved |
| operator_note | TEXT | 운영자 메모 |
| created_at | TIMESTAMP | 생성 시각 |
| updated_at | TIMESTAMP | 수정 시각 |
| resolved_at | TIMESTAMP | 처리 완료 시각 (선택) |

- **status**
  - `pending`: 미확인
  - `noted`: 메모만 작성
  - `contacted`: 고객 연락 완료
  - `resolved`: 후처리 완료

### 3.3 저장 시점

- **LangGraph**  
  - `generate_response_node`에서 "모르는 내용" 응답을 낸 경우  
    `needs_follow_up=True`, `follow_up_user_query=user_query` 반환.
- **Agent**  
  - 그래프 결과에 `needs_follow_up`, `follow_up_user_query` 포함해 반환.
- **RAG Processor (Pipecat)**  
  - Agent 결과에 `needs_follow_up`가 있으면  
    **Follow-up 서비스**를 호출해 `pending_follow_ups`에 1건 INSERT  
    (call_id, caller_id, callee_id, user_question, ai_response, status=’pending’).

### 3.4 API

- **GET /api/follow-ups**  
  - 목록 조회 (테넌트/callee_id 또는 전역).  
  - 쿼리: `status`, `call_id`, `limit`, `offset`.  
  - 응답: `{ "items": [...], "total": N }`.
- **PATCH /api/follow-ups/{id}**  
  - `status`, `operator_note` 등 업데이트 (후처리).

(필요 시 POST는 저장을 파이프라인에서만 하고, 운영자 조회/수정만 API로 할 수 있음.)

### 3.5 프론트엔드

- **"확인 필요(후처리)" 영역**
  - GET /api/follow-ups로 목록 표시.
  - 컬럼: 통화 ID, 사용자 질문(확인할 사항), AI 응답 요약, 상태, 생성일, [메모], [연락 완료], [처리 완료].
  - 행 클릭 또는 모달에서 메모 입력, 상태를 noted/contacted/resolved로 변경 (PATCH).

---

## 4. 기존 HITL과의 관계

- **HITL**: 통화 중 즉시 운영자 개입이 필요한 경우 (예: confidence 낮음, 위험 발화).
- **후처리(확인 필요)**: AI가 "모른다"고 하고, "확인 후 연락드리겠다"고 한 건을 **나중에** 처리하는 경우.
- 저장 테이블을 분리(`pending_follow_ups`)하여, HITL 미처리 목록과 확인 필요 목록을 각각 조회·표시할 수 있게 한다.

---

## 5. 구현 체크리스트

- [x] `generate_response.py`: 고정 멘트 상수 `RESPONSE_UNKNOWN_NEEDS_FOLLOWUP`, 프롬프트 반영, `needs_follow_up`/`follow_up_user_query` 반환.
- [x] Migration: `migrations/003_create_pending_follow_ups.sql` — `pending_follow_ups` 테이블 생성.
- [x] Follow-up 서비스: `src/services/follow_up_service.py` — `save_pending_follow_up()`, `list_pending_follow_ups()`, `update_follow_up()`.
- [x] LangGraph state: `needs_follow_up`, `follow_up_user_query` 추가. Agent 반환값에 포함.
- [x] RAG Processor: Agent 결과 `needs_follow_up` 시 `get_follow_up_service().save_pending_follow_up()` 호출.
- [x] API: GET `/api/call-history/follow-ups`, PATCH `/api/call-history/follow-ups/{id}`.
- [x] Frontend: 대시보드 "확인 필요 (후처리)" 섹션 — 목록, 상태 필터, 메모/연락 완료/처리 완료 버튼.

---

**문서 버전**: 1.0  
**작성일**: 2026-02-21  
**구현 완료**: 2026-02-21
