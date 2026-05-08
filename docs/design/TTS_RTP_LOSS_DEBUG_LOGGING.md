# TTS ↔ RTP 손실 원인 분석 및 디버깅 로그 강화
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


## 1. 현상 정리

- **인사말(Phase1/Phase2)**: 체감상 손실 없음 (또는 상대적으로 적음).
- **이후 대답**(대기 안내, 최종 응답): `tts_rtp_duration_mismatch` 발생 — Notifier 프레임/길이에 비해 Output 큐 투입이 적음 → **RTP 구간에서 손실 가능성**.

로그 상으로는 Phase1/Phase2에서도 Notifier vs Output 수치 불일치가 있으나, 인사말은 **flush 없이 연속 재생**되고, 이후 응답은 **flush → 새 StartFrame → 새 TTS** 경로를 타서 동작이 다름.

---

## 2. 인사말은 괜찮고 이후 응답에서만 손실이 나는 이유 (추정)

| 추정 원인 | 설명 |
|-----------|------|
| **flush 이후 경로 차이** | 인사말은 파이프라인 시작 직후 한 번에 스트리밍. 이후 응답은 `tts_flush_requested_nonblocking` 후 **StartFrame → TTS 청크**가 새로 들어옴. 이때 **flush 직후 또는 StartFrame 직후**에 오는 청크가 Output(큐 투입)까지 도달하지 못하고 누락될 수 있음. |
| **첫 청크 누락** | 새 응답의 **첫 TTSAudioRawFrame**이 Notifier에는 들어오지만, Output 쪽에서 “이전 응답 종료” 처리와 “새 응답 시작” 처리 사이에서 **첫 몇 청크가 버려지거나 카운트에서 제외**될 수 있음. |
| **응답 경계에서 카운트 리셋 타이밍** | Notifier는 “이 응답에서 받은” 프레임/바이트를 세고, Output은 “이 응답에서 큐에 넣은” 값을 셀 때, **EndFrame 도달 순서**나 **응답 ID 구분**이 다르면 한쪽만 리셋되거나 늦게 리셋되어 불일치가 커질 수 있음. |
| **청크 단위 vs 프레임 단위** | Notifier `audio_frame_count`는 TTS 엔진의 (예: 320샘플) 프레임 수, Output `response_audio_frame_count`는 “큐에 넣은 청크 수”로 해석되는 경우 — 단위가 다르면 비율로만 보이지만, **response_bytes**까지 Notifier 기대 바이트보다 작으면 **실제 바이트 손실**임. |

**정리**: 인사말은 **단일 연속 스트림**이라 flush/경계 이슈가 없고, **이후 응답만** flush·StartFrame·응답 경계를 거치면서 첫 청크 누락 또는 경계 처리 버그로 손실이 발생하는 것으로 추정됨.

---

## 3. 디버깅용 로그 강화 스펙

아래 로그를 추가하면 “어느 구간에서 손실이 나는지”를 좁혀갈 수 있음. (실제 구현은 TTS/Output/Notifier를 가진 백엔드 저장소에서 적용.)

### 3.1 응답(Phase) 식별자

- 모든 TTS/ RTP 관련 로그에 **`response_id`** 또는 **`phase`** 필드 추가.
  - 예: `response_id: "phase1" | "phase2" | "resp_1" | "resp_2"` 또는 `phase: 1, 2, 3, ...`
- 동일 응답의 Notifier 로그와 Output 로그를 **response_id/phase**로 묶어서 비교 가능하게 함.

### 3.2 Notifier 측 (TTS → Notifier)

| 이벤트 | 시점 | 권장 필드 |
|--------|------|------------|
| `tts_response_started` | 해당 응답의 StartFrame 수신 시 (또는 첫 TTSAudioRawFrame) | `call_id`, `response_id`, `phase` |
| `notifier_audio_chunk_received` | (선택) TTS 오디오 청크/프레임 수신 시 누적만 로그 | `call_id`, `response_id`, `cumulative_bytes`, `cumulative_frames`, `chunk_index` |
| `notifier_endframe_processed` | (기존) EndFrame 수신 시 | 기존 + `response_id`, `phase`, **`total_bytes_this_response`** (이 응답에서 받은 총 바이트). Notifier 쪽에서 바이트 합산이 있다면 함께 기록. |

- **total_bytes_this_response**: 이 응답에서 Notifier가 받은 오디오 바이트 합. (현재 `duration_sec`만 있으면 `duration_sec * sample_rate * 2`로 기대 바이트 계산 가능하지만, 실제 누적 바이트가 있으면 더 정확함.)

### 3.3 Output 측 (큐 투입)

| 이벤트 | 시점 | 권장 필드 |
|--------|------|------------|
| `output_response_started` | 해당 응답에 대한 첫 청크를 큐에 넣기 직전 | `call_id`, `response_id`, `phase` |
| `pcm_chunk_queued` | (기존) 청크 큐 투입 시 | 기존 + **`response_id`**, **`phase`**, **`cumulative_bytes_this_response`** (이 응답에서 지금까지 큐에 넣은 누적 바이트). |
| `output_endframe_processed` | (기존) EndFrame 수신 시 | 기존 + `response_id`, `phase`, **`total_bytes_this_response`** (이 응답에서 큐에 넣은 총 바이트 = response_bytes와 동일 개념을 명시). |

- **누적 바이트**를 응답 단위로 유지하려면, StartFrame 또는 “새 응답 시작” 시점에 `cumulative_bytes_this_response`를 0으로 리셋하고, 각 `pcm_chunk_queued`에서만 해당 응답의 청크 바이트를 더해 로그에 남기면 됨.

### 3.4 불일치 시 상세 (tts_rtp_duration_mismatch 확장)

| 기존 | 추가 권장 필드 |
|------|-----------------|
| `tts_rtp_duration_mismatch` | **`response_id`**, **`phase`**, **`notifier_total_bytes`**, **`output_total_bytes`**, **`bytes_diff`**, **`first_chunk_queued_ts`** (이 응답에서 첫 pcm_chunk_queued 시각), **`notifier_first_frame_ts`** (이 응답에서 Notifier가 첫 오디오 받은 시각). |

- `bytes_diff = notifier_total_bytes - output_total_bytes` 로 실제 손실 바이트 추정.
- `first_chunk_queued_ts` vs `notifier_first_frame_ts` 로 “첫 청크가 큐에 늦게 들어가는지” 여부 확인 가능.

### 3.5 flush / StartFrame 경계

| 이벤트 | 시점 | 권장 필드 |
|--------|------|------------|
| `tts_flush_requested_nonblocking` | (기존) | 기존 + **`next_response_id`** (다음에 올 응답 식별자, 알 수 있으면). |
| `tts_startframe_after_greeting` | (기존) “이후 TTS 시작” | 기존 + **`response_id`**, **`phase`**. |
| `tts_first_audio_received` | (기존) 해당 응답의 첫 오디오 | 기존 + **`response_id`**, **`phase`**. |
| `output_first_chunk_queued_for_response` | **신규** | 해당 **response_id**에 대해 Output이 **처음으로** 큐에 청크를 넣은 시점. `call_id`, `response_id`, `phase`, `pcm_bytes`, `chunk_seq`, `ts_iso`. |

- “인사말 이후” 응답에서만 **output_first_chunk_queued_for_response**가 **notifier 첫 오디오**보다 현저히 늦거나, 첫 청크 바이트가 0이면 → flush/StartFrame 직후 첫 청크 누락 의심.

### 3.6 요약 로그 (응답 단위)

| 이벤트 | 시점 | 권장 필드 |
|--------|------|------------|
| `tts_rtp_response_summary` | 해당 응답의 EndFrame 처리 직후 (mismatch 여부와 무관) | `call_id`, `response_id`, `phase`, `notifier_frames`, `notifier_bytes`, `output_chunks`, `output_bytes`, `bytes_match`, `duration_sec`. |

- `bytes_match = (abs(notifier_bytes - output_bytes) <= threshold)` 로 손실 여부를 항상 한 줄로 확인 가능.

---

## 4. 구현 체크리스트 (백엔드)

- [ ] 모든 TTS/Notifier/Output 로그에 `response_id` 또는 `phase` 추가.
- [ ] Notifier: 이 응답에 대한 **total_bytes_this_response** (또는 duration_sec과 sample_rate로 기대 바이트)를 `notifier_endframe_processed`에 포함.
- [ ] Output: `pcm_chunk_queued`에 `response_id`, `cumulative_bytes_this_response` 추가; `output_endframe_processed`에 `total_bytes_this_response`(= response_bytes) 명시.
- [ ] `tts_rtp_duration_mismatch`에 `response_id`, `notifier_total_bytes`, `output_total_bytes`, `bytes_diff`, (가능하면) `first_chunk_queued_ts`, `notifier_first_frame_ts` 추가.
- [ ] **output_first_chunk_queued_for_response** 신규 로그: 각 response_id에 대해 큐에 첫 청크를 넣을 때 1회만 기록.
- [ ] (선택) **tts_rtp_response_summary** 로그로 응답 단위 요약 출력.

이 스펙을 적용한 뒤, **인사말(phase1/2)** 과 **이후 응답(resp_1, resp_2)** 의 `bytes_diff`, `first_chunk_queued_ts` 차이를 비교하면 “flush/경계 이후에서만 손실이 나는지” 여부를 확인할 수 있음.
