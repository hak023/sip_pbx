# 실시간 통화 처리 로그 (call_data_record 동기화)

**작성일**: 2026-03

## 목적

대시보드에서 **`logs/call_data_record_YYYYMMDD.log`에 쓰이는 것과 동일한 이벤트**를 WebSocket으로 실시간 확인한다.  
LLM·STT·TTS·RAG·`call_event`·HITL 등 파이프라인 단계별 디버깅용.

## 설계

| 항목 | 내용 |
|------|------|
| **기록 원천** | `src/common/call_data_record_logger.py`의 `log_call_data()` |
| **파일** | 기존과 동일 — JSON Lines (`ts`, `call_id`, `category`, `event`, …) |
| **실시간** | `log_call_data`가 파일 flush 직후 동일 `payload`를 `schedule_socket_emit("call_debug_trace", …)`로 전송 |
| **페이로드 제한** | WebSocket용으로 문자열·리스트 길이 상한 (`_truncate_for_ws`) — 파일 로그는 전체 유지 |
| **유저 간 STT** | Bypass 스트리밍 STT는 **최종 구간만** `log_call_data(..., "stt_bypass_final")`로 기록 (`bypass_realtime_stt.py`) |

## 프론트엔드

- 이벤트: `call_debug_trace`
- 통화 카드 하단 **「처리 로그 (call_data_record)」** 접기/펼치기 패널
- 상단 **카테고리 필터** (전체 / stt / tts / llm / rag / …)
- 통화 종료 시 해당 `call_id`의 버퍼 제거

## 변경 파일 (요약)

| 파일 | 역할 |
|------|------|
| `src/common/call_data_record_logger.py` | `_broadcast_call_debug_trace`, `_truncate_for_ws` |
| `src/media/bypass_realtime_stt.py` | 최종 STT `log_call_data` |
| `frontend/app/dashboard/page.tsx` | `call_debug_trace` 구독·UI |

## 운영

- Socket.IO는 **`python -m src.main`** 기동 시 Python WS 스레드(8001)에서만 `call_debug_trace` 수신 가능.
- `log_call_data` 호출이 없는 경로(예: 일부 유저 간만)는 패널이 비어 있을 수 있음 — 정상.
