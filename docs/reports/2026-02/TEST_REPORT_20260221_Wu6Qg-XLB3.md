# 통화 테스트 리포트 (2026-02-21 재시작 후)

**통화 ID**: Wu6Qg-XLB3 (1003 → 1004 기상청)  
**로그**: `logs/app.log`  
**요약**: 재시작 후 1회 통화 기준. API 키 403(유출) 발생으로 후반 LLM 실패, HITL 타임아웃 후 서버 BYE.

---

## 1. LLM 응답 문장 절단

**현상**: "네, 내일의 날씨 예보를 안내해 드릴 수 있습니다. **어떤 지역의**" (35자)에서 끊김.

**로그**:
- `semantic_cache_hit` score 0.960 → **캐시에서 반환된 응답이 이미 절단된 문장**.
- `response_len`: 35.

**원인**:
- **캐시에 저장될 때** 해당 문장이 끝까지 생성되지 않고 저장됨(이전 통화에서 MAX_TOKENS 또는 조기 종료).
- 프롬프트에 “문장 완결” 강조가 부족해, 모델이 “어떤 지역의” 다음을 생성하지 않고 종료한 뒤 캐시에 들어간 것으로 추정.

**조치**:
- RAG/응답 생성 프롬프트에 “문장은 반드시 마침표(.)·물음표(?)로 끝내고, 중간에 끊기지 마세요” 명시.
- 캐시 저장 시 불완전 응답(끝이 조사/불완전 시그널)이면 저장하지 않거나, 재생성 유도.

---

## 2. TTS가 RTP까지는 개선, 문장 잘림 지속

**정상 예시**: "저는 날씨 예보 조회, 기상 특보 안내, 과거 기상 데이터 제공, 기상청 담당자 연결, 일반 기상 상식 안내**을** 도와드릴 수 있어요."

**현재 청취**: "저는 날씨 예보 **조**(잘림), 기상 **특**(잘림), 과거 기상 **제**(잘림), 기상청 담당자 연결, 일반 기상 상식 안내을 도와드릴 수 있어요."

**로그**:
- Phase2 전체 문장 1회 전송: `greeting_phase2_sent` text 길이 73자.
- `notifier_endframe_processed` duration_sec 13.655, `response_bytes` 436958 → **서버 기준으로는 전체 구간 PCM 투입**.

**해석**:
- EndFrame 타이밍 수정 후 **RTP로 나가는 양**은 정상에 가깝게 나옴.
- 전화기에서 “조”, “특”, “제” 등에서 끊겨 들리는 현상은 **TTS 엔진(Google)이 긴 문장을 구간별로 내보낼 때 구간 경계에서 끊기거나**, **RTP/재생 버퍼·jitter** 가능성 있음.

**조치**:
- Phase2 인사말을 **쉼표 단위로 나누어 순차 재생**(한 구간 끝까지 재생 후 다음 구간)하는 옵션 검토.
- TTS 구간별 `tts_stopped_frame_received` / `duration_sec` 상세 로그로, 구간별 길이와 실제 재생 구간 대조.

---

## 3. Frontend 실시간/이력 STT에 인사말 미포함

**현상**: Phase1·Phase2 인사말이 실시간 STT 및 이력 STT에 포함되지 않음.

**이유**: 인사말은 **TTS 출력**이라 STT 채널(caller/callee 음성)에 없음. 대시보드는 STT 결과만 표시하므로 “AI가 말한 인사말”이 안 나옴.

**조치**:
- 인사말 Phase1·Phase2 텍스트를 **통화별로 저장**(DB 또는 세션).
- API/WebSocket으로 해당 통화의 인사말 텍스트를 내려주고, 프론트에서 “AI 인사” 영역에 표시.

---

## 4. 통화 마지막 마무리 인사말 미재생

**현상**: 마무리 인사말이 DB에 저장·TTS→RTP로 나가야 하는데, 그 전에 통화가 끊김.

**이번 로그**:
- 이번 통화에서는 **사용자 “감사합니다”** 로그 없음. **HITL 타임아웃**(17:00:42) 후 **서버가 BYE** (17:00:50) 전송.
- 따라서 **farewell 플로우**는 미동작. 마무리 멘트는 “사용자가 farewell 말한 경우”에만 재생되는 구조.

**추가 점검**:
- 사용자가 “감사합니다” 등 farewell 발화 시 `farewell_closing_message_set` 로그와 해당 response의 TTS push 여부 확인.
- 서버 발신 BYE 전에 “통화를 종료합니다” 등 안내 TTS를 넣는 정책이 있다면, 그 경로에서도 마무리 문구가 TTS→RTP로 나가는지 확인 필요.

---

## 5. LLM이 모르는 내용에 대한 잘못된 응답

**로그**:
- 17:00:26 **403 Your API key was reported as leaked** 발생.
- `rewrite_query`가 실패하면서 **“죄송합니다, 답변을 생성하는 중 오류가 발생했습니다.”** 가 **rewritten_query**로 사용됨.
- RAG 검색이 그 문장으로 수행되어 `results_count: 0`, `confidence: 0`, HITL 알림 발생.

**원인**:
- LLM 예외 시 클라이언트가 **에러 메시지 문자열**을 그대로 반환하고, 이를 **쿼리/응답**으로 쓰는 경로가 있음.
- “모르는 내용” 전용 응답(“확인 후 안내 드리겠습니다” 등)과 **시스템/API 오류** 응답이 구분되지 않음.

**조치**:
- LLM 예외 시: **쿼리 변환** 용도면 원본 쿼리 유지, **응답 생성** 용도면 “해당 내용은 확인 후 안내 드리겠습니다” 등 고정 문구 반환.
- rewrite_query: 반환 문자열이 오류 메시지 패턴(예: “오류”, “죄송”)이면 **원본 user_query**를 rewritten_query로 사용.

---

## 6. 기타 이슈

| 이슈 | 로그/내용 | 비고 |
|------|-----------|------|
| **403 API 키 유출** | `LLM generation error` 403 leaked | 새 키 발급 후 config에 반영 필요. |
| **HITL 타임아웃** | 17:00:42 `HITL request timed out` | 60초 내 응답 없음. |
| **timeout_message TTS 실패** | `format_for_customer_failed` 403 | HITL 타임아웃 메시지 포맷 시에도 동일 API 키 사용. |
| **서버 발신 BYE** | 17:00:50 `bye_sent_to_caller` reason=server_initiated | HITL 타임아웃 후 정책에 따른 종료. |
| **get_organization_manager_deprecated** | 초기화 시 1회 | create_org_manager 사용 권장. |

---

## 7. 상세 로그 보강 제안

- **farewell 시**: `farewell_closing_message_set` 이후 해당 response로 TTS push 시 `llm_response_sent` 등에 `intent=farewell` 표시.
- **캐시 저장 시**: `response`가 문장 완결인지 여부(끝 문자, 길이) 로그.
- **Phase2 인사**: Phase2 1문장을 쉼표 등으로 나눈 구간 수·구간별 문자 수 로그(문장 잘림 원인 분석용).
- **LLM 예외 시**: `rewrite_query`/`generate_response`에서 예외 처리 시 `fallback_used=True`, `original_query` 유지 여부 로그.

---

## 8. API 키 403 (유출) 대응

- **메시지**: `403 Your API key was reported as leaked. Please use another API key.`
- **조치**: [docs/guides/GEMINI_API_KEY_ROTATION.md](../guides/GEMINI_API_KEY_ROTATION.md) 참고하여 **새 API 키 발급** 후 `.env`(권장) 또는 `config/config.yaml`에 반영. 기존 키는 사용 중단.

---

이 리포트는 위 조치 반영 후 재테스트 시 비교 기준으로 사용할 수 있다.

---

## 구현 요약 (2026-02-21 반영)

| 항목 | 구현 내용 |
|------|-----------|
| **1. LLM 절단** | `generate_response.py`: 프롬프트에 문장 완결 규칙 추가. `semantic_cache.py`: `_looks_complete_sentence()`로 불완전 응답 캐시 미사용·미저장. |
| **2. TTS 잘림** | 리포트에 원인·조치 정리. Phase2 쉼표 단위 순차 재생 옵션은 추후 검토. |
| **3. 인사말 노출** | `greeting_store.py` 추가. CDR metadata에 저장. WebSocket `ai_greeting` + 프론트 수신. 이력 API에서 트랜스크립트 앞에 인사말 추가. |
| **4. 마무리 인사말** | `farewell_closing_pushed` 로그 추가. farewell 시 TTS push 여부 확인 가능. |
| **5. 모르는 내용** | `rewrite_query`: 오류 메시지면 원본 쿼리 유지. `generate_response`: 오류/예외 시 고정 문구 "해당 내용은 확인 후 안내 드리겠습니다" 반환. |
| **6. 상세 로그** | `farewell_closing_pushed`, `generate_response_llm_error_fallback`, `query_rewrite_llm_error_used_original`, `semantic_cache_skip_truncated` 등 추가. |
| **7. API 키** | `docs/guides/GEMINI_API_KEY_ROTATION.md` 작성. |
