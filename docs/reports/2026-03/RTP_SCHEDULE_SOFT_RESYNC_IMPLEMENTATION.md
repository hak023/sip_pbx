# RTP 송신 스케줄 소프트 재동기화 구현

| 항목 | 내용 |
|------|------|
| **작성일** | 2026-03-26 (로컬) |
| **상태** | 구현 완료 |
| **배경** | `RTP_SENDER_PATH_STRUCTURE_REVIEW.md` §5-1, `RTP_CUTOUT_APP_LOG_ANALYSIS_20260327.md` |
| **코드** | `sip-pbx/src/media/rtp_relay.py` — `RTPRelayWorker._pcm_sender_thread_main` |

---

## 1. 문제 (기존 동작)

- 송신 스레드는 **절대시간 격자** `target = base + N × 20ms` 로 패킷을보냄.
- `target`보다 늦게 루프가 도는 경우(`sleep_needed < 0`), **sleep·busy-wait 없이 즉시 전송**하고 다음 슬롯으로 진행.
- 한 PCM 청크 안에 여러 RTP 패킷이 있을 때, **여러 슬롯이 이미 지난 상태**면 **연속 즉시 전송** → 로그의 `interval_min_ms` ~0.37ms, `interval_max_ms` ~54ms 같은 **길게·짧게 쌍** 지터.
- RTP 페이로드의 seq/ts는 빌더가 유지하므로 **미디어 타임라인은 맞지만**, **와이어 간격 지터**가 단말 PLC/jitter buffer에 부담.

---

## 2. 설계 방안

### 2.1 최소 패킷 간격 (Min inter-send)

- 매 패킷마다 목표 시각을  
  `target_time = max(ideal_grid_time, last_send_time + 8ms)` 로 올림.
- **의도**: “조금 늦음” 구간에서 **sub-ms 연속 전송**을 막고, **최소 8ms** 이상 간격을 확보.
- 상수: `RTPRelayWorker._RTP_SCHED_MIN_INTER_SEND_MS = 8.0`

### 2.2 소프트 재동기화 (Soft resync)

- 위 조정 **후에도** `sleep_needed < -22ms` 이면, 구 격자를 포기하고:
  - `_rtp_base_time = now`
  - `_rtp_packets_sent_total = 0` (스케줄 카운터만 리셋; **RTP 헤더는 이미 빌드된 패킷 그대로**)
  - 이번 패킷은 **즉시** 보내고, 이후는 `now`, `now+20ms`, … 격자로 진행.
- **의도**: “무한 따라잡기” 버스트를 끊고 **수신기 관점에서 CBR에 가까운 간격**으로 재출발.
- 상수: `RTPRelayWorker._RTP_SCHED_SOFT_RESYNC_LATE_MS = 22.0` (약 1슬롯+α)
- **트레이드오프**: 재동기화 시점에 **월클럭 대비 미디어 타임과의 상대 위상**이 한 번 어긋날 수 있으나, 20ms 음성에서 일반적으로 청감·버퍼 쪽이 이득인 경우가 많음.

### 2.3 로그·통계

- `rtp_schedule_soft_resync`: 재동기화 시 (최대 15회 + 이후 40회마다).
- `stats["rtp_sched_soft_resync_count"]`: 누적 횟수.
- `rtp_sender_session_end`: `rtp_sched_soft_resync_count` 필드 추가.
- `rtp_send_behind_schedule`: **재동기화 직전의 소폭 지연**에만 유지 (`sleep_needed < 0` 이고 이번 틱에서 resync 안 함).

---

## 3. 구현 요약

| 변경 | 설명 |
|------|------|
| 클래스 상수 | `_RTP_PACKET_MS`, `_RTP_SCHED_MIN_INTER_SEND_MS`, `_RTP_SCHED_SOFT_RESYNC_LATE_MS` |
| `self.stats` | `rtp_sched_soft_resync_count` 초기화 0 |
| `_pcm_sender_thread_main` | `ideal_target` → `min_next` 클램프 → `sleep_needed` → 조건부 resync → 기존 sleep/busy-wait/send |

---

## 4. 검증 권장

1. 동일 시나리오 통화 후 `app.log`에서  
   `rtp_interval_violation` 빈도, `rtp_tts_send_window_stats`의 `interval_min_ms` / `interval_max_ms` 폭, `rtp_schedule_soft_resync` 발생 횟수 비교.
2. `rtp_sched_soft_resync_count`가 **과도하게** 쌓이면 `SOFT_RESYNC_LATE_MS`를 소폭 올리거나, 지연 원인(AEC 락, CPU)을 병행 조사.
3. `MIN_INTER_SEND_MS`를 10~12ms로 올리면 지터는 더 부드러울 수 있으나 **약간의 추가 지연**이 생길 수 있음.

---

## 5. 문서 §5와의 대응

- **§5-1 스케줄 정책 재검토**: 본 구현으로 **일정 한도 내 재동기화 + 최소 간격**을 코드에 반영.
- §5-4 Busy-wait 완화, §5-5 백프레셔는 **별도 과제** (본 변경과 독립).

---

*최종 업데이트: 2026-03-26*
