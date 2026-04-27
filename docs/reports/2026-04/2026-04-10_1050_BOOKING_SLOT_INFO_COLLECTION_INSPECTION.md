# 예약 슬롯 필수 정보 수집 로직 점검 리포트

- 작성일: 2026-04-10
- 상태: 버그 1건 수정 완료
- 관련 경로: `sip-pbx/src/ai_voicebot/langgraph/`

---

## 개요

고객이 비어있는 슬롯에 예약을 시도할 때 AI가 날짜·시간을 포함한 슬롯 필수 정보를 수집하는 로직이 올바르게 동작하는지 점검했다. 점검 결과 **라우팅 버그 1건** 발견 및 수정, **구조적 미연동 이슈 2건** 식별했다.

---

## 슬롯 필수 정보 수집 로직 현황

### 수집 대상 필드 (booking_agent.py)

| 필드 | 수집 방법 | 자동화 |
|------|-----------|--------|
| `slot_date` (날짜) | LLM이 고객 발화에서 추출 → YYYY-MM-DD | 없음 (LLM 의존) |
| `slot_time` (시각) | LLM이 고객 발화에서 추출 → HH:MM | 없음 (LLM 의존) |
| `party_size` (인원) | LLM이 고객 발화에서 추출 | 없음 |
| `customer_name` (이름) | LLM이 고객 발화에서 추출 | 없음 |
| `customer_phone` (전화번호) | 발신자 번호 자동 주입 | **있음** (caller_number) |

### 대화 흐름

1. `classify_intent` → `booking` 인텐트 분류
2. `route_utterance` → `utterance_lane="booking"`, `rag_mode="skip"` 설정
3. *(수정 후)* `booking_agent` → LLM + function calling 루프 실행
4. `_BOOKING_SYSTEM_PROMPT`에 정의된 순서로 정보 수집:
   - 날짜/시간 → 인원 → 이름 → 예약 생성 (전화번호 자동)
5. `_format_collected_slots()`가 SystemMessage에 수집 현황 주입 → LLM이 미수집 필드 파악
6. 모든 필드 수집 완료 시 `create_booking_tool` 호출

---

## 발견된 문제

### 🔴 [버그 수정] 예약 의도가 `booking_agent` 대신 `generate_response`로 라우팅되는 문제

**파일:** `sip-pbx/src/ai_voicebot/langgraph/agent.py`

**원인:**
- `route_utterance_node`는 `booking` 인텐트 감지 시 `rag_mode="skip"`, `utterance_lane="booking"`을 반환
- `_route_after_utterance()`는 `rag_mode == "skip"` 조건을 **`utterance_lane` 확인보다 먼저** 검사
- 결과적으로 `booking` 인텐트도 `generate_response`(일반 RAG 응답 노드)로 흘러가고 `booking_agent` 노드에 도달하지 못함

**수정 내용:**
```python
# 수정 전
def _route_after_utterance(state):
    if state.get("outbound_purpose"):
        return "generate_response"
    if state.get("rag_mode") == "skip":
        return "generate_response"   # booking도 여기서 빠져나감 (버그)
    return _route_after_intent(state)

# 수정 후
def _route_after_utterance(state):
    if state.get("outbound_purpose"):
        return "generate_response"
    if state.get("utterance_lane") == "booking":   # 추가: booking 먼저 분기
        return "booking_agent"
    if state.get("rag_mode") == "skip":
        return "generate_response"
    return _route_after_intent(state)
```

---

### 🟡 [구조적 미연동] `booking_settings`의 `require_phone`/`require_name` 미사용

**파일:** `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` - `_get_booking_settings()`

`booking_settings` DB에는 `require_phone`, `require_name` 같은 필수 여부 설정이 있으나, `_get_booking_settings` Tool이 LLM에 반환하는 JSON에 포함되지 않는다. AI는 항상 고정된 5개 필드를 수집하며, 테넌트 설정을 반영하지 못한다.

**현재 동작:** AI가 항상 `slot_date`, `slot_time`, `customer_name`, `customer_phone`, `party_size` 5개를 수집  
**이상적 동작:** `require_phone=false`이면 전화번호를 묻지 않는 등 설정 반영

---

### 🟡 [구조적 미연동] 도메인(booking_domains)별 추가 필드 AI 미연결

**파일:** `sip-pbx/src/ai_voicebot/langgraph/tools/booking_tools.py` - `_get_booking_settings()`

`booking_domains` 테이블에 도메인별 `required_fields`/`optional_fields`(예: 미용실 → 시술사 선택, 식당 → 테이블 위치)가 있으나, AI Tool이 이를 읽지 않는다. 슬롯의 `domain_id`도 예약 대화 중에 안내·선택하는 경로가 없다.

---

## 변경 이력

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/ai_voicebot/langgraph/agent.py` | 수정 | `_route_after_utterance`에서 `utterance_lane=="booking"` 우선 분기 추가 | 버그 수정 |

---

## 주요 결정 사항

- `utterance_lane`은 `route_utterance_node`에서 의도 전용으로 설정하는 값이므로, `rag_mode`보다 먼저 확인하는 것이 의미상 올바름
- `rag_mode=="skip"`은 chitchat/out_of_scope용 빠른 경로이며, booking과 분리되어야 함

---

## 잔여 과제

1. `_get_booking_settings` Tool에 `require_phone`, `require_name` 등 AI 수집 정책 필드 추가
2. `booking_domains` 추가 필드를 AI 예약 대화에 연동 (도메인별 동적 필드 수집)
3. 실제 통화 로그에서 `booking_agent_node_enter` 로그 확인으로 수정 전/후 라우팅 검증
