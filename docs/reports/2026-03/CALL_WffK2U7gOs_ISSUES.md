# call_id WffK2U7gOs 이슈 리뷰 및 트래킹

## 호 개요

- **call_id**: `WffK2U7gOs` (b2bua-277002-WffK2U7g)
- **흐름**: 1003 → 1004 INVITE → 180 Ringing → 약 10초 no_answer → AI 터크오버 → Pipecat 기동 → 인사말 TTS → 사용자 "오늘 날씨가." STT → RAG 검색(결과 0) → LLM 응답 → HITL 알림 시도 시 **에러** → TTS 재생 후 통화 계속

## 확인된 이슈 및 조치

### 1. get_all_capabilities_failed (`'_VectorDbWrapper' object has no attribute 'collection'`)

| 항목 | 내용 |
|------|------|
| **로그** | `get_all_capabilities_failed` — `'_VectorDbWrapper' object has no attribute 'collection'` |
| **위치** | `src/services/knowledge_service.py` — `self.vector_db.collection.get(...)` 호출 다수 (라인 284, 435, 452, 465, 539, 625, 670, 872 등) |
| **원인** | `vector_db`가 `_VectorDbWrapper`로 주입되는데, 래퍼에 `.collection` 속성이 없음. 래퍼는 `.get()`, `.query()` 등만 제공. |
| **조치** | `src/ai_voicebot/knowledge/chromadb_client.py`의 `_VectorDbWrapper`에 `@property def collection(self): return self._collection` 추가하여 기존 `vector_db.collection.get(...)` 호출 호환. |

### 2. hitl_alert_callback_error (`missing 1 required positional argument: 'context'`)

| 항목 | 내용 |
|------|------|
| **로그** | `hitl_alert_callback_error` — `_default_hitl_alert() missing 1 required positional argument: 'context'` |
| **위치** | RAG/파이프라인에서 HITL 알림 시 `hitl_processor`가 `on_alert(alert_data)` **1인자**로 호출. `call_manager`의 `_default_hitl_alert`는 `(cid, question, context, urgency)` **4인자** 시그니처로 정의됨. |
| **원인** | 콜백 시그니처 불일치. 호출측: `(context)` / 정의측: `(cid, question, context, urgency)`. |
| **조치** | `src/sip_core/call_manager.py`에서 `_default_hitl_alert(context: dict)`로 변경하고, 내부에서 `cid = context.get("call_id")`, `question = context.get("question")`, `urgency = context.get("urgency", "medium")` 추출 후 `emit_hitl_requested(cid, question, context, urgency)` 호출. |

## 기타 로그 (참고)

- `org_manager_capabilities_loaded` count=0 — get_all_capabilities 실패 후 폴백.
- `rag_search_completed` results_count=0 — 해당 질의에 대한 지식 없음.
- `adaptive_rag_no_results`, `tts_rtp_duration_mismatch`, `rtp_interval_violation` 등은 별도 이슈/튜닝 대상.

## 참고

- 해당 호 로그: `sip-pbx/logs/app.log` (call_id WffK2U7gOs, b2bua-277002-WffK2U7g 구간).
- HITL 콜백 규약: `hitl_processor`는 `on_alert(alert_data)` 1인자만 사용; `alert_data`에 `call_id`, `question`, `alert_type` 등 포함.
