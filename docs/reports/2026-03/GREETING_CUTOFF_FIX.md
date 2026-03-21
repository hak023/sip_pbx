# 인사말 잘림 현상 원인 및 수정

## 1. 현상

- **들리는 소리**: 인사말 Phase1·Phase2가 TTS 로그(완료·duration)와 다르게 **잘려서** 들림.
- **로그**: Phase2 텍스트가 "저는 날씨 예보, 기상 특보, 과거 기상 데이터 조회, 기상 상식 안내, 그리고 기상청 담" 처럼 **끝이 잘린 것처럼** 보임 (실제 전송 텍스트는 전체일 수 있음 — 로그 미리보기 한계).

---

## 2. 원인

### 2.1 Phase1·Phase2 잘려 들리는 이유 (PCM 큐 flush)

- Pipecat Output에서 **새 TTS 응답(LLMFullResponseStartFrame)** 이 올 때마다 `request_tts_flush()` 를 호출해 **PCM 큐를 비움**.
- **Phase2 StartFrame** 이 오면, 그 시점에 큐에 **아직 Phase1 꼬리**가 남아 있을 수 있음.
- 이때 flush 하면 **남은 Phase1 PCM이 전부 버려져** Phase1이 잘려 들림.
- Phase2도, 그 다음 응답에서 flush 가 일어나면 동일하게 꼬리가 잘릴 수 있음.

즉, **인사말 Phase1 → Phase2 전환 시** 에만이라도 flush 를 하지 않아야 Phase1 꼬리가 보존됨.

### 2.2 Phase2 텍스트가 잘린 것처럼 보이는 이유

- **실제 TextFrame** 에는 전체 문자열이 들어가 있음 (`capability_guide` 전체).
- 로그에 찍을 때 **미리보기만** (예: 50자, 100자) 넣어서, 로그 상으로는 끝이 잘린 것처럼 보였을 가능성이 큼.
- TTS 엔진/외부 로그에서 짧은 preview 만 찍는 경우도 동일한 효과.

---

## 3. 적용한 수정

### 3.1 Phase1 → Phase2 전환 시 flush 스킵

- **RAG** `send_greeting()`: Phase2를 보내기 직전에  
  `tts_sync_context["_greeting_phase2_no_flush"] = True` 설정.  
  Phase2 StartFrame·TextFrame·EndFrame 전송 후 해당 키 제거.
- **Output** `process_frame(LLMFullResponseStartFrame)`:  
  `_greeting_phase2_no_flush` 가 있으면 **`request_tts_flush()` 를 호출하지 않음** 하고,  
  `tts_flush_skipped_greeting_phase2` 로그로 한 번 기록.

→ 인사말 구간에서는 Phase1 꼬리가 flush 로 버려지지 않아, **Phase1·Phase2가 잘리지 않고** 들리도록 함.

### 3.2 로그 강화 (잘림·텍스트 길이 확인)

- **RAG**
  - `greeting_phase1_sent`: `text_len`, `text_full` 추가.
  - `greeting_phase2_sent`: `text_len`, `text_full`, `text_preview` 추가.  
  → Phase1/Phase2 **전체 텍스트 길이와 내용**을 로그에서 확인 가능.
- **Output** `tts_text_input`:  
  `text_len`, `text_preview`, `text_full` 로 TTS 로 전달되는 **전체 문자열** 확인 가능.
- **RTP 발송 루프** `_TTS_FLUSH` 처리 시:  
  버리는 청크 수 `drained_chunks` 와 `drained_bytes` 를 **info** 로 로깅.  
  → flush 로 인해 얼마나 버려졌는지로 **잘림 원인** 추적 가능.

---

## 4. 점검 방법

- **인사말 잘림**
  - 통화 후 `tts_flush_skipped_greeting_phase2` 가 찍혀 있으면, Phase2 전환 시 flush 가 스킵된 것.
  - `rtp_tts_queue_flushed` 의 `drained_chunks` / `drained_bytes` 가 **인사말 구간에서** 크게 나오면, 그때는 다른 응답 전환 시 flush 로 잘린 것일 수 있음.
- **Phase2 텍스트**
  - `greeting_phase2_sent` 의 `text_len`, `text_full` 과  
    `tts_text_input` 의 `text_len`, `text_full` 이 **같고**,  
    실제 Phase2 문장 전체와 일치하면, TTS 로는 **전체 텍스트**가 전달된 것.

이 문서는 인사말 잘림 원인(Phase1→Phase2 시 flush)과, Phase2 텍스트가 잘린 것처럼 보이는 이유(로그 미리보기), 그리고 그에 대한 수정·로그 강화 내용을 정리한 것이다.
