# app.log 리뷰: LLM 짧은 응답 및 기타 이슈

**기준 로그**: `sip-pbx/logs/app.log`  
**분석 일자**: 2026-02-21  
**대상 통화**: YCYrz6cVN4 (1003 → 1004, AI 터치다운)

---

## 1. LLM이 짧게만 응답하는 문제

### 1.1 로그에서 확인된 현상

- **사용자 발화**: `"안녕하세요 주차 문의하려고 하는데요 주차는 어떻게 해야 돼요?"` (34자)
- **실제 LLM 응답**: `"안녕하세요. 기상청 AI 통"` (**15자**, 중간에 잘림)
- **응답 관련 로그**:
  - `LLM response generated` → `response_length: 15`, `chunks: 2`
  - `llm_exchange_full` → `response_full: "안녕하세요. 기상청 AI 통"`, `response_len: 15`
  - TTS 재생: `duration_sec: 2.56`, `bytes_sent: 81932` (짧은 문장만 재생)

즉, 주차 문의에 대해 **본문 답변이 아니라 인사 한 마디만** 나가고 끝난 상태입니다.

### 1.2 원인 분석

1. **의도(intent) 오분류**
   - `classify_intent`에서 **키워드 "안녕"**만 보고 **intent = greeting**으로 분류됨.
   - greeting 경로는 **RAG/캐시를 타지 않고** 바로 `generate_response`만 호출.
   - 그래서 “주차는 어떻게 해야 돼요?”라는 **실제 질문이 RAG로 가지 않음**.

2. **greeting일 때의 짧은 응답**
   - 사용자 질문 전체가 LLM에는 전달되지만, intent가 greeting이라 **인사 위주 짧은 응답**이 나오는 것으로 보임.
   - 로그상 `response_length: 15`로, 모델이 **15자 수준에서 생성이 끊긴 것**으로 기록됨.
   - 설정 측면: `config.yaml`에는 `max_output_tokens: 500`인데, `LLMClient`는 **`max_tokens` 키만 참조**하고 있어, **`max_output_tokens`가 반영되지 않을 수 있음** (기본 200 등으로 동작 가능).

### 1.3 적용한 수정 사항

| 구분 | 파일 | 내용 |
|------|------|------|
| 의도 분류 | `langgraph/nodes/classify_intent.py` | 인사 키워드와 **질문/요청 패턴**(예: 어떻게, 문의, 주차, 알려, 되나요 등)이 **함께 있으면** greeting이 아니라 **question**으로 분류하도록 변경. → RAG 경로를 타서 본문 답변이 나오도록 함. |
| LLM 설정 | `ai_pipeline/llm_client.py` | `max_output_tokens`를 우선 사용하고, 없으면 `max_tokens` 사용하도록 수정. → `config.yaml`의 `max_output_tokens: 500`이 정상 반영되도록 함. |

이후 동일한 발화("안녕하세요 주차 문의...")는 **question**으로 분류되어 RAG + 본문 답변이 나와야 합니다.

---

## 2. 로그 전반 리뷰 – 기타 이슈

### 2.1 경고·비정상 패턴

| 이벤트 | 설명 | 권장 조치 |
|--------|------|-----------|
| `callee_not_found` | 1004가 아직 미등록 상태에서 1003이 1004로 INVITE → 404. | 테스트 시 1004 등록 후 발신하거나, 등록 순서/안내 정리. |
| `ack_ignored_no_active_call` | 404 응답에 대한 ACK 수신 시 활성 통화 없음으로 무시. | 404 흐름에서의 정상 동작일 수 있음. 필요 시 ACK 처리 로그만 정리. |
| `get_organization_manager_deprecated` | `get_organization_manager` 사용 deprecated. | `create_org_manager(owner, knowledge_service)`로 교체 권장. |
| `no_answer_timeout_activating_ai` | 10초 무응답 후 AI 터치다운 발동. | 의도된 동작. 필요 시 타임아웃 값만 설정 검토. |
| **`llm_judgment_response` / JSON parse 실패** | 통화 유용성 판단(judgment) LLM 응답이 **중간에 잘림** → JSON 파싱 실패. 로그: `Unterminated string...`, `response_length: 156`, `finish_reason: "2"`. | judgment 호출 시 **`judgment_max_output_tokens`** 확인(현재 1024). 응답이 여전히 잘리면 2048 등으로 상향 또는 JSON 스키마 축소. |
| **`llm_judgment_completed`** | 위 실패 후 기본값 적용: `is_useful: false`, `confidence: 0.0`. | JSON 실패 시 재시도 또는 fallback 정책 검토. |

### 2.2 정상 동작으로 보이는 부분

- SIP 등록/INVITE/200 OK/ACK/BYE, RTP 릴레이, 녹음 시작/종료
- Pipecat 파이프라인 구동, STT/LLM/TTS 이벤트, greeting Phase1/Phase2
- CDR 기록, 후처리 STT(caller/callee 채널 분리), transcript 저장
- WebSocket 구독/해제, active_calls 조회

### 2.3 참고: transcript 저장 형식

- `stt_transcript_saved` preview에 **서브워드 구분자 `▁`**가 포함된 형식으로 저장됨.
- 읽기 편하게 하려면 저장 시 `▁` 제거 후 저장하는 로직은 이미 별도 적용된 상태일 수 있음. 필요 시 `sip_call_recorder` 등 저장 경로 확인.

---

## 3. 요약 및 다음 점검 사항

- **LLM 짧은 응답**: intent를 “인사+질문”일 때 question으로 보도록 수정하고, `max_output_tokens` 설정이 반영되도록 수정함. 재현 테스트 권장.
- **유용성 판단 JSON 잘림**: judgment LLM 응답이 잘려 JSON 파싱이 실패하는 케이스가 있음. `judgment_max_output_tokens` 상향 또는 응답 길이 제한 완화 검토.
- **Deprecation**: `get_organization_manager` → `create_org_manager` 전환 진행 권장.

이 문서는 `app.log` 리뷰와 LLM 짧은 응답 수정 내용을 정리한 것입니다.
