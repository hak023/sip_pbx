# 로그 리뷰: 인사말 Phase2 깨짐 / STT 응답 실패 (통화 oSX4j4qEav)

**대상**: app.log 4021–4305, 터미널 992–1011 (통화 oSX4j4qEav, 2026-03-13 14:25:30–14:26:28)

---

## 1. 사용자 체감 문제 정리

| # | 현상 | 로그/코드 기반 분석 |
|---|------|---------------------|
| 1 | 인사말 1은 깔끔, **인사말 2는 음성이 깨져서 들림** | Phase1→Phase2 전환 구간에서 RTP 타이밍 리셋·큐 공백·간격 이탈이 겹침 |
| 2 | **STT가 전혀 이루어지지 않은 것처럼 보임** | STT는 정상 동작(TranscriptionFrame 도달). **사용자 발화 처리 시 `temporal` 모듈 없음**으로 인해 응답 경로만 실패 |

---

## 2. 인사말 Phase1 vs Phase2 비교

### 2.1 Phase1 (정상에 가까움)

- **14:25:31.198** `tts_first_audio_received` → TTS 첫 오디오 수신
- **14:25:31.557** `rtp_tts_queue_empty_timeout` (packets_sent: 0) → 첫 PCM 전에 1초 대기
- **14:25:31.902** `rtp_base_time_initialized` (pcm_queue_wait_ms: 345.76) → 첫 PCM 수신 후 base_time 설정
- **14:25:31.902** `tts_first_audio_sent_to_rtp`, `rtp_first_packet_sent` → RTP 전송 시작
- Phase1 구간: `rtp_packet_timing_absolute` 로 20ms 간격 전송, 일부 `rtp_interval_violation` 있으나 전반적으로 재생 가능
- **14:25:33.264** `notifier_endframe_processed` (duration_sec: 7.755), `phase1_rtp_summary` (duration_sec: 5.841, response_bytes: 186916)
- **tts_rtp_duration_mismatch** 24.7% → Notifier 7.76초 vs Output 5.84초 (Phase1도 일부 누락 가능성)

### 2.2 Phase1→Phase2 전환 (깨짐 가능 구간)

- **14:25:33.264** `rag_greeting_blocking_end` → Phase1 재생 완료 이벤트 해제
- **14:25:33.503** `rag_greeting_gap_sleep_start` (gap_sec: 8.76) → **8.76초 대기**
- 그 사이 **14:25:38.799** `rtp_tts_queue_empty_timeout` (empty_timeouts: 2, packets_sent: 295) → **큐가 비어 1초 타임아웃** (Phase1 종료 후 공백)
- **14:25:42.265** `greeting_phase2_sent` → Phase2 텍스트 전송
- **14:25:42.576** `tts_first_audio_sent_to_rtp` (Phase2 첫 오디오)
- **14:25:42.576** `rtp_timing_drift_reset` → **accumulated_error_ms: 4773.26**, base_time 리셋
- **14:25:42.664** `rtp_tts_queue_depleted` (packets_sent: 300) → Phase1 마지막까지 전송 직후 큐 소진

**차이 요약**

- Phase1: **첫 PCM 전에만** 큐 대기 → base_time 한 번 설정 후 일관된 20ms 스케줄링.
- Phase2: **긴 gap(8.76초) 동안 RTP 큐가 비어 있음** → empty timeout 발생 → Phase2 첫 청크 수신 시점에 **누적 오차가 이미 4.77초**라 base_time 리셋 발생.  
  리셋 직후 패킷은 “현재 시각 기준 0, 20, 40…”으로 다시 쏘므로, 구간 전환 직후 간격이 들쭉날쭉해지거나 끊겨 들릴 수 있음.

**권장**

- Phase1→Phase2 전환 시 **리셋을 하지 않거나**, Phase2 **첫 청크 전에만** base_time을 재설정하도록 구간을 명확히 나누기.
- gap_sec 동안 큐가 비는 것은 설계상 자연스러우나, **Phase2 첫 오디오가 올 때** “새 구간”으로만 base_time을 잡고, 리셋 조건(1초 이상 오차)을 **Phase2 첫 패킷 이전**에는 적용하지 않도록 로직 검토.

---

## 3. STT 및 사용자 발화 처리

### 3.1 STT는 동작함

- **14:26:09.223** `transcription_frame_received` (text: "안녕하세요 오늘의 날씨가 궁금합니다.", seq: 1)
- **14:26:09.223** `stt_path_stt_first`, `rag_llm_user_input` → STT 결과가 RAG/LLM 입력으로 전달됨

즉, **STT 파이프라인과 RAG 도달까지는 정상**이다.

### 3.2 응답 실패 원인: temporal 모듈 없음

- **14:26:09.224** `user_message_worker_error`: **"No module named 'src.ai_voicebot.pipecat.temporal'"**
- `rag_processor.py`의 `_process_with_agent()` 안에서  
  `from ..temporal.normalizer import TemporalExpressionNormalizer`  
  를 사용하는데, **`src/ai_voicebot/pipecat/temporal/` 패키지가 없음** → 사용자 발화 처리 진입 시 ImportError 발생.

그래서 “STT가 안 된 것처럼” 보이는 것은, **STT 결과가 RAG에는 들어왔지만 그 직후 처리에서 예외가 나서 응답(날씨 안내 등)이 나가지 않은 것**이다.

**권장**

- `temporal` 패키지를 추가하거나,
- **해당 import를 선택 처리**하여, 모듈이 없으면 시간 표현 정규화를 건너뛰고 원문으로만 처리하도록 변경.

---

## 4. 터미널/VAD 관련

- **14:25:30.639** VADWrapperProcessor#0 exception: **"PipecatVADProcessor#0 TaskManager is still not initialized"**  
  → 파이프라인 초기화 순서/타이밍 이슈. StartFrame 선행 전달 수정으로 일부 완화되었을 수 있으나, 여전히 에러 프레임이 한 번 나옴.
- **14:26:28.388** Dangling tasks: `VADWrapperProcessor#0::__input_frame_task_handler`  
  → BYE 정리 시 해당 태스크가 정리되지 않음. 파이프라인 종료 시 래퍼/프로세서 정리 순서 점검 필요.

---

## 5. 조치 체크리스트

| 항목 | 조치 |
|------|------|
| Phase2 깨짐 | Phase1→Phase2 전환 시 base_time 리셋 조건 완화 또는 Phase2 첫 청크에서만 재설정하도록 RTP 발송 루프 검토 |
| STT 후 응답 없음 | ✅ `temporal` 패키지 추가 완료: `src/ai_voicebot/pipecat/temporal/` (normalizer.py, 오늘/내일/어제 등 → 절대 날짜). requirements 추가 없음(표준 라이브러리만 사용). |
| VAD TaskManager | Pipecat/VAD 초기화 순서·문서 확인 (선택) |
| Dangling task | ✅ 파이프라인 종료 시 모든 프로세서에 `cleanup()` 호출. VADWrapperProcessor.cleanup()에서 Pipecat `__input_frame_task_handler` Task 취소 후 await. |

---

**작성일**: 2026-03-13  
**통화 ID**: oSX4j4qEav
