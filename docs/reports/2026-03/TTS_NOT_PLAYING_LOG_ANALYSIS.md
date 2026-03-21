# TTS가 실제로 나가지 않은 경우 로그 점검 (tTM8FBYDD2 예시)

**현상**: `tts_text_input` 에 "네, 그러게요.날씨가 많이 바뀌었죠." 가 찍혔는데, 실제로는 TTS가 나가지 않음.

---

## 1. 로그에서 확인된 원인 (call_id: tTM8FBYDD2, 12:21:03~04)

### 1.1 타임라인 요약

| 시각 | 이벤트 | 의미 |
|------|--------|------|
| 12:21:03.368 | `llm_exchange_full` | LLM 응답 "네, 그러게요. 날씨가 많이 바뀌었죠." 확정 |
| 12:21:03.368 | `tts_first_audio_received` | TTS 첫 오디오 청크 수신 |
| 12:21:03.485 | **tts_text_input** | 동일 문장이 TTS 입력으로 전달됨 (첫 번째) |
| 12:21:04.006 | `tts_first_audio_sent_to_rtp` | 이 응답의 **첫 오디오만** RTP 전송 (16000 bytes), pcm_chunk_queued chunk_seq=30 |
| 12:21:04.185 | `notifier_endframe_processed` | **58 프레임**, duration_sec **4.517** (TTS 쪽에서는 4.5초 분량 생성됨) |
| 12:21:04.190 | **tts_text_input** (동일 문장 **두 번째**) | 같은 문장이 다시 TTS 입력으로 들어옴 |
| 12:21:04.190 | `output_endframe_processed` | **response_audio_frame_count: 8**, response_bytes: 112652 (약 3.52초 분만 큐에 넣음) |
| 12:21:04.190 | **tts_rtp_duration_mismatch** (경고) | Notifier **58프레임(4.517초)** vs Output **8프레임(3.52초)** → **약 22%만 전송** |
| 12:21:04.643 | **rtp_tts_queue_flushed** | **drained_bytes: 112652, drained_chunks: 8** — "새 TTS 시작으로 PCM 큐 비움" |
| 12:21:05.655~ | `rtp_tts_queue_empty_timeout` 반복 | PCM 큐가 1초간 비어 있음 → 그 구간 **끊김/무음** |

### 1.2 결론 (이번 통화에서 TTS가 안 나간 이유)

1. **동일 응답이 TTS로 두 번 들어감**  
   - `tts_text_input` 이 같은 문장으로 **12:21:03.485** 와 **12:21:04.190** 에 두 번 찍힘.
2. **두 번째 입력이 “새 TTS”로 간주되어 큐 플러시 발생**  
   - 12:21:04.643 에 `rtp_tts_queue_flushed` 가 발생하며, 그 시점까지 큐에 있던 **112652 bytes(8 chunks)** 만 drain 되고 나머지는 버려짐.
3. **Notifier vs Output 불일치**  
   - TTS 쪽(Notifier)은 **58 프레임(4.517초)** 을 만들었는데, RTP로 “큐에 넣은” 쪽(Output)은 **8 프레임(약 3.52초)** 만 기록 → **tts_rtp_duration_mismatch** 경고.
4. **실제로는 8청크 분만 송출 후 플러시**  
   - 첫 오디오만 RTP로 나가고, 곧바로 “새 TTS 시작”으로 큐가 비워져서 **대부분의 TTS가 재생되지 않음**.

정리하면, **같은 문장이 두 번 TTS로 들어오면서 두 번째를 “새 TTS”로 처리해 큐를 플러시한 것**이, “TTS가 실제로 나가지 않았다”고 느껴진 직접 원인이다.

---

## 2. 로그만으로 원인을 찾을 때 보면 되는 것

- **`tts_text_input`**  
  - 같은 `text_chunk_0` / `text_suffix_60` 이 **짧은 시간 안에 두 번** 나오면, 중복 전달 가능성.
- **`tts_rtp_duration_mismatch`**  
  - `notifier_audio_frame_count`(또는 duration_sec) vs `output_audio_frame_count`(또는 rtp_sent_duration_sec) 차이가 크면, **일부만 RTP로 나가고 나머지는 버려졌을 가능성**.
- **`rtp_tts_queue_flushed`**  
  - **TTS가 “실제로 안 나갔다”** 고 느껴지는 구간 직후에 이 이벤트가 있으면, **플러시로 인해 재생이 끊긴 것**으로 의심.

현재 로그에는 **“왜 플러시가 발생했는지”** (예: 새 StartFrame 수신, 새 tts_text_input 수신, barge-in 등) 가 명시되지 않아, **같은 문장 두 번 입력** 은 `tts_text_input` 시간차로만 추론 가능하다.

---

## 3. 제안: 원인 추적용 로그 보강

다음과 같이 로그를 추가하면, 다음부터는 **“TTS가 안 나간 이유”** 를 로그만으로 더 명확히 볼 수 있다.

1. **`rtp_tts_queue_flushed` 발생 시**  
   - **flush 이유** 를 한 줄 필드로 추가  
     - 예: `reason: "StartFrame_received"` / `"new_tts_text_received"` / `"barge_in"` / `"pipeline_cancel"` 등.
   - 가능하면 **직전에 큐에 쌓여 있던 응답 식별자** (예: `response_preview` 60자, 또는 `phase_id`) 도 함께 로깅.

2. **`tts_text_input` 로깅 시**  
   - **동일 통화·짧은 구간 내 중복 여부** 를 알 수 있도록  
     - 직전 `tts_text_input` 의 시각(`last_tts_text_at`) 또는 `delta_sec_since_last_tts_input` 같은 필드를 선택적으로 추가.

3. **`tts_rtp_duration_mismatch` 로그**  
   - 이미 Notifier vs Output 수치가 있으므로 유지하고,  
   - 같은 구간에 **`rtp_tts_queue_flushed` 가 있었는지** 참고할 수 있도록  
     - 플러시가 발생한 직후 mismatch가 나오면, “플러시로 인해 대부분 미재생” 으로 해석 가능.

위와 같이 보강하면, “해당 TTS는 실제로 나가지 않았다” 는 경우에도 **로그만으로**  
- 같은 문장 이중 입력,  
- 새 TTS로 인한 조기 플러시,  
- Notifier vs RTP 전송량 불일치  
를 한 번에 추적할 수 있다.
