# HITL 운영자 응답 반영 및 타임아웃 흐름

## 1. 문제 요약 (call_id yQpeFs~dWm)

- **현상**: 운영자가 "고객님, 문의해 주셔서"가 **아닌** 다른 내용으로 응답했는데, 로그에는 `hitl_response_received`로 "고객님, 문의해 주셔서"만 기록됨.
- **원인**: 백엔드가 **HITL 타임아웃 시** 생성한 **정제 폴백 메시지**(`hitl_timeout_message_refined`)를, **운영자 응답**과 동일한 경로로 처리하면서 **같은 로그 이벤트**(`hitl_response_received`)로 남기고 TTS에도 사용한 것으로 추정됨.

---

## 2. 로그로 확인된 흐름 (yQpeFs~dWm)

| 시각 | 이벤트 | 내용 |
|------|--------|------|
| 20:47:05.010 | hitl_alert_processing | low_confidence, HITL 알림 처리 |
| 20:47:05 ~ 20:47:25 | (대기) | 운영자 응답 대기 (~20초) |
| **20:47:25.039** | **hitl_timeout_message_refining** | original_text: "확인이 지연되고 있습니다. 확인되는 대로 연락 드리겠습니다." (타임아웃용 템플릿) |
| **20:47:26.758** | **hitl_timeout_message_refined** | refined_text_full: "고객님, 문의해 주셔서" (LLM이 타임아웃 문구를 정제한 결과) |
| **20:47:26.758** | **hitl_response_received** | text_preview: "고객님, 문의해 주셔서" ← **실제 운영자 응답이 아님** |
| 20:47:41.040 | bye_received | 발신자 BYE |

- `hitl_response_received`에 찍힌 문구는 **타임아웃 정제 메시지**와 동일함. 즉, **운영자 응답 경로**와 **타임아웃 폴백 경로**가 한 곳에서 합쳐져, 타임아웃 시에도 "응답 수신"으로 로깅·TTS에 사용된 것으로 보는 것이 타당함.

---

## 3. 의도된 흐름 (설계)

### 3.1 운영자 응답이 들어온 경우

1. **프론트**: HITL 다이얼로그에서 운영자가 답변 입력 후 "전송" → `wsClient.submitHITLResponse({ call_id, response_text, save_to_kb, category, question })` → Socket.IO `submit_hitl_response` 이벤트로 전송.
2. **백엔드**: `submit_hitl_response` 수신 시  
   - 해당 `call_id`의 HITL 대기 상태 해제.  
   - **운영자가 입력한 `response_text`**를 그대로 사용.  
   - 로그: `hitl_response_received` with **실제 response_text** (원문 또는 정제된 문구 명시).  
   - (선택) 통화 맥락 + 운영자 응답으로 LLM에 한 번 더 질의해 문장만 다듬을 수 있음.  
   - TTS: **운영자 응답**(또는 LLM 다듬은 문장)으로 재생.
3. **지식 저장**: `save_to_kb` true이면 해당 tenant 지식베이스에 저장.

### 3.2 HITL 타임아웃인 경우

1. **백엔드**: 타임아웃 타이머 만료 시  
   - 운영자 응답이 **아직 없음**으로 간주.  
   - **타임아웃용 템플릿**("확인이 지연되고 있습니다...")을 LLM으로 정제 → `hitl_timeout_message_refined` 로그 (refined_text_full 등).  
   - 이 문구를 **TTS로만** 사용.  
   - **`hitl_response_received`는 사용하지 않음** (운영자 응답이 없으므로).  
   - 프론트에는 `hitl_timeout` 이벤트로 알림 (대기 해제, “AI가 다시 연결” 안내 등).

### 3.3 경로 분리 요약

| 구분 | 소스 텍스트 | 로그 (응답 수신) | TTS |
|------|-------------|------------------|-----|
| **운영자 응답** | WebSocket `submit_hitl_response` 의 `response_text` | `hitl_response_received` (실제 payload) | 운영자 응답(또는 LLM 정제본) |
| **타임아웃** | 타임아웃 템플릿 → LLM 정제 | `hitl_timeout_message_refined` 만 사용, **hitl_response_received 사용 금지** | refined 타임아웃 문구 |

---

## 4. 백엔드 수정 시 점검 사항

(백엔드 코드가 있는 저장소에서 적용)

1. **타임아웃 시**  
   - 정제된 타임아웃 문구를 TTS로 넣을 때, **`hitl_response_received`를 호출하지 않기**.  
   - `hitl_timeout_message_refined` 만 로깅하고, “타임아웃으로 TTS 재생” 등 별도 이벤트로 구분.

2. **운영자 응답 수신 시**  
   - `submit_hitl_response` 에서 오는 **`response_text`만** `hitl_response_received` 및 TTS에 사용.  
   - 이미 타임아웃으로 폴백 TTS를 보냈더라도, **나중에 도착한 운영자 응답**을 그대로 “응답 수신”으로 로깅하고, 다음 턴에서라도 TTS로 재생할지는 정책으로 결정 (기본은 “타임아웃 후 도착한 응답은 로그만 남기고 TTS는 이미 보냈음”으로 처리 가능).

3. **레이스 컨디션**  
   - 타임아웃 타이머와 `submit_hitl_response` 도착이 비슷할 때:  
     - “먼저 도착한 쪽”을 한 번만 적용하도록 상태 플래그(예: `hitl_resolved`)로 보호.  
     - 타임아웃 쪽이 먼저 실행되면 → 타임아웃 정제 문구만 TTS, `hitl_response_received` 로그 없음.  
     - 운영자 응답이 먼저 도착하면 → 운영자 응답만 TTS + `hitl_response_received`(실제 텍스트).

4. **로깅**  
   - `hitl_response_received`: **반드시** WebSocket `submit_hitl_response` payload의 응답 텍스트만 기록.  
   - `hitl_timeout_message_refined`: 타임아웃 정제 문구만 기록.  
   - 필요 시 `source: "operator"` / `source: "timeout_refined"` 처럼 구분 필드 추가.

---

## 5. 프론트엔드 ↔ 백엔드 연동 (현재 구현 기준)

- **프론트**: `HITLDialog` → `wsClient.submitHITLResponse({ call_id, response_text, save_to_kb, category, question })` → Socket.IO `submit_hitl_response` 전송. (이미 올바르게 구현됨.)
- **백엔드**: `submit_hitl_response` 수신 시 위 §3.1대로 **운영자 `response_text`만** 응답으로 사용하고, 타임아웃 경로(§3.2)와 로그/코드 경로를 분리할 것.

---

## 6. HITL → 프론트 → LLM → TTS 전체 흐름 체크리스트

| 단계 | 담당 | 점검 항목 |
|------|------|-----------|
| HITL 알림 | 백엔드 | low_confidence 등 조건 시 hitl_alert, WebSocket으로 hitl_requested 전송 (call_id, question, context 포함). |
| 대기 | 프론트 | hitl_requested 수신 → HITL 큐 표시, 다이얼로그에서 운영자 입력 대기. |
| 운영자 전송 | 프론트 | 전송 시 submit_hitl_response(call_id, response_text, ...) 호출. |
| 응답 수신 | 백엔드 | submit_hitl_response 수신 시 **response_text만** 사용, hitl_response_received(실제 텍스트) 로그, hitl_resolved 브로드캐스트. |
| LLM 정제 (선택) | 백엔드 | 운영자 응답을 통화 맥락과 함께 LLM에 넘겨 문장만 다듬을 수 있음. (정제 시 “원문 / 정제문” 구분 로그 권장.) |
| TTS | 백엔드 | **운영자 경로**: 운영자 응답(또는 정제문)으로 TTS. **타임아웃 경로**: refined 타임아웃 문구로만 TTS, hitl_response_received 미사용. |
| 타임아웃 | 백엔드 | 타이머 만료 시 hitl_timeout_message_refining → hitl_timeout_message_refined, hitl_timeout 이벤트 전송, TTS는 정제 타임아웃 문구만 사용. |

이 문서는 로그 분석과 설계 정합성 확인용이며, 실제 수정은 백엔드 저장소의 HITL·WebSocket 처리 코드에서 적용해야 함.
