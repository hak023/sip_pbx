# 예약 슬롯 필수 정보 수집 로직 구현 리포트

- 작성일: 2026-04-10
- 상태: 완료
- 관련 경로: `sip-pbx/src/ai_voicebot/langgraph/`
- 이전 리포트: `2026-04-10_1050_BOOKING_SLOT_INFO_COLLECTION_INSPECTION.md`

---

## 개요

점검 리포트에서 식별된 잔여 과제 3가지를 모두 구현했다.
`require_phone`/`require_name` 설정 연동, 도메인 추가 필드 AI 수집, 라우팅 검증 로그 추가가 완료되었다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `src/ai_voicebot/langgraph/tools/booking_tools.py` | 수정 | `_get_booking_settings` Tool에 수집 정책 필드 추가 |
| `src/ai_voicebot/langgraph/nodes/booking_agent.py` | 수정 | 시스템 프롬프트 수집 정책 지침 추가, `_format_settings_hint` 신규, `_format_collected_slots` 설정 반영, settings 캐싱, 라우팅 검증 로그 |

---

## 구현 상세

### 과제 1: `_get_booking_settings` Tool 확장

**`src/ai_voicebot/langgraph/tools/booking_tools.py`**

반환 JSON에 3개 항목 추가:

| 신규 필드 | 내용 |
|-----------|------|
| `require_phone` | `booking_settings.require_phone` 값. `false`이면 LLM이 전화번호를 묻지 않음 |
| `require_name` | `booking_settings.require_name` 값. `false`이면 LLM이 이름을 묻지 않음 |
| `domain_extra_fields` | 활성 `booking_domains`의 `required_fields` + `optional_fields` 목록. 각 항목에 `domain_id`, `domain_name`, `field_key`, `field_label`, `field_type`, `required`, `options[]` 포함 |
| `schema_extra_fields` | `booking_schema_fields` 테넌트 공통 추가 필드 목록 |

추가 로그:
- `booking_tool_get_settings_complete`: `require_phone`, `require_name`, 추가 필드 수 기록
- `booking_tool_get_settings_domain_fields_failed`: 도메인 필드 조회 실패 시 경고
- `booking_tool_get_settings_schema_fields_failed`: 스키마 필드 조회 실패 시 경고

---

### 과제 2: `booking_agent` 도메인 추가 필드 수집 연동

**`src/ai_voicebot/langgraph/nodes/booking_agent.py`**

#### 2-a. 시스템 프롬프트 (`_BOOKING_SYSTEM_PROMPT`) 수정

`get_booking_settings` 결과 해석 지침 추가:
- `require_phone: false` → `customer_phone` 묻지 말 것
- `require_name: false` → `customer_name` 묻지 말 것
- `domain_extra_fields[].required=true` 항목은 `create_booking_tool` 전 반드시 수집
- 수집 값은 `extra_data: {field_key: 값}` 형태로 전달
- `field_type: select` 항목은 `options` 목록 안내

수집 순서 업데이트:
```
날짜/시간 → 인원 → (도메인 추가 필드 required) → 이름 → 예약 생성
```

#### 2-b. `_format_settings_hint()` 함수 신규 추가

`settings_cache`(get_booking_settings 결과)를 SystemMessage용 텍스트로 포맷.
- 전화번호/이름 수집 필요 여부
- 추가 필수/선택 수집 필드 목록 (domain_name, field_key, field_type, options 포함)
- settings_cache가 비어 있으면 빈 문자열 반환 (첫 발화 시 아직 조회 전)

#### 2-c. `_format_collected_slots()` 함수 시그니처 변경

`settings_cache: Optional[dict] = None` 파라미터 추가.
- `require_phone=false`이면 전화번호 필드를 기본 필드 목록에서 제외
- `require_name=false`이면 이름 필드를 기본 필드 목록에서 제외
- `domain_extra_fields` + `schema_extra_fields` 중 `required=true` 항목의 수집 현황 표시
- `collected["extra_data"]`에서 추가 필드 수집 여부 확인

#### 2-d. settings_cache 캐싱 (tool 실행 직후)

`get_booking_settings` tool 결과가 성공이면 `booking_context["settings_cache"]`에 저장.
- 동일 통화 내 다음 발화부터는 DB 재조회 없이 캐시 사용
- 캐싱 성공 시 `booking_agent_settings_cached` 로그 기록

#### 2-e. `_extract_collected_slots_from_messages()` 확장

`create_booking_tool` args에서 `extra_data`(dict)도 추출하여 `collected_slots["extra_data"]`에 병합.

---

### 과제 3: 라우팅 검증 로그 추가

`booking_agent_node_enter` 로그에 필드 추가:
- `routing_check_utterance_lane`: route_utterance_node가 설정한 레인 값
- `routing_check_intent`: classify_intent가 분류한 의도
- `routing_ok`: `utterance_lane == "booking" and intent == "booking"` 불리언

이 로그로 실제 통화 중 `booking_agent` 노드에 올바르게 도달했는지 즉시 확인 가능.

---

## 주요 결정 사항

- **settings_cache를 ContextVar 대신 booking_context에 저장**: 발화 간 히스토리와 동일한 생명주기를 가지며, 통화 종료 시 자동으로 소멸한다.
- **첫 발화 시 `_format_settings_hint`는 빈 문자열**: 아직 `get_booking_settings` 미호출 상태이므로 LLM이 자연스럽게 settings 조회 후 정책 반영한다. 두 번째 발화부터는 캐시가 주입된다.
- **`_format_collected_slots` 시그니처에 Optional 파라미터 추가**: 기존 `_fallback_text_booking` 등 settings 없이 호출하는 경로와 하위 호환성 유지.
- **도메인 추가 필드 실패 격리**: `list_domains`, `list_schema_fields` 오류 시 경고 로그만 남기고 기본 5개 필드 정책으로 폴백 — 안정성 우선.

---

## 잔여 과제

없음. (점검 리포트의 3개 과제 모두 완료)
