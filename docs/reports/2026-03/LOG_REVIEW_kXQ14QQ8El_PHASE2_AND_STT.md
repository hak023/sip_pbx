# 로그 리뷰: 인사말 Phase2 깨짐 / STT 미동작 (통화 kXQ14QQ8El)

**대상**: app.log 4545–4828, 터미널 988–1011 (통화 kXQ14QQ8El, 2026-03-13 14:49:13–14:50:07)

---

## 1. 요약

| # | 현상 | 로그 기반 결론 |
|---|------|----------------|
| 1 | **인사말 2(Phase2)가 깨져 들림** | Phase2 첫 오디오 시점에 `rtp_timing_drift_reset`(누적 오차 4686ms) 발생. empty 직후 Phase1 꼬리 청크만 새 구간 처리되고 Phase2 첫 청크는 새 구간 미적용으로 1초 리셋 발생. |
| 2 | **STT가 동작하지 않은 것처럼 보임** | 해당 통화(kXQ14QQ8El) 전체 app.log에 `transcription_frame_received` / `stt_path_stt_first` / `rag_llm_user_input` 없음. 터미널에 VAD `TaskManager is still not initialized` 및 `__input_frame_task_handler` dangling 경고 있음. |

---

## 2. 인사말 Phase2 깨짐 원인

### 2.1 타임라인 (요약)

- **14:49:14.905** `rtp_tts_queue_empty_timeout` (empty_timeouts: 1, packets_sent: 0) → TTS 첫 청크 전 1초 대기
- **14:49:15.071–15.072** Phase1 시작: `tts_first_audio_sent_to_rtp`, `rtp_base_time_initialized`, `rtp_tts_sender_resumed_after_empty` (packets_sent_so_far: 0) → 정상
- **14:49:21.647** `rtp_tts_queue_empty_timeout` (empty_timeouts: 2, packets_sent: 279)
- **14:49:22.660** `rtp_tts_queue_empty_timeout` (empty_timeouts: 3, packets_sent: 279)
- **14:49:24.944** `rag_greeting_gap_sleep_done`, Phase2 전송
- **14:49:25.339** Phase2 첫 오디오: `tts_first_audio_sent_to_rtp`와 동시에 **`rtp_timing_drift_reset`** (accumulated_error_ms: 4686.69, packets_sent: 279)
- **14:49:25.339** 이 시점에 **`rtp_tts_sender_resumed_after_empty` 없음** → Phase2 첫 청크가 “새 구간”으로 처리되지 않음

### 2.2 원인 정리

- empty timeout 2·3 직후, **Phase2보다 먼저 Phase1 꼬리 청크**가 한 번 더 올 수 있음.
- 그 꼬리 청크에서 `last_was_empty_timeout=True`라 **그때만** 새 구간(base_time) 적용되고 `last_was_empty_timeout=False`로 바뀜.
- 그 다음에 오는 **Phase2 첫 청크**는 `last_was_empty_timeout=False`이므로 새 구간 분기에 안 들어가고, 기존 base_time + 279패킷 기준으로 목표 시간을 잡게 됨.
- 실제로는 8초 가까이 gap이 있어서 누적 오차가 약 4.7초가 되고, 1초 초과 리셋 조건에 걸려 **Phase2 첫 전송 직후** `rtp_timing_drift_reset`이 발생 → Phase2 구간이 깨져 들림.

### 2.3 적용한 수정 (rtp_relay.py)

- **조건 확장**: `last_was_empty_timeout`뿐 아니라 **`empty_timeout_count >= 2`이고 `packets_sent > 0`**일 때도 “새 구간”으로 인정.
- 이렇게 하면 Phase1 꼬리에서 한 번 새 구간을 써도, **Phase2 첫 청크**에서 `empty_timeout_count >= 2`와 `packets_sent > 0`이 만족되므로 다시 새 구간 base_time을 설정.
- Phase2 첫 패킷부터 새 기준으로 20ms 스케줄링되어, 1초 리셋으로 인한 끊김/깨짐이 줄어듦.
- 새 구간 적용 시 `empty_timeout_count >= 2 and packets_sent > 0`인 경우에만 `empty_timeout_count`를 0으로 소비해, 이후 청크가 계속 새 구간으로 잡히지 않도록 함.

---

## 3. STT 미동작 점검

### 3.1 kXQ14QQ8El 통화

- app.log 전체에서 `call_id: kXQ14QQ8El` 기준으로 검색:
  - **`transcription_frame_received`**: 없음  
  - **`stt_path_stt_first`**: 없음  
  - **`rag_llm_user_input`**: 없음  
- 즉, 이 통화에서는 **STT 최종 결과(TranscriptionFrame)가 RAG까지 도달한 이벤트가 한 건도 없음**.

### 3.2 가능한 원인

1. **사용자 발화 없음**  
   - 인사말만 듣고 말하지 않았을 수 있음.  
2. **VAD/파이프라인 이상**  
   - 터미널 로그:
     - `PipecatVADProcessor#0 TaskManager is still not initialized`
     - `VADWrapperProcessor#0 exception` → `ErrorFrame`  
     - `FrameProcessor.__process_frame_task_handler was never awaited`  
     - `Dangling tasks detected: ['VADWrapperProcessor#0::__input_frame_task_handler']`  
   - VAD 초기화/태스크 순서 문제로 입력 프레임 처리나 STT 상류가 막혀, STT가 결과를 내지 못했을 가능성.
3. **다른 통화와의 차이**  
   - 동일일 다른 통화(oSX4j4qEav)에서는 `transcription_frame_received` / `rag_llm_user_input`이 있음.  
   - 해당 통화에서는 `user_message_worker_error` (temporal 모듈 없음)로 **응답만** 실패한 상태.

### 3.3 적용한 수정 (VAD TaskManager)

- **원인**: 파이프라인은 체인에 있는 프로세서에만 `setup(FrameProcessorSetup)`을 호출함. `VADWrapperProcessor`만 체인에 있고 내부 `PipecatVADProcessor`(_vad)는 체인에 없어 `setup()`을 받지 못함. 그래서 `process_frame()` 시 내부 VAD가 `_task_manager`를 쓰려다 "TaskManager is still not initialized" 발생.
- **수정**: `vad_wrapper.py`의 `VADWrapperProcessor`에 `setup(setup)` 오버라이드 추가. `super().setup(setup)` 호출 후 `self._vad.setup(setup)`으로 동일 setup(clock, task_manager, observer)을 내부 VAD에 전달해, 프레임 처리 전에 TaskManager가 설정되도록 함.

### 3.4 권장 확인

- `vad_wrapper.py`의 cleanup 및 `pipeline_builder.py`의 processor cleanup으로 dangling task는 정리했으나, **초기화 완료 전에 오디오가 들어오는 경로**가 없는지 한 번 더 확인.
- 동일 시나리오로 재현 후, 해당 통화에서 `transcription_frame_received` / `stt_path_stt_first` 로그가 찍히는지 확인.

---

## 4. 참고

- Phase2 새 구간 로직: `sip-pbx/src/media/rtp_relay.py` `_pipecat_tts_sender_loop` 내 `new_segment = last_was_empty_timeout or (empty_timeout_count >= 2 and packets_sent > 0)`.
- VAD TaskManager 수정: `sip-pbx/src/ai_voicebot/pipecat/processors/vad_wrapper.py` `VADWrapperProcessor.setup()`에서 내부 VAD에 `FrameProcessorSetup` 전달.
- 유사 리뷰: `docs/reports/LOG_REVIEW_oSX4j4qEav_PHASE2_AND_STT.md` (Phase2 구간·temporal 오류 정리).
