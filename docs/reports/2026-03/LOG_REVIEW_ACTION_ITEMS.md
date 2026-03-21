# app.log 점검 결과 — 수정 필요 사항

**기준 로그**: `sip-pbx/logs/app.log` (2026-03-09 기동·통화 1건)

**반영 일자**: 적용 완료 항목은 아래 상태로 갱신됨.

---

## 1. 버그/에러 (즉시 수정 권장)

| # | 현상 | 권장 조치 | 상태 |
|---|------|-----------|------|
| 1.1 | **HITL fallback 호출 실패** | `HITLService`에 `consume_fallback_affirm`·`start_fallback_timer` 추가 | ✅ `src/services/hitl.py`에 구현 반영 |
| 1.2 | **Deprecated API 사용** | `get_organization_manager` → `create_org_manager` 교체 | ⏭ 코드베이스에 해당 로그 호출부 없음 (스킵) |

---

## 2. 로그 키/일관성

| # | 현상 | 로그 예시 | 권장 조치 |
|---|------|-----------|-----------|
| 2.1 | **`call_id` 빈 문자열** | `call_id`를 인자로 받아 항상 채워서 로깅 | ✅ `pipeline_builder.build_pipeline`에서 `tts_sync_context["_call_id"] = call_id` 설정. Notifier/로그에서 사용. |
| 2.2 | **event vs call 혼재** | 구조화 로그 정책에 맞춰 통일 | ⏭ 기존 구조 유지 (추후 정리 가능) |

---

## 3. 로그 레벨·양

| # | 현상 | 로그 예시 | 권장 조치 |
|---|------|-----------|-----------|
| 3.1 | **디버그용 로그가 info** | `🔍 [DEBUG] ai_voicebot_config check`, `config_debug_step1`~`step4` | 레벨을 `logging.DEBUG`로 변경하거나, 운영 기본이 info일 때는 해당 로그 제거/주석. |
| 3.2 | **API 키 노출 위험** | `Gemini API key loaded`, `key`: `"AIzaSyCueg...4a8w"` | 마스킹은 되어 있으나, 이 로그는 `DEBUG` 레벨로만 남기기. |
| 3.3 | **send_audio_to_caller_success 과다** | 매 TTS 청크마다 로그 (수십~수백 건) | 현재 조건(pcm_len > 10000 등)으로도 16000 bytes 청크가 많아 계속 찍힘. “처음 N회 + 큐 크기 임계 초과 시” 등으로 더 줄이기. |
| 3.4 | **rtp_interval_violation 과다** | 20ms 이탈 시 warning, 통화당 수백 건 (violation_count 550 등) | 이벤트는 유지하되 레벨을 `debug`로 내리거나, 50회마다만 warning으로 남기고 나머지는 debug. |

---

## 4. 동작/타이밍

| # | 현상 | 로그 예시 | 권장 조치 |
|---|------|-----------|-----------|
| 4.1 | **no_answer_timeout_activating_ai 중복** | 동일 초에 warning 2회 (15:49:49.768, 15:49:49.772) | 타임아웃 처리 경로가 두 번 들어가지 않도록 플래그/락으로 한 번만 실행되게 하기. |
| 4.2 | **인사말 Phase1 완료 타임아웃** | `greeting_phase_gap_tts_complete_timeout`, fallback_gap_sec 7.35, wait_timeout_sec 11.5 | Phase1 TTS 완료(EndFrame) 감지가 늦거나, Phase2 전송 조건이 타임아웃에만 의존. Notifier EndFrame과 연동해 “Phase1 완료 시점”에 Phase2 전송하도록 정리. |
| 4.3 | **RTP 20ms 간격 이탈 다발** | actual_ms 32.6, 13.4, 39.7, 6.8 등 | asyncio.sleep(0.02)만으로는 부하 시 지터 발생. 허용 오차(INTERVAL_TOLERANCE_MS) 확대 또는 “다음 절대 시각” 기준으로 sleep하여 누적 오차 보정 검토. |

---

## 5. 경로/설정 일관성

| # | 현상 | 로그 예시 | 권장 조치 |
|---|------|-----------|-----------|
| 5.1 | **CDR 경로 혼재** | filepath → cdr_file, as_posix() | ✅ cdr.py, sip_endpoint cdr_path.as_posix() |
| 5.2 | **Windows 경로 표기** | as_posix()로 `/` 통일 | ✅ CDR 로그에 반영 |

---

## 6. 품질/UX (참고)

| # | 현상 | 로그 예시 | 권장 조치 |
|---|------|-----------|-----------|
| 6.1 | **STT 오인식** | 한글(ko-KR) 설정·확인 | ✅ warmup 시 `ai_config_dict.google_cloud.stt` 전달, 기본·병합 시 `language_code` ko-KR 고정. 로그에 language_code 출력. |
| 6.2 | **LLM 응답 지연** | 구간별 점검 | ✅ `process_utterance_complete` 로그에 note로 "classify_intent (LLM) / generate_response (LLM)" 구간 로그 참고 안내. |
| 6.3 | **구간별 지연 로깅** | 이슈 발생 시 어느 파트가 느린지 확인 | ✅ LangGraph 노드 전반에 `timing_segment` 이벤트 추가 (segment, elapsed_sec). classify_intent, check_cache, rewrite_query, adaptive_rag, step_back, generate_response, hitl_alert, update_cache, update_state. |

---

## 7. 요약 우선순위 및 적용 현황

1. **즉시**: HITL ✅ | deprecated (호출부 없음) ⏭
2. **단기**: call_id(sync_context) ✅, 로그 레벨(debug) ✅, no_answer 중복 방지 ✅
3. **중기**: Phase1→Phase2 Notifier 연동 ✅, CDR/경로 일관성 ✅, RTP 지터(로그만 debug, 원인 분석은 추후), 구간별 지연 로깅(timing_segment) ✅

**Frontend (통화 실시간 / 지식 베이스)**  
- **활성 통화**: `GET /api/calls/active`가 빈 배열을 반환하던 원인은 CallManager에 `get_active_sessions` 메서드가 없었음. ✅ `get_active_sessions()`를 추가해 Repository의 활성 세션을 반환하도록 수정.  
- **지식 베이스**: `GET /api/knowledge` 등 API는 구현되어 있음. 프론트에서 호출 URL·owner 파라미터·CORS 등만 확인하면 됨.

---

*문서 생성: app.log 점검 기준 | 반영: 적용 완료 항목 갱신*
