# 실시간 대화 (STT/TTS) 표시 가이드

## 개요

대시보드 **통화 모니터**의 **실시간 대화** 영역에는 AI 통화 중 발신자(STT)와 AI 비서(TTS) 발화가 실시간으로 표시된다.

## 동작 조건

1. **WebSocket 서버(8001) 기동**  
   - 프론트는 `NEXT_PUBLIC_WS_URL`(기본 `http://localhost:8001`)로 Socket.IO 연결.  
   - **`python -m src.main`** 실행 시 WebSocket 서버가 같은 프로세스에서 자동 기동된다.  
   - 별도 실행이 필요하면: `python -m src.websocket` (또는 `start-all.ps1` 사용).

2. **로그인 및 통화 구독**  
   - JWT로 로그인한 extension과 통화의 **callee(착신번호)**가 일치해야 해당 통화를 구독할 수 있다.  
   - 통화 목록에서 통화를 선택하면 `subscribe_call(call_id)`로 구독하며, 이때만 `stt_transcript`, `tts_started`, `tts_completed` 이벤트를 수신한다.

3. **백엔드 발송**  
   - Pipecat `RAGLLMProcessor`가 `TranscriptionFrame`/`InterimTranscriptionFrame` 수신 시 `emit_stt_transcript` 호출.  
   - LLM 응답 전송 시 `emit_tts_started`, `emit_tts_completed` 호출.  
   - 동일한 `call_id`로 `broadcast_to_call` 하므로, 프론트에서 구독한 `call_id`와 파이프라인의 `call_id`가 일치해야 한다(동일한 original_call_id 사용).

## "연결 안됨" / 대화가 안 보일 때

| 현상 | 원인 | 조치 |
|------|------|------|
| 상단 **연결 안됨** | WebSocket(8001) 미기동 | `python -m src.main`으로 서버 실행(WebSocket 포함). 또는 `python -m src.websocket` 별도 실행. |
| 연결됐는데 대화 0건 | 해당 통화 미구독 또는 call_id 불일치 | 통화 목록에서 **해당 통화 선택** 후 실시간 대화 패널 확인. 로그인 extension이 callee와 같은지 확인. |
| STT만 보이고 TTS 안 보임 | 이벤트 누락 또는 오류 | 백엔드 로그에서 `tts_started_event_failed` 등 확인. |

## 참고

- 설계: `docs/architecture/realtime-call-dashboard-design.md`  
- STT/TTS 발송 구현: `src/ai_voicebot/pipecat/processors/rag_processor.py`  
- WebSocket 이벤트: `src/websocket/server.py` (`emit_stt_transcript`, `emit_tts_started`, `emit_tts_completed`)  
- 프론트 수신: `frontend/components/LiveCallMonitor.tsx` (`stt_transcript`, `tts_started`, `tts_completed`)
