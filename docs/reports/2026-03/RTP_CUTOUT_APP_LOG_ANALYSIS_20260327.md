# app.log 기반 RTP·TTS 끊김 징후 분석

- **작성일**: 2026-03-26 (로컬)
- **로그**: `sip-pbx/logs/app.log` (샘플: `call_id` `bmAhYH9DxI` 중심)
- **참고 문서**: `RTP_SENDER_PATH_STRUCTURE_REVIEW.md` §5

---

## 1. 강화 로그로 본 결론 (요약)

| 관측 | 해석 |
|------|------|
| `rtp_relay_stopped` … `rtp_tts_packets_dropped`: **0**, `rtp_tts_send_errors`: **0** | **PCM 큐 포화 드롭·sendto 실패로 인한 “송신단 패킷 유실”은 이 구간에서 없음.** |
| `rtp_tts_send_window_stats`: `interval_avg_ms` ≈ **20**, 그러나 `interval_max_ms` **24~54ms**, `interval_min_ms` **0.37~17ms**, `interval_violations_cumulative` **수십** | **20ms 균일 송신이 아니라, 지연 후 “따라잡기”로 긴 간격·짧은 간격이 쌍을 이루는 지터** — 리뷰 문서 §3.1과 동일 패턴. |
| `rtp_send_behind_schedule` 소수 회, `behind_schedule_cumulative` **1~3** | 절대시각 기준 스케줄은 가끔 밀리나, 누적은 크지 않음. |
| `pcm_queue_size` **대략 5~23** (max 150 대비 여유) | **백프레셔/큐 포화 직전 상태는 아님.** |
| `rtp_tts_queue_empty_timeout`, `packets_sent`가 구간마다 **증가** (예: 852 → 1425 → 1838 → 2105) | **TTS 청크 사이·LLM 대기 등으로 PCM 공급이 끊기는 “무음 구간”**은 정상적으로도 발생; `packets_sent`가 멈추지 않으면 “송신 스레드가 멈춤”은 아님. |
| `rtp_interval_violation` 개별 로그: 예) **28ms 직후 13ms**, **30.5ms 직후 9.5ms** | 전형적인 **catch-up 지터** 쌍. |

**한 줄:** 이 로그에서는 **UDP/큐 드롭보다 “절대시간 스케줄 + 따라잡기”에 따른 송신 간격 지터**와 **TTS·상위 파이프라인이 PCM을 공급하지 않는 구간(무음)** 이 “끊김” 체감의 주된 원인 후보에 가깝다.

---

## 2. `RTP_SENDER_PATH_STRUCTURE_REVIEW.md` §5 대응

| 항목 | 효과 예상 (이 로그 기준) | 비고 |
|------|-------------------------|------|
| **1. 스케줄 정책 재검토** | **가장 효과적** | `interval_violation`·min/max 벌어짐이 명확. “늦었을 때 무조건 따라잡기” 대신 **한도 있는 재동기화** 또는 **수신기 관점 CBR에 가깝게**내면 단말 PLC 부담 감소 기대. |
| **2. 송신 루프 격리** | 이미 구현됨 | `behind_schedule` 누적이 크지 않아, **추가 격리만으로는 지터 쌍이 사라지지 않을 수 있음** (스케줄 정책 이슈). |
| **3. 녹음 경로** | 청취 품질과 직접 무관 | 드롭/부하 완화용; 이 trace에는 `packets_dropped` 0. |
| **4. Busy-wait 완화** | **보조적 효과** | 같은 프로세스 내 STT·파이프라인과 CPU 경합 완화 → 간접적으로 `behind_schedule`·지터 감소 가능. 단독 해법은 아님. |
| **5. 백프레셔** | **이 로그에서는 우선순위 낮음** | `pcm_queue_size`가 포화에 가깝지 않고, `pipecat_pcm_queue_full` 유무는 이 파일에서 드롭 이벤트 없음. **큐가 자주 찰 때** 의미 있음. |

---

## 3. §5 밖 보완 방안

- **TTS/LLM 측**: 청크 사이 `rtp_tts_queue_empty_timeout` 구간이 길면 단말은 무음·끊김으로 느낌 → **스트리밍 TTS 청크 연속성**, **짧은 휴지용 comfort noise(정책 허용 시)** 검토.
- **단말/네트워크**: 동일 프로세스가 깨끗해도 **Wi‑Fi·VPN·Jitter buffer**는 별도.
- **이중 통화·STT 싱글톤**: 과거 이슈처럼 파이프라인이 막히면 **PCM 자체가 안 들어옴** (`packets_sent` 정체) — 본 로그는 송신은 진행 중.

---

## 4. 권장 우선순위

1. **스케줄러 정책 개선** (§5-1) — 로그 증거와 직접 정합.  
2. **Busy-wait 완화** (§5-4) — 부하 환경에서 1번을 보조.  
3. **백프레셔** (§5-5) — `pcm_queue_size`·`pipecat_pcm_queue_full_dropping`이 반복될 때 도입.  
4. **녹음/격리** — 이미 된 부분은 유지·모니터링만.

---

*본 분석은 제공된 `app.log` 스냅샷에 한정되며, 다른 통화·부하에서는 `packets_dropped`·`sendto_failed`가 나올 수 있으므로 해당 이벤트는 항상 교차 확인할 것.*
