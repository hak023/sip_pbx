# 추가한 진단 로그 목록 및 경로

**현재 테스트(engine: legacy)에서는 인사말이 Orchestrator 경로로 재생됩니다.**  
그래서 **Pipecat 쪽에만 넣은 로그는 찍히지 않고**, **Orchestrator 쪽 로그만** 보입니다.  
아래는 “어떤 로그를 우리가 추가했는지”, “어느 경로에서 나오는지” 정리한 문서입니다.

---

## 1. Orchestrator 경로 (Legacy — 인사말이 여기서 재생될 때 나오는 로그)

| 이벤트 | 의미 | 확인할 것 |
|--------|------|------------|
| **orchestrator_greeting_phase1_sent** | Phase1 인사말 텍스트 전송 직후 | text_len, text_chunk_0, text_chunk_1 |
| **orchestrator_greeting_phase2_sent** | Phase2 가이드 텍스트 전송 직후 | text_len, text_chunk_0, text_chunk_1, text_last_chunk |
| **orchestrator_speak_start** | TTS 스트리밍 시작 (speak() 진입) | text_len |
| **orchestrator_speak_chunk** | TTS 청크 누적 (10, 20, 30, 50… 번째) | chunk_index, bytes_so_far — **중간 끊김 시 여기서 멈춤** |
| **orchestrator_speak_done** | TTS 스트리밍 완료 | total_chunks, total_bytes, text_len — TTS "audio_bytes"와 비교 |

**grep 예시 (Orchestrator 로그만):**
```bash
grep -E "orchestrator_greeting_phase|orchestrator_speak_" app.log
```

---

## 2. Pipecat 경로 (파이프라인으로 인사말이 나갈 때만 나오는 로그)

아래는 **RAG send_greeting()** 과 **Output transport** 를 타는 경우에만 찍힙니다.  
**Legacy로 인사말을 재생하면 이 경로를 안 타서, 아래 로그는 안 나옵니다.**

| 이벤트 | 의미 |
|--------|------|
| **greeting_phase1_sent** | RAG Phase1 전송 (text_len, text_chunk_0/1) |
| **greeting_phase2_sent** | RAG Phase2 전송 (text_len, text_chunk_*, text_last_chunk) |
| **rag_greeting_blocking_start** / **rag_greeting_blocking_end** | RAG가 event.wait() 하는 구간 |
| **rag_greeting_gap_sleep_start** / **rag_greeting_gap_sleep_done** | Phase1→Phase2 gap sleep |
| **tts_text_input** | Output이 TTS로 넘기는 텍스트 (text_len, text_chunk_*, text_suffix_60) |
| **tts_flush_skipped_greeting_phase2** | Phase2 전환 시 PCM flush 스킵 |
| **output_endframe_processed** | 응답 종료 시 response_bytes, **response_audio_frame_count** |
| **tts_response_audio_chunk** | 응답 내 오디오 청크 10/20/30/50… 번째 (frame_index, response_bytes_so_far) |
| **rtp_tts_queue_flushed** | PCM 큐 flush 시 drained_chunks, drained_bytes. **TTS가 실제로 안 나갔을 때**는 이 이벤트 직전·직후와 `tts_rtp_duration_mismatch`를 함께 확인 → [TTS_NOT_PLAYING_LOG_ANALYSIS.md](./TTS_NOT_PLAYING_LOG_ANALYSIS.md) 참고. |
| **stt_path_queue_high** | STT 입력 큐 ≥ 800 (백로그) |
| **stt_path_queue_yield_ok** | 큐에서 300개마다 yield |

---

## 3. STT 경로 (Pipecat 모드에서 오디오가 파이프라인으로 갈 때)

RTP → 큐 → Input → 파이프라인 → STT → RAG 로 갈 때만 아래 로그가 의미 있음.  
**Legacy에서는** RTP가 `ai_orchestrator.on_audio_packet()` 으로만 가고, 파이프라인 STT 경로는 **Pipecat 모드**일 때 사용됩니다.

| 이벤트 | 의미 |
|--------|------|
| stt_path_rtp_first | RTP → 큐 첫 투입 |
| stt_path_rtp_to_queue | 200패킷마다 |
| stt_path_queue_high | 큐 ≥ 800 |
| stt_path_queue_full_drop | 큐 풀 시 드롭 |
| stt_path_queue_first / stt_path_queue_to_consumer / stt_path_queue_yield_ok | 큐 소비 |
| stt_path_input_first / stt_path_input_to_pipeline | Input → 파이프라인 |
| stt_path_stt_first / stt_path_stt_to_rag | STT → RAG |

---

## 4. 정리

- **지금처럼 Legacy로 인사말이 나가면**  
  → **Orchestrator 쪽 로그만** 추가된 상태이므로,  
  **orchestrator_greeting_phase1_sent**, **orchestrator_greeting_phase2_sent**,  
  **orchestrator_speak_start**, **orchestrator_speak_chunk**, **orchestrator_speak_done** 만 보면 됨.
- **Pipecat으로 인사말이 나가면**  
  → **Pipecat 쪽 로그**(§2)가 찍히고, Orchestrator 인사말 로그는 안 나옴.
- **추가한 로그가 안 보일 때**  
  → **어느 경로(Orchestrator vs Pipecat)로 인사말/TTS가 나가는지** 먼저 확인하고, 해당 경로에 넣은 위 이벤트로 grep 하면 됨.
