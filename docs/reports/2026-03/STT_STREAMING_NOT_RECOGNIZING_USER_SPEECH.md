# 통화 중 사용자 발화("네 저는 오늘의 날씨가 궁금 합니다")가 STT에 인식되지 않은 이유

## 1. 현상

- 사용자가 통화 중 **"네 저는 오늘의 날씨가 궁금 합니다"**라고 말함.
- 통화 중에는 이 발화로 AI가 반응하지 않음.
- **통화 종료 후** 녹음 파일(mixed.wav)에 대한 **사후 STT**(stt_post_process)에서는 동일 문장이 정상 인식됨:  
  `발신자: 네 저는 오늘의 날씨가 궁금 합니다`

즉, **녹음에는 말소리가 들어가 있지만**, **실시간 스트리밍 STT**에는 인식되지 않은 상태.

---

## 2. 로그 타임라인 (올바른 해석)

| 시각 | 이벤트 |
|------|--------|
| 19:47:07.305 | **AI call handling started** — 인사말 종료, 본격 사용자 발화 대기 구간 |
| 19:47:07 ~ 19:47:29 | 사용자가 이 구간에 발화("네 저는 오늘의 날씨가 궁금 합니다") |
| 19:47:29.803 | **BYE** 수신 — 통화 종료 |
| 19:47:29.819 | Mixed WAV 저장, stt_post_process 시작 |
| 19:47:36.262 | 사후 STT 완료 — "발신자: 네 저는 오늘의 날씨가 궁금 합니다" 인식 |
| 19:47:36.278 | call_cleaned_up, rtp_relay_stopped |
| **19:47:39.958** | **STT streaming error** — `400 Audio Timeout Error: Long duration elapsed without audio.` |
| 19:47:39.958 | STT streaming ended |

**중요**: **Audio Timeout(19:47:39.958)은 전화가 끊긴 후(BYE 19:47:29)에 발생한 것이다.**  
통화가 끝나서 RTP로 더 이상 오디오가 오지 않고, 파이프라인/스트림이 정리되면서 Google 스트리밍 세션이 “오디오 없음”으로 타임아웃된 것이다.  
즉, **타임아웃은 원인이 아니라 “통화 종료”의 결과**로 보는 것이 맞다.

---

## 3. 올바른 원인 정리: AI call handling started 이후 발화 오디오가 STT까지 도달하지 않음

실제로 짚어야 할 부분은 다음이다.

- **AI call handling started(19:47:07) 이후** 사용자가 말했지만,
- 그 **발화 오디오가 스트리밍 STT까지 도달하지 않았다.**

그래서 “통화 중 STT가 동식하지 않은 것처럼” 보인다.  
(타임아웃 때문에 세션이 먼저 끊겨서 그런 것이 아니다.)

---

## 4. 가능한 원인: RTP → 큐 → 파이프라인 → STT 구간

오디오 경로는 다음과 같다.

1. **RTP** (caller) → `on_packet_received` → PCM 변환 → **`_pipecat_audio_queue.put_nowait(pcm_data)`**
2. **Input Transport** `_read_audio_loop`: **`async for pcm_data in get_caller_audio_stream()`** → **`await push_frame(InputAudioRawFrame(...))`**
3. **get_caller_audio_stream**: **`await _pipecat_audio_queue.get(timeout=5.0)`** → yield
4. 파이프라인: Input → rec_input → VAD → BargeInSuppress → **STT** → RAG → …

즉, **caller 오디오가 STT에 도달하려면**  
RTP에서 큐에 넣고 → Input이 큐에서 꺼내서 → `push_frame`으로 파이프라인에 넣어야 한다.

### 4.1 큐가 소비되지 않는 경우 (파이프라인 블로킹)

- **Input Transport**는 `get_caller_audio_stream()`에서 한 번에 하나씩 꺼내서 **`await push_frame(frame)`** 한다.
- `push_frame`은 다운스트림(rec_input → VAD → STT → RAG …)을 **한 번 통과할 때까지** 대기한다.
- 이 구간 어디선가 **한 프레임 처리에 오래 걸리거나 블로킹**되면,  
  Input이 다음 `queue.get()`을 하지 못하고, **큐 소비가 멈춘다.**
- 그러면 **`_pipecat_audio_queue`(maxsize=1000)** 가 가득 찬 뒤,  
  RTP 쪽에서는 **`put_nowait` 실패 → `stt_input_queue_full_dropping`** 으로 **caller PCM을 드롭**한다.
- 결과: **AI call handling started 이후 사용자 발화 오디오가 큐에 쌓이지도 못하거나, 큐에는 들어가지만 파이프라인으로 넘어가지 못하고**, 결국 **STT까지 도달하지 않는다.**

### 4.2 그 외 가능성

- **RTP가 AI 구간에서 caller 오디오를 큐에 넣지 않는 경우** (조건 분기, 모드 전환 등):  
  로그에 `caller_rtp_to_stt_input` / `stt_input_queue_full_dropping` 등으로 어느 쪽인지 어느 정도 구분 가능.
- **파이프라인 중간에서 오디오 프레임을 버리거나 막는 경우**:  
  VAD/BargeInSuppress 등에서 InputAudioRawFrame을 조건부로 전달하지 않으면 STT에는 안 간다.

---

## 5. 정리

| 구분 | 내용 |
|------|------|
| **녹음/사후 STT** | 통화 녹음(mixed.wav)에는 발화가 포함되어 있고, **stt_post_process**에서 "네 저는 오늘의 날씨가 궁금 합니다" 정상 인식. |
| **Audio Timeout** | **전화가 끊긴 후(BYE 이후)** 에 발생. 통화 종료로 오디오 공급이 끊기면서 나중에 Google이 반환한 에러로 보는 것이 맞음. **원인이라기보다 결과.** |
| **실제 원인 방향** | **AI call handling started 이후** 사용자가 말했지만, 그 **발화 오디오가 스트리밍 STT까지 도달하지 않았다.** 가능성: (1) 파이프라인 블로킹으로 큐 소비 정지 → 큐 풀 → RTP에서 caller PCM 드롭, (2) RTP→큐 투입 자체가 안 되거나, (3) 파이프라인 중간에서 오디오가 STT로 전달되지 않음. |

즉,  
- **“타임아웃 때문에 세션이 먼저 끊겨서 말이 안 들렸다”**가 아니라,  
- **“말은 했는데, 그 오디오가 STT에 도달하지 않았다”**를 전제로 원인을 보는 것이 맞다.

---

## 6. 점검/개선 방향

1. **로그 확인**
   - **`stt_input_queue_full_dropping`**: 이 구간에 찍히면, 큐가 가득 차서 caller PCM이 버려지고 있다는 뜻.  
     → 파이프라인(Input → … → STT)이 큐를 충분히 소비하지 못하는지 확인.
   - **`caller_rtp_to_stt_input`**: 19:47:07 이후에도 패킷이 계속 들어오는지, **`input_audio_frame_to_pipeline`**: Input이 파이프라인으로 프레임을 넣는지.
   - **`pipecat_audio_stream_no_data`**: 5초 동안 큐에서 꺼낸 데이터가 없을 때.  
     통화 중에 반복되면 RTP→큐 투입이 안 되거나, 다른 쪽에서 큐를 비우고 있는지 확인.

2. **파이프라인 블로킹**
   - 인사말이 끝난 뒤(Phase2 완료, AI call handling started)에도  
     RAG 등에서 **오래 걸리는 동기 처리**나 **블로킹 대기**가 있으면,  
     Input의 `push_frame`이 늦게 돌아와서 큐 소비가 지연되고, 결국 드롭으로 이어질 수 있음.
   - Phase2 이후 **caller 오디오만** 계속 흘려보내도 되는지,  
     파이프라인 설계(특히 RAG/LLM 호출과 오디오 경로 분리)를 한 번 점검하는 것이 좋음.

3. **큐 크기/타임아웃**
   - STT 입력 큐(maxsize=1000)와 `get_caller_audio_stream`의 5초 타임아웃이,  
     "AI call handling started 이후" 발화를 흡수하기에 충분한지 검토.

이 문서는 **“Audio Timeout은 끊긴 후 발생”**이고, **“실제 문제는 AI call handling started 이후 발화 오디오가 STT에 도달하지 않은 것”**이라는 분석에 맞춰 수정한 내용이다.

---

## 7. STT 경로 점검용 로그 (원인 밝히기)

아래 이벤트를 **call_id** 기준으로 시간순으로 보면, **어디에서 오디오가 끊기는지** 추적할 수 있다.

| 이벤트 | 구간 | 확인할 것 |
|--------|------|------------|
| **stt_path_rtp_to_queue** | RTP → 큐 | `packet_count` 증가, `queue_size` / `queue_max`. 200패킷마다. |
| **stt_path_queue_full_drop** | 큐 풀 시 | 나오면 파이프라인 소비 지연으로 caller PCM 드롭. |
| **stt_path_queue_to_consumer** | 큐 → Input | `packets_consumed` 증가. 200개마다. 소비 여부. |
| **stt_path_queue_timeout** | 큐 get 5초 대기 | `packets_consumed_so_far`. 0이면 한 번도 소비 안 됨. |
| **stt_path_input_to_pipeline** | Input → 파이프라인 | `frame_count` 200마다. Input이 push 하고 있는지. |
| **stt_path_input_total** | Input 종료 시 | `total_frames`. 통화 끝까지 파이프라인에 넣은 총 프레임 수. |
| **stt_path_stt_to_rag** | STT → RAG | `seq`, `text_len`. STT 최종 결과가 RAG에 도달한 횟수. |

**점검 순서**: (1) stt_path_rtp_to_queue 가 AI call handling started 이후에도 나오는지 (2) stt_path_queue_full_drop 나오는지 (3) stt_path_queue_to_consumer / stt_path_input_to_pipeline 이 증가하는지 (4) stt_path_stt_to_rag 가 나오는지. 위 로그로 RTP → 큐 → Input → STT → RAG 중 끊기는 구간을 좁힐 수 있다.

테스트 후 **동작 여부 한눈에 점검**하려면 [DEBUG_LOG_VERIFICATION.md](DEBUG_LOG_VERIFICATION.md) 의 STT 경로 체크리스트를 참고하면 된다.
