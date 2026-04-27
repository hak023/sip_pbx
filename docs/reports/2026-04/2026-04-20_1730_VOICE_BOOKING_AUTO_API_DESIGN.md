# 음성 예약 자동 확정(HITL 없음) — API·DB 연동 설계

- **작성일**: 2026-04-20 (로컬)
- **상태**: 구현 반영 — 상세는 `2026-04-20_1538_VOICE_BOOKING_AUTO_IMPL.md` 참고.
- **근거 분석**: `2026-04-20_1600_CID_DOCK_AND_VOICE_RESERVATION_GAP.md` §2 (RAG만으로는 예약 미확정)
- **전제**: PBX 내 이미 존재하는 **`booking_service` + SQLite `bookings` / `booking_slots`**, REST **`/api/booking/*`**, LangGraph **`booking_agent_node`** + **`BOOKING_TOOLS`**(서비스 레이어 직접 호출, HTTP 우회)를 **단일 진실 소스**로 한다. HITL 승인 없이 **도구 호출 성공 시 DB 커밋 = 예약 확정**으로 정의한다.

---

## 1. 목표와 비목표

### 1.1 목표

| ID | 내용 |
|----|------|
| G1 | 발화가 **예약 트랜잭션**에 해당하면 **`intent=booking` + `utterance_lane=booking`** 으로 라우팅되어 **`booking_agent_node`** 가 **슬롯 조회·예약 생성·변경·취소**를 **도구로만** 수행한다. |
| G2 | 예약/조회/실패의 **전 구간**이 **`app.log`(structlog)** 및 **`call_data_record_*.log`** 에 **구조화 이벤트**로 남아, 통화별 사후 분석·알림이 가능하다. |
| G3 | 고객에게는 **확인 발화 후 `create_booking_tool`**(기존 시스템 프롬프트 규칙)로 **STT 오류 리스크**를 완화한다. |
| G4 | 테넌트(`owner` = 착신 내선)별 **`booking_settings`·슬롯 데이터**가 없을 때는 **명시적 안내**만 하고 DB에 쓰지 않는다. |

### 1.2 비목표 (본 설계 범위 밖)

- 외부 POS/외부 캘린더를 **유일** 진실원으로 하는 이중 기록(별도 동기화 프로젝트).
- HITL 큐에 예약 요청을 올리는 **인간 승인** 워크플로(요청사항은 “없음”).

---

## 2. 현행 아키텍처 요약 (재사용)

```
[STT] → RAGLLMProcessor / ConversationAgent
         → LangGraph: classify_intent → …
         → intent=="booking" & utterance_lane=="booking"
              → booking_agent_node
                    → LLM + bind_tools(BOOKING_TOOLS)
                    → booking_tools.* → booking_service.*
                    → SQLite (booking.db) + (선택) Google Calendar 훅
```

- **저장**: `src/services/booking_service.py` — `create_booking`, `list_slots`, 중복 방지, 정원 초과 시 `ValueError` 등.
- **도구**: `src/ai_voicebot/langgraph/tools/booking_tools.py` — `check_available_slots`, `create_booking_tool`, `reschedule_booking_tool`, `cancel_booking_tool`, …
- **에이전트**: `src/ai_voicebot/langgraph/nodes/booking_agent.py` — 히스토리, 발신번호 주입, 확인 발화 규칙, `booking_context` 갱신.
- **그래프**: `src/ai_voicebot/langgraph/agent.py` — `booking_agent` → `update_state` 직결(**`hitl_alert` 미경유**).

**갭(분석 리포트와 일치)**: 동일 발화가 **`question` + RAG**로 가면 **도구가 호출되지 않아** “말로만 예약된 것처럼” 보인다. 설계의 핵심은 **라우팅 보강**과 **관측 가능성(리포팅)** 이다.

---

## 3. 기능 설계

### 3.1 의도·레인 라우팅 (필수)

**문제**: “예약하려고 하는데요”, “오늘 7시 예약”이 `question`으로 분류되면 RAG 경로로 이탈한다.

**대응 (단계적, 상호 배타 우선순위 제안)**:

1. **규칙 보강 (`classify_intent` / `route_utterance`)**  
   - 날짜·시각 엔티티 + 예약 키워드(예약/잡아주/자리/테이블/n명/시) 동시 존재 시 **`booking` 우선** 후보.  
   - `booking_context` 활성 시(이미 `booking_agent` 대화 중) 후속 발화는 **`booking` 고정**에 가깝게 유지(현 코드 힌트 확장).

2. **경량 슬롯 감지기(옵션, LLM 부담↓)**  
   - 정규식·간단 NER로 `slot_date` / `slot_time` 후보 추출 → 후보만 있어도 **`utterance_lane=booking`** 후보로 올리고, `classify_intent` 3차 LLM에 **“슬롯 후보 있음”** 플래그 전달.

3. **피처 플래그**  
   - `BOOKING_VOICE_INTENT_STRICT=1` 일 때: 위 규칙 만족 시 **`question` 덮어쓰기 금지**가 아니라, **동점이면 `booking`**.

**수용 기준**: `call_data_record` 상 동일 시나리오에서 `intent_classify`의 `path`가 **`booking_lane`**(또는 동등 명칭)으로 기록되고, **`booking_agent_node_enter`** 가 최소 1회 이상 찍힌다.

### 3.2 트랜잭션 시나리오 (HITL 없음)

| 시나리오 | 도구(예) | DB/비고 |
|----------|-----------|---------|
| 가용 조회 | `check_available_slots` / `check_multi_date_slots` | 읽기 전용 |
| 신규 확정 | `get_booking_settings` → 확인 발화 → `create_booking_tool` | `bookings` INSERT + `booking_slots.booked_count` 증가(트랜잭션) |
| 중복 시도 | `create_booking_tool` | `ValueError` → JSON `error` → TTS 안내 |
| 일정 변경 | `reschedule_booking_tool` | 원자적 슬롯 이동(기존 설계 준수) |
| 취소 | `cancel_booking_tool` | 상태/정원 복구 |

**확인 발화**: 기존 `_BOOKING_SYSTEM_PROMPT` 유지. 자동 확정이라도 **한 번의 고객 긍정**은 필수(정책 변경 시 별도 문서).

### 3.3 `owner` / `caller` / `call_id` 바인딩

- **`owner`**: 통화 컨텍스트의 착신 테넌트(현재 `state._owner`와 동일 원칙).  
- **`customer_phone`**: SIP 발신 식별 가능 시 **자동 주입**(기존 `booking_agent` 동작 유지).  
- **`call_id`**: `create_booking_tool`에 전달되어 `bookings.call_id` 연계 → 통화 이력 API `has_booking`과 일치.

---

## 4. 리포팅 설계 (`app.log` + `call_data_record`)

### 4.1 원칙

- **도구 경계**마다 1행: 조회/시도/성공/실패를 분리해 원인 추적 가능하게 한다.  
- **PII**: 전화번호·이름은 **로그에 마스킹**(예: 뒤 4자리) 또는 **해시**; 파일 로그 정책 준수.

### 4.2 `call_data_record` 이벤트 스키마 (제안)

`log_call_data(call_id, "booking", "<event>", **kwargs)` 통일.

| event | 필수 필드 예시 | 설명 |
|-------|----------------|------|
| `booking_intent_routed` | `intent`, `utterance_lane`, `from_intent` | RAG에서 booking으로 붙잡았는지 |
| `booking_agent_enter` | `owner`, `history_count` | 노드 진입(기존 structlog와 중복 시 하나로 합칠지 결정) |
| `booking_tool_start` | `tool`, `arg_keys` | 도구 호출 직전 |
| `booking_tool_done` | `tool`, `ok`, `duration_ms`, `summary` | JSON 일부 요약(길이 제한) |
| `booking_committed` | `booking_id`, `slot_date`, `slot_time`, `party_size` | **성공 커밋** |
| `booking_rejected` | `reason_code`, `detail` | 정원 초과/중복/슬롯 없음/검증 실패 |

**`app.log`**: 기존 `booking_tool_*`, `booking_created`, `booking_agent_*` 와 **필드명·키 맞춤** 또는 한 채널로 통합해 중복 검색 방지.

### 4.3 대시보드·운영

- 통화 종료 후: `GET /api/call-history/.../bookings` 로 이미 연계 가능 → Dock/대시보드에 **`has_booking`** 표시 연동 검증.  
- 알림(옵션): `booking_committed` 시 WebSocket `booking_confirmed` 브로드캐스트(프론트 배지용).

---

## 5. 설정·가드레일

| 항목 | 제안 |
|------|------|
| 기능 토글 | 환경변수 `BOOKING_VOICE_ENABLED` (기본 on) — off 시 `booking`이어도 안내 문구만. |
| 슬롯 없음 | `check_*` 결과 empty → **RAG로 “전화 예약만 가능” 허위 확정 금지** 문구 템플릿. |
| 동시 통화 | SQLite `BEGIN IMMEDIATE` 이미 사용 — 동일 슬롯 경쟁은 DB가 직렬화. |
| LLM 도구 루프 | `_MAX_TOOL_ROUNDS` 초과 시 **명시적 실패 이벤트** + TTS “다시 시도”. |

---

## 6. 구현 단계 (권장 순서)

1. **P0 라우팅**: `classify_intent` / `route_utterance`에서 **예약+시각/날짜** 패턴 → `booking` + `utterance_lane=booking` 보강 + `call_data`에 `booking_intent_routed`.  
2. **P1 관측**: `booking_tools` 또는 `_execute_tool` 래퍼에서 **`log_call_data` + structlog** 일원화.  
3. **P2 회귀 테스트**: 시나리오 스크립트(“예약하려고” → “7시” → “네”)로 **DB row 존재** 검증.  
4. **P3 UX**: 실패 코드별 짧은 TTS 문구 테이블; `confirmation_msg` 템플릿과 TTS 일치 확인.

---

## 7. 변경 이력 (문서)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/docs/reports/2026-04/2026-04-20_1730_VOICE_BOOKING_AUTO_API_DESIGN.md` | 추가 | 음성 예약 자동 API·리포팅 설계 |

---

## 8. 주요 결정 사항

- **HITL 없음**: 확정은 **`create_booking_tool` 성공**으로 정의; 인간 큐는 사용하지 않는다.  
- **HTTP 불필요**: 음성 파이프라인은 이미 **Python `booking_service`** 직접 호출 — 동일 프로세스 내 일관성·지연 최소화.  
- **리포팅은 제품 요구사항**: RAG 응답이 아니라 **`booking_*` 이벤트**로 “실제로 예약됐는지”를 증명한다.

---

## 9. 잔여 과제 (설계 후 결정 필요)

- `question`과 `booking`이 **동시에** 켜지는 하이브리드(“메뉴 추천하고 7시 예약”) 처리: 단일 턴 vs 다턴 분해.  
- 다국어 STT 시 날짜 엔티티 정규화 품질 모니터링.
