# 유저 간 통화 — 대시보드 실시간 STT 미표시 점검

- **작성일**: 2026-03-24
- **상태**: 코드 경로 분석 + 진단 로그 보강
- **관련 코드**: `src/media/bypass_realtime_stt.py`, `src/media/rtp_relay.py` (`feed_bypass_realtime_stt`), `src/websocket/server.py` (`install_bypass_realtime_stt_callback`, `stt_transcript`), `frontend/app/dashboard/page.tsx`

## 동작 요약

1. B2BUA **Bypass** 모드에서 `ai_mode == False`일 때 RTP가 `RTPRelayWorker.on_packet_received` → `feed_bypass_realtime_stt`로 들어감.
2. 페이로드를 **G.711(PCMU/PCMA)** 로 가정해 8kHz LINEAR16 PCM으로 만든 뒤, 채널별(`caller` / `callee`)로 **Google Cloud 스트리밍 STT** 스레드에 넣음.
3. 전사 결과는 `set_broadcast_callback`으로 등록된 핸들러가 **`schedule_socket_emit("stt_transcript", …)`** 로 Socket.IO에 보냄.
4. 대시보드는 `NEXT_PUBLIC_WS_URL`(기본 `http://localhost:8001`)로 접속해 `stt_transcript`를 받고, **`call_id`가 활성 통화와 같을 때** 해당 통화의 피드에 쌓음.

## 흔한 원인 (우선순위)

| 원인 | 증상·확인 |
|------|-----------|
| **GCP Speech 미설치/자격증명** | `pip install -r requirements-ai.txt`, `GOOGLE_APPLICATION_CREDENTIALS`, 프로젝트에서 Speech API 활성화. 로그: `bypass_stt_google_import_failed`, `bypass_stt_speech_client_failed`, `bypass_stt_stream_ended` + API/권한 오류 메시지 |
| **WebSocket(8001) 미기동 또는 콜백 미등록** | SIP만 떠 있고 WS 스레드 실패 시. 로그: `schedule_socket_emit_skipped_ws_not_ready`, `bypass_stt_callback_install_failed` (보강됨) |
| **오디오 코덱 불일치** | SDP가 **OPUS** 등인데 `media_session.codec`이 없어 기본 **PCMU**로 디코딩하면 무음/쓰레기 PCM → STT 무결과. 로그: `bypass_stt_pcm_empty_after_decode` (보강됨), 필요 시 SDP에서 협상 코덱을 `MediaSession`에 반영 후 `feed_bypass`에 전달하는 개선이 필요 |
| **RTP가 B2BUA를 안 탐** | 미디어가 단말 직접(P2P)이면 PBX가 RTP를 못 받아 STT 입력 없음. 통화는 되지만 `bypass_realtime_stt_feed_started` 자체가 안 찍힐 수 있음 |

## 재기동 후 확인할 로그 키워드

- `bypass_realtime_stt_dashboard_callback_registered` — WS 기동 시 콜백 등록 성공
- `bypass_realtime_stt_feed_started` — 해당 통화에서 RTP→STT 피드 시작
- `bypass_stt_gcp_stream_iter_started` — GCP 스트리밍 세션 루프 진입
- `bypass_stt_gcp_first_transcript` — 첫 전사 수신 (이후 대시보드면 WS/프론트 이슈)
- `bypass_stt_broadcast_skipped_no_callback` — 콜백 없이 전사만 되고 UI로 안 나감

## 코드 변경 요약 (진단용)

- `bypass_realtime_stt.py`: WS 등록 실패·PCM 디코딩 공백·GCP 스트림 시작/첫 전사/스트림 비정상 종료 시 **원인 추적 가능한 로그** 추가.
