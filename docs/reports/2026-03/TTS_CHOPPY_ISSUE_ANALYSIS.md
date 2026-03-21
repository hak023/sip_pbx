# TTS 끊김 이슈 정리: 인사말은 정상, 이후 TTS만 끊기는 경우

**현상**: 인사말 Phase1·Phase2는 정상 송출되나, **사용자 발화에 대한 AI 응답 TTS**가 끊기거나 끊겨 들리는 현상.

---

## 1. 인사말 vs 이후 TTS 경로 차이

### 1.1 공통 흐름

- **RAGLLMProcessor** → `LLMFullResponseStartFrame` → `TextFrame(text=...)` → `LLMFullResponseEndFrame`
- TTS가 TextFrame을 받아 합성 후 **TTSAudioRawFrame/OutputAudioRawFrame**으로 출력
- **SIPPBXOutputTransport**가 오디오를 받아 `rtp_worker.send_audio_to_caller()`로 RTP 큐에 적재
- RTP Worker 측에서 20ms 간격 등으로 실제 RTP 전송

### 1.2 차이: PCM 큐 Flush 여부

| 구간 | `LLMFullResponseStartFrame` 수신 시 flush | 비고 |
|------|------------------------------------------|------|
| **인사말 Phase1** | **하지 않음** | `_session_has_sent_audio == False` → 첫 응답이라 flush 스킵 |
| **인사말 Phase2** | **하지 않음** | `_greeting_phase2_no_flush == True` (RAG에서 설정) → Phase1 꼬리 잘림 방지 |
| **이후 TTS (사용자 턴 응답)** | **함** | `request_tts_flush()` 호출 → 기존 PCM 큐 비우기 |

**코드 위치**: `src/ai_voicebot/pipecat/rtp_transport.py`  
`SIPPBXOutputTransport.process_frame()` 내 `LLMFullResponseStartFrame` 처리:

```python
skip_flush = self._tts_sync_context.pop("_greeting_phase2_no_flush", False)
if self._session_has_sent_audio and not skip_flush:
    # 논블로킹: create_task 또는 run_in_executor로 flush 요청만 하고 대기하지 않음
    _req_flush = getattr(self._rtp_worker, "request_tts_flush", None)
    if _req_flush is not None:
        if asyncio.iscoroutinefunction(_req_flush):
            asyncio.create_task(_req_flush())
        else:
            asyncio.get_event_loop().run_in_executor(None, _req_flush)
```

- 인사말 1·2는 **flush 없이** 연속으로 PCM이 쌓였다가 RTP로 나감.
- **이후 TTS**는 매번 새 응답 시작 시점에 **flush를 비동기로 요청**한 뒤 곧바로 다음 프레임(TextFrame) 진행.

---

## 2. 끊김 원인 가설

### 2.1 Flush 타이밍/블로킹

- **StartFrame** 수신 시 **await request_tts_flush()** 로 큐를 비움.
- 이때 `request_tts_flush()`가 **동기적으로 오래 걸리거나**, RTP Worker 쪽에서 큐를 비우는 동안 **대기**하면:
  - 파이프라인이 해당 구간에서 블로킹되고
  - TTS가 만들어 낸 **첫 오디오 프레임이 Output으로 늦게 도달**할 수 있음.
- 그 결과 **첫 음성이 늦게 나오거나**, RTP 구간에서 **공백이 생겨 끊겨 들릴 수 있음**.

### 2.2 Flush 직후 공백

- Flush로 큐가 비워진 직후, TTS는 아직 **첫 청크를 생성하지 않은 상태**일 수 있음.
- 그 사이 RTP sender는 **보낼 PCM이 없어** `rtp_tts_queue_empty_timeout` 이 반복되고,
- 로그에 나온 것처럼 **packets_sent가 일시 정지**하는 구간이 생기면, 그 구간이 **침묵/끊김**으로 들릴 수 있음.

### 2.3 tts_rtp_duration_mismatch

- Notifier(음원 길이)와 Output(큐에 넣은 양) 불일치가 15~20% 수준으로 보고됨.
- sample_rate 불일치나 **일부 프레임 누락** 가능성이 있으면, 재생이 **중간에 끊기거나** 길이가 짧게 들릴 수 있음.

### 2.4 RTP 간격 지터

- `rtp_interval_violation` (expected 20ms vs actual 7~33ms)가 많으면,
- 누적 시 **지터/끊김** 느낌을 줄 수 있음 (보조 요인).

---

## 3. 권장 조치

### 3.1 Flush를 논블로킹으로 처리 (적용)

- **목적**: `LLMFullResponseStartFrame` 처리 시 파이프라인이 flush 완료를 기다리지 않도록 함.
- **방법**: `request_tts_flush()` 호출을 **기다리지 않고** 백그라운드로 실행.
  - `request_tts_flush`가 **async**이면 `asyncio.create_task()`로 스케줄.
  - **sync**이면 `asyncio.to_thread()`(또는 `run_in_executor`)로 실행.
- **효과**: StartFrame 처리 후 곧바로 다음 프레임(TextFrame 등)이 TTS로 흐르고, TTS 첫 오디오가 더 일찍 Output에 도달할 수 있어, flush로 인한 끊김을 완화할 수 있음.

### 3.2 RTP Worker 쪽 점검

- **`request_tts_flush()` 구현** 확인:
  - 큐만 비우고 즉시 반환하는지, 아니면 “다 보낼 때까지 대기”하는지.
  - 가능하면 **비동기·즉시 반환**으로 두고, 실제 전송은 기존 sender 루프에 맡기는 편이 유리.
- **큐가 이미 비어 있을 때** flush를 no-op으로 두면, 불필요한 지연을 줄일 수 있음.

### 3.3 로그로 검증

- **이후 TTS** 구간에서:
  - `tts_first_audio_sent_to_rtp` 와 `output_endframe_processed` 시각 차이
  - `rtp_tts_queue_empty_timeout` 발생 횟수·시각
  - `tts_rtp_duration_mismatch` 발생 여부
- 위를 비교해, flush를 논블로킹으로 바꾼 **전후**로 첫 오디오 지연·공백 구간이 줄었는지 확인.

### 3.4 (선택) 첫 사용자 턴만 flush 스킵 실험

- 인사말 직후 **첫 번째 사용자 발화 응답**에서만 `_greeting_phase2_no_flush`와 유사한 플래그를 두어 **flush를 한 번 스킵**해 보는 방법.
- Phase2 종료 후에는 큐가 이미 비어 있을 가능성이 높아, 이때는 flush가 실질적으로 불필요할 수 있음.
- 실험으로 “첫 사용자 턴만 no flush”일 때 끊김이 사라지면, **flush 타이밍/블로킹**이 주원인일 가능성이 큼.

---

## 4. 요약

| 구분 | 인사말 1·2 | 이후 TTS |
|------|-------------|----------|
| **Flush** | 하지 않음 | 매번 `request_tts_flush()` |
| **흐름** | Start → Text → … → End 가 연속으로 이어짐 | Start 시 flush → Text → TTS 합성 → 오디오 |
| **끊김 가능성** | 낮음 (flush 없음) | flush 블로킹·직후 공백·mismatch 등으로 끊김 가능 |

**권장**:  
1) Output에서 **flush 호출을 논블로킹**으로 변경 (이미 적용됨),  
2) RTP Worker의 **request_tts_flush** 동작을 점검·정리한 뒤,  
3) 동일 시나리오로 **로그·청취 테스트**로 끊김 감소 여부를 확인하는 순서로 진행하는 것이 좋음.

---

## 5. 로그 기반 분석 (실제 로그 예시)

### 5.1 인사말 구간 (정상)

- `tts_first_audio_sent_to_rtp`: 이 응답의 **첫 오디오**가 RTP 큐에 넣어진 시점.
- 인사말은 **StartFrame 시 flush 없음** → Phase1 TextFrame → TTS 합성 → 오디오가 **끊김 없이** 큐에 누적.
- `notifier_endframe_processed` / `output_endframe_processed`: EndFrame 시점의 재생 길이·큐 투입량.
- `tts_rtp_duration_mismatch`: Notifier(음원 길이) vs Output(큐에 넣은 양) 불일치 시 경고. 인사말에서도 10~15% 차이 나면 **프레임 누락·sample_rate 차이** 가능성.

### 5.2 이후 TTS 구간에서 끊김 시 확인할 로그

| 로그 이벤트 | 의미 | 끊김과의 관계 |
|-------------|------|-------------------------------|
| `tts_flush_requested_nonblocking` | 이후 TTS 시작 시 flush 비동기 요청 | flush 직후 공백이 길면 여기서부터 공백 시작 |
| `tts_first_audio_sent_to_rtp` | 해당 응답의 **첫 오디오** RTP 투입 시점 | 이 시점이 flush 요청보다 **너무 늦으면** 공백/끊김 구간 |
| `rtp_tts_queue_depleted` | PCM 큐 소진 | 다음 TTS 청크가 올 때까지 **전송할 데이터 없음** → 끊김 가능 |
| `rtp_tts_queue_empty_timeout` | 큐가 1초간 비어 있음 | 해당 구간이 **침묵/깨짐**으로 들릴 수 있음 |
| `rtp_interval_violation` | 20ms 기대 간격 이탈 | 누적 시 지터·끊김 느낌 (보조 요인) |

### 5.3 app.log 타임라인 예 (2026-03-14 15:51)

- **15:51:01.549** `tts_first_audio_sent_to_rtp`: 인사말(Phase1+2) 첫 오디오 RTP 투입.
- **15:51:03.454** `notifier_endframe_processed` duration_sec=14.874 (인사말 전체 재생 길이).
- **15:51:03.460** `tts_rtp_duration_mismatch`: Notifier 14.874s vs RTP 12.681s → **약 14.7% 불일치** (인사말 구간에서도 일부 누락 가능).
- **15:51:15.375** `rtp_tts_queue_depleted`: 인사말 송출 완료 후 큐 소진.
- **15:51:16.401** ~ **15:51:24.411** `rtp_tts_queue_empty_timeout` 반복: **이후 TTS가 없음** (사용자 발화 "오늘의 날씨가 궁금해요" 처리 중 `user_message_worker_error` 발생 → LLM 응답/TTS 미생성).

**결론**: 해당 통화에서는 **이후 TTS가 한 번도 생성되지 않아** RTP 끊김처럼 보였음.  
정상적으로 이후 TTS가 나올 때는 위 표의 로그로 **flush 요청 시각 ↔ tts_first_audio_sent_to_rtp 시각** 차이, **rtp_tts_queue_empty_timeout** 발생 횟수를 보면 공백/끊김 원인 구분에 도움이 됨.
