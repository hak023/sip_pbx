# CALL_ANALYSIS 대응 구현 보고서 (의도·help JSON·RAG·STT 큐)

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-03-28 (로컬) |
| 근거 | `docs/reports/2026-03/CALL_ANALYSIS_CY09aXndRF_AI_AND_RTP.md` §3.3·§4 |
| 상태 | 구현 완료 |

---

## 1. 설계 요약

### 1.1 깨진 JSON(help TTS 오염) — 근본 원인

1. **출력 형식**: 배열-only 텍스트 프롬프트 + 일반 `generate_simple`(설정 temperature·비 JSON MIME) → 모델이 한국어 접두와 배열을 한 줄로 섞거나, `max_output_tokens`에서 배열이 잘림.
2. **파싱·폴백**: `json.loads` 실패 시 줄 단위 폴백이 `["...` 형태의 한 줄을 항목으로 삼을 수 있음 → 템플릿에 메타 문자열이 섞임.

### 1.2 대응

- **근본**: `LLMClient.generate_help_items_json` — `temperature=0.05`, 가능 시 `response_mime_type=application/json`, 프롬프트는 `{"items":[...]}` 단일 객체.
- **방어**: 객체 우선 파싱, TTS 안전 필터(`[]"{` 등 제거), 줄 폴백에서 JSON 잔재 라인 제외.
- **의도**: help 키워드에서 `"어떤 일"` 제거 + 기관 역할 질문 패턴이면 `question`으로 우회.
- **RAG**: `user_query_raw`(정규화 전 STT)를 상태에 넣고, `intent==question`일 때 원문 쿼리로 보조 검색 후 문서 병합.
- **STT 큐**: 깊이 ≥6일 때 1회 구간 경고 로그(기존 800대 백로그와 별도).

### 1.3 미구현 / 운영 검토만

- 착신 무응답 **10초** 정책: 코드베이스 내 상수 미확인 시 **운영 설정 검토**로 남김(리포트 P3).

---

## 2. 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `src/ai_voicebot/langgraph/state.py` | 수정 | `user_query_raw` 상태 필드 추가 | 설계대로 |
| `src/ai_voicebot/langgraph/agent.py` | 수정 | `process_utterance`에 `user_query_raw` 주입 | 설계대로 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | 정규화 전 STT 원문 캡처 후 Agent에 전달 | 설계대로 |
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | help 키워드 정리·기관 역할 질문→question | 설계대로 |
| `src/ai_voicebot/langgraph/nodes/response_shortcuts.py` | 수정 | help JSON 객체·파싱·TTS 필터·신규 LLM 호출 | 설계대로 |
| `src/ai_voicebot/ai_pipeline/llm_client.py` | 수정 | `generate_help_items_json` 추가 | 설계대로 |
| `src/ai_voicebot/langgraph/nodes/adaptive_rag.py` | 수정 | question 시 원문+주쿼리 이중 검색 병합 | 설계대로 |
| `src/media/rtp_relay.py` | 수정 | STT 큐 깊이 6+ 스파이크 경고(AEC/비AEC) | 설계대로 |

---

## 3. 운영·검증 메모

- 로그 키: `help_llm_generate_done`(`json_mode_applied`), `help_response_llm_parse_empty`, `adaptive_rag_dual_query_merged`, `stt_input_queue_depth_spike`, `classify_intent_help_keyword_to_question`.
- Gemini 구버전에서 `response_mime_type` 미지원 시 TypeError로 폴백하고 `help_llm_json_mime_unsupported`로 남김.
