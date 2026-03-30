# RTP TTS 송신 스케줄러·Busy-wait 개선 설계

- **작성일**: 2026-03-26  
- **상태**: 구현 반영 (`src/media/rtp_relay.py`)  
- **근거**: `RTP_CUTOUT_APP_LOG_ANALYSIS_20260327.md` §4 권장 1·2항, `RTP_SENDER_PATH_STRUCTURE_REVIEW.md` §5-1·§5-4

## 1. 스케줄러 정책 (§5-1)

### 문제

- `target_time = max(ideal_grid, last_send + MIN_INTER)` 에서 **MIN_INTER=8ms** 이면, 격자상 늦은 뒤 **연속 전송 간격이 8~12ms대로 붙는 버스트**가 생기고, 로그상 **긴 간격 직후 짧은 간격**(`rtp_interval_violation`) 쌍이 늘어남.
- 단말 PLC/지터버퍼 입장에서 청취 뭉개짐·끊김 체감으로 이어질 수 있음.

### 조치

| 상수 | 이전 | 이후 | 의도 |
|------|------|------|------|
| `_RTP_SCHED_MIN_INTER_SEND_MS` | 8.0 | **17.0** | 20ms CBR에 가깝게 최소 간격 제한 → catch-up 버스트 완화 |
| `_RTP_SCHED_SOFT_RESYNC_LATE_MS` | 22.0 | **20.0** | 약 1 RTP 슬롯 지연에서 `base_time` 재앵커 → 긴 꼬리 버스트 단축 |

기존 **soft resync** 로직(지연 시 `_rtp_packets_sent_total` 리셋 + `rtp_sched_soft_resync_count`)은 유지.

## 2. Busy-wait 완화 (§5-4)

### 문제

- `time.sleep(sleep_needed - 1ms)` 이후 **목표 시각까지 무한 `while pass` 스핀** → 전용 스레드가 코어를 점유, 동일 프로세스의 STT·파이프라인·다른 스레드와 **CPU 경합** 유발 가능.

### 조치

- `_wait_until_send_deadline(deadline)`:
  - 남은 시간이 **큰 구간**: `time.sleep(rem - spin_cap)` 로 대부분 소모 (`spin_cap` ≈ 350µs).
  - **중간 구간** (~180µs 초과): `Sleep(0)`(Windows) / `os.sched_yield()`(Unix) 로 양보.
  - **미세 구간**: 짧은 busy-wait로만 정밀도 유지.

상수:

- `_RTP_SCHED_BUSY_SPIN_MAX_SEC = 0.00035`
- `_RTP_SCHED_YIELD_FLOOR_SEC = 0.00018`

## 3. 튜닝·모니터링

- `interval_violations`, `rtp_tts_send_window_stats`, `rtp_sched_soft_resync_count`를 이전 통화와 비교.
- MIN_INTER를 **18~19ms**까지 올리면 지터 쌍은 더 줄 수 있으나, **지연 누적·큐 적체** 가능 → 부하 통화에서 `pcm_queue_size` 병행 관찰.

## 4. 범위 밖

- PCM 공급 공백(`rtp_tts_queue_empty_timeout`)은 **상위 TTS/LLM** 이슈 — 본 변경으로 해결되지 않음 (`RTP_CUTOUT` §3).
