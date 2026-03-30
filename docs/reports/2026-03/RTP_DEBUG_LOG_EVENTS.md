# RTP 전송 불안정 디버깅용 로그 이벤트

- **작성일:** 2026-03-26
- **상태:** `rtp_relay.py`, `sip_call_recorder.py` 반영
- **목적:** 구조적 병목(릴레이·큐·소켓·스케줄) 가설을 로그만으로 구분

## grep 키워드

| 이벤트 (`event` / 메시지 키) | 의미 | 가설 필드 |
|-----------------------------|------|-----------|
| `rtp_health_snapshot` | STT/PCM/UDP 큐·통계 스냅샷 | `trigger_reason` |
| `rtp_bypass_relay_sent` | Bypass `sendto` 성공 샘플 | `hypothesis`, `interarrival_ms`, `seq_jump_from_prev` |
| `rtp_bypass_sendto_failed` | Bypass `sendto` 실패 | `hypothesis`, `winerror`/`errno` |
| `rtp_bridge_sendto_failed` | Bridge leg `sendto` 실패 | `leg`, `hypothesis` |
| `rtp_datagram_socket_error_received` | `Protocol.error_received` | `hypothesis` (10054 등) |
| `tts_udp_out_queue_full_drop` | TTS→UDP 중간 큐 풀 | `hypothesis` |
| `rtp_recording_ingest_queue_full` | 녹음 인입 큐 최초 풀 | `hypothesis` |
| `rtp_recording_ingest_drop_accumulated` | 녹음 드롭 누적(200단위) | `drop_count` |

기존 이벤트(`rtp_send_behind_schedule`, `rtp_interval_violation`, `rtp_sendto_lock_wait_high`, `tts_udp_drain_bursty_or_slow` 등)와 함께 보면 됨.

## 해석 가이드

1. **`interarrival_ms` > ~55ms 반복** → 수신 버스트 또는 이벤트 루프 지연(다른 로그와 시간 상관).
2. **`seq_jump_from_prev` > 2** → 네트워크 손실·재정렬 또는 이전 샘플이 비RTP였을 가능성(첫 패킷 제외).
3. **`winerror=10054`** → Windows ICMP unreachable 등으로 송신 실패(미디어 포트/NAT).
4. **`tts_udp_out_queue_full_drop` + `pipeline_lag`** (기존 `rtp_tts_send_window_stats`) → 스레드가 루프보다 빠르게 큐잉.
5. **`rtp_recording_ingest_drop_accumulated`** → 녹음 워커가 느려 RTP 콜백 경로와 경합.
