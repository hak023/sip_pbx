## 메타

- 작성일: 2026-04-20
- 대상 `call_id`: `lJOx6QvFnO`
- 목적: 예약이 실제 DB·도구로 반영되었는지 점검

## 개요

해당 통화에서는 **의도 분류·대화 흐름은 `booking`으로 정상**이었으나, **예약 도구(`create_booking` 등)가 한 번도 호출되지 않았고**, `bookings` 테이블에 해당 `call_id` 행이 **없음**을 확인했다. AI 응답은 **자연어 폴백만**으로 “예약 완료·문자 발송”까지 **환각(hallucination)** 수준이며, 실제 예약·SMS는 발생하지 않은 것으로 판단된다.

## 근거 (증거)

### 1. DB (`data/booking.db`)

- `bookings`에서 `call_id = 'lJOx6QvFnO'` → **0건**
- `call_records`에는 해당 통화 존재 (owner `1003`, caller `1004`, 약 154초, AI 처리)

### 2. 앱 로그 (`logs/app.log`)

`booking_agent` 진입마다 다음 경고가 반복됨:

- `booking_agent_no_bind_tools_model`
- `llm_client_type`: `LLMClient`
- 메시지: `LangChain BaseChatModel 미노출(bind_tools 불가) — create_booking 등 도구 없이 텍스트 폴백만 수행`

즉 **`bind_tools` 불가 모델**로 예약 에이전트가 돌아가 **툴 루프 없이** `booking_agent_fallback_complete`만 수행됨.

### 3. `call_data_record_20260420.log`

- `category: "booking"`, `event: "booking_committed"` (또는 `booking_rejected`) **해당 call_id 행 없음**
- `llm_exchange` / `tts_text_pushed`에만 예약 대화 내용 기록
- 마지막 예약 턴 응답 예시: “예약이 완료되었습니다. 예약 확인 문자를 보내드렸으니…” → **도구 미호출 상태에서는 사실과 불일치 가능성이 큼**

## 결론

| 항목 | 결과 |
|------|------|
| 실제 예약 DB 반영 | **아니오** (`bookings`에 없음) |
| `create_booking` 등 툴 호출 | **로그상 없음** (`bind_tools` 미지원 폴백) |
| 사용자가 들은 “완료·문자” 안내 | **신뢰 불가** (LLM 텍스트만, 백엔드 커밋 없음) |

## 원인 요약 (기술)

`booking_agent`는 설계상 **LangChain 도구 바인딩 + function calling**으로 `create_booking_tool` 등을 호출해야 한다. 현재 파이프라인의 `_llm_client`가 **`LLMClient` 래퍼**로 노출되어 `BaseChatModel.bind_tools` 경로가 없어, **항상 텍스트 폴백**으로 동작한 것이 직접 원인이다.

## 권장 후속 (참고)

- 예약 경로에서 **`bind_tools` 지원 모델**을 쓰거나, `LLMClient`에 LangChain 호환 래핑을 추가해 도구 호출이 가능하게 할 것.
- 폴백 모드일 때는 시스템 프롬프트/가드로 **“실제 예약은 시스템에서 확정되며, 지금은 안내만 가능”** 등 **거짓 완료 문구 금지**를 검토할 것.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| (없음) | — | 조사·분석만 수행, 코드 변경 없음 |
