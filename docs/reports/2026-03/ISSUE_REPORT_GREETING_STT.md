# 이슈 리포트 — 인사말 잘림·Phase2 텍스트·STT 미동작 (재시작 테스트 기준)

테스트 일시·통화: 재시작 후 통화 (call_id 예: llMnWGDM37 등).  
아래 세 이슈에 대해 **추정 원인**과 **추적용 로그**를 정리함.

---

## 1. 인사말 1이 문장 중간에서 끊겨 들림

### 현상
- **들리는 소리**: "안녕하세요. 무엇을 도와드릴까요?" (중간 "AI 비서입니다" 구간이 빠짐)
- **로그**: Phase1 TTS는 "TTS synthesis done, audio_bytes: 122936", "TTS completed", "1.61s" 등으로 정상 완료처럼 보임.

### 추정 원인
- **TTS → Output → RTP 큐** 구간에서 **일부 오디오 프레임이 누락**되거나,
- **RTP 발송 루프**에서 **일부 청크가 버려지거나** (flush, 큐 풀 등),
- **단말/네트워크**에서 패킷 손실.

### 추적용 로그 (보강됨)
| 이벤트 | 확인할 것 |
|--------|-----------|
| **output_endframe_processed** | `response_bytes`, **response_audio_frame_count**. TTS "audio_bytes"(122936)와 비교. 작으면 파이프라인에서 누락. |
| **tts_response_audio_chunk** | `frame_index`, `response_bytes_so_far`. 10, 20, 30, 50… 구간별 누적. **중간에 이 로그가 멈추면** 그 구간에서 끊김. |
| **phase1_rtp_summary** | Phase1 `response_bytes`. 122936에 가까우면 Output까지는 전부 온 것. |
| **rtp_tts_queue_flushed** | `drained_chunks`, `drained_bytes`. 인사말 구간에 크게 나오면 flush로 잘린 것. |

**점검 순서**:  
1) `output_endframe_processed` 의 Phase1 `response_bytes` vs TTS `audio_bytes`  
2) `tts_response_audio_chunk` 가 10→20→30… 순으로 나오는지, 중간에 끊기는지  
3) 인사말 중에 `rtp_tts_queue_flushed` 가 찍혀서 큰 값이 버려졌는지  

---

## 2. 인사말 2 텍스트가 로그에서 잘려 보임 (text_preview)

### 현상
- 235라인 등에서 **text_preview**가 "저는 날씨 예보 … 기상 정보 안내" 정도에서 끝나 보임.
- 실제 전달 텍스트가 잘렸는지, **로그 출력만 잘린 것인지** 구분 필요.

### 추정 원인
- **로그 포맷/전송** 시 필드 길이 제한으로 **미리보기만 저장**되거나,
- 외부 TTS/프레임워크 로그가 **짧은 preview**만 찍는 경우.

### 추적용 로그 (보강됨)
| 이벤트 | 확인할 것 |
|--------|-----------|
| **greeting_phase1_sent** | **text_len**, **text_chunk_0**, **text_chunk_1** (60자 단위). 전체 문장은 청크 조합으로 확인. |
| **greeting_phase2_sent** | **text_len**, **text_chunk_count**, **text_chunk_0**, **text_chunk_1**, **text_chunk_2**, **text_last_chunk**. 로그가 잘려도 청크로 전체 확인. |
| **tts_text_input** | **text_len**, **text_chunk_0**, **text_chunk_1**, **text_chunk_2**, **text_suffix_60** (끝 60자). TTS로 넘긴 문자열이 실제로 잘렸는지 확인. |

**점검 순서**:  
1) `greeting_phase2_sent` 의 `text_len` 이 예상 문자 수(예: 91)와 같은지  
2) `text_chunk_*`, `text_last_chunk` 를 이어 붙였을 때 문장이 완결되는지  
3) `tts_text_input` 의 `text_len`·`text_suffix_60` 이 Phase2 문장 끝과 일치하는지  

---

## 3. 말해도 STT가 전혀 동작하지 않음

### 현상
- 통화 중 사용자가 말해도 **STT 결과(실시간 인식)** 가 없음.
- 구조상 STT는 항시 동작하도록 되어 있는데 동작하지 않음.

### 추정 원인
- **RTP → 큐**는 들어가지만 **Input이 큐를 소비하지 못함** (파이프라인 블로킹).
  - 인사말 구간에서 RAG가 **event.wait()** 또는 **gap sleep** 동안 **같은 파이프라인**을 점유하면,  
    Input의 **push_frame**이 오래 블로킹되고 → **get_caller_audio_stream**이 다음 데이터를 못 꺼냄 → **큐만 쌓임**.
- 큐가 가득 나면 **stt_path_queue_full_drop** 으로 caller PCM이 드롭 → STT에 오디오가 안 감.
- 또는 **큐 → Input** 소비는 되는데 **STT → RAG** 구간에서 **TranscriptionFrame**이 안 나오는 경우 (STT 설정/스트림 문제).

### 추적용 로그 (보강됨)
| 이벤트 | 확인할 것 |
|--------|-----------|
| **stt_path_rtp_first** | RTP → 큐 첫 투입. 있어야 경로 시작. |
| **stt_path_rtp_to_queue** | 200패킷마다. `packet_count` 증가, `queue_size`. |
| **stt_path_queue_high** | **queue_size ≥ 800** 시 1회. 큐 백로그 → Input 소비 지연(파이프라인 블로킹) 추정. |
| **stt_path_queue_full_drop** | 큐 풀 시. 나오면 caller PCM 드롭 → STT 입력 손실. |
| **stt_path_queue_first** | 큐 → Input 첫 소비. |
| **stt_path_queue_to_consumer** | 200마다. `packets_consumed` 증가. **멈추면** Input이 큐를 안 읽는 것. |
| **stt_path_queue_yield_ok** | 300마다. 큐에서 꺼내 yield. 소비 정상이면 계속 증가. |
| **stt_path_queue_timeout** | 5초간 큐 get 대기. `packets_consumed_so_far`. 0이면 한 번도 소비 안 됨. |
| **stt_path_input_first** | Input → 파이프라인 첫 프레임. |
| **stt_path_input_to_pipeline** | 200프레임마다. **AI call handling started 이후에도 증가하는지**가 핵심. 멈추면 파이프라인 블로킹. |
| **stt_path_stt_first** / **stt_path_stt_to_rag** | STT → RAG 도달. 한 번이라도 나와야 실시간 STT 동작한 것. |
| **rag_greeting_blocking_start** / **rag_greeting_blocking_end** | RAG가 event.wait() 하는 구간. 이때 Input 블로킹 가능. |
| **rag_greeting_gap_sleep_start** / **rag_greeting_gap_sleep_done** | Phase1→Phase2 gap sleep. 이 구간에도 Input 블로킹 가능. |

**점검 순서**:  
1) **stt_path_rtp_to_queue** 가 "AI call handling started" **이후**에도 계속 증가하는지  
2) **stt_path_queue_high** 또는 **stt_path_queue_full_drop** 이 나오는지 (큐 백로그/드롭)  
3) **stt_path_queue_to_consumer**·**stt_path_input_to_pipeline** 이 **인사말 이후에도** 증가하는지  
4) **rag_greeting_blocking_*** / **rag_greeting_gap_sleep_*** 시간대에 **stt_path_input_to_pipeline** 이 멈춰 있는지  
5) **stt_path_stt_to_rag** 가 한 번이라도 나오는지  

---

## 4. 요약 체크리스트 (재테스트 후 로그로 확인)

- [ ] **인사말 1 중간 끊김**: `output_endframe_processed`(Phase1) `response_bytes` ≈ 122936? `tts_response_audio_chunk` 가 10→20→30… 연속?  
- [ ] **Phase2 텍스트**: `greeting_phase2_sent` `text_len`·`text_chunk_*` 로 전체 문장 확인. `tts_text_input` `text_len`·`text_suffix_60` 일치?  
- [ ] **STT**: `stt_path_queue_high` / `stt_path_queue_full_drop` 유무. `stt_path_input_to_pipeline` 이 인사말 이후에도 증가? `stt_path_stt_to_rag` 1회 이상?  

이 문서는 재시작 테스트 이슈 3건(인사말 중간 끊김, Phase2 텍스트 로그 잘림, STT 미동작)에 대한 **추정 원인**과 **로그로 추적하는 방법**을 정리한 것이다.
