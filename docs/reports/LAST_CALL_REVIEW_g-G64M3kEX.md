# 마지막 통화 점검 (g-G64M3kEX)

- **통화 시각**: 2026-02-21 02:20:32 ~ 02:21:36 (AI 응대)
- **로그 기준**: `logs/app.log` 마지막 AI 통화 구간

---

## 1. 문제점 요약

### 1.1 TTS Phase1 잘림 (실제로 5~6글자만 재생됨)

- **현상**: Phase1 인사말 전체("안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?")가 아닌 **처음 5~6글자 정도만 재생**되고 잘림.
- **로그 상**: `tts_duration_known` 에서 Phase1 구간이 7.055초로 누적되어 있으나, 이는 파이프라인 내부 누적값이고 **실제 RTP로 나간 오디오 양과 불일치**할 수 있음. (다음 응답의 오디오가 같은 구간에 섞여 누적되었을 가능성도 있음.)
- **가능 원인** (추가 조사 필요):
  - **Upstream EndFrame 전달 시점**: RAGLLM이 Phase1으로 StartFrame + TextFrame + **EndFrame** 을 한꺼번에 보내면, Google TTS가 EndFrame을 받고 스트림을 일찍 닫아 **일부만 합성**하고 끊었을 수 있음.
  - **TTS 스트림 조기 종료**: TTS가 첫 청크만 내보내고 다음 청크 전에 스트림이 닫힌 경우.
  - **RTP 전송 중단**: SIPPBXOutput에서 Phase1 오디오 프레임을 일부만 전송한 뒤 다른 프레임(예: Phase2 StartFrame)으로 전환이 되었을 수 있음.
- **조치** (반영됨):
  - RTP 출력 단(SIPPBXOutput)에서 **응답(Phase) 단위**로 전송 바이트를 누적하고, **LLMFullResponseEndFrame 수신 시** `tts_rtp_sent_for_response` 로그 출력 (`bytes_sent`, `duration_sec`, `ts_iso`).  
  - 다음 통화부터 Phase1 직후 이 로그가 **짧은 duration_sec / 작은 bytes_sent**로 나오면, Phase1이 RTP까지 짧게만 나간 것(실제 잘림)으로 판단 가능.

### 1.2 TTS Phase2 지연 (인사말 두 번째 문장이 18초 뒤에 재생)

- **현상**: Phase1 "안녕하세요. 기상청 AI 상담원입니다..." 전송 후, Phase2 "저는 날씨 예보 조회..." 가 **약 18.88초 뒤**에 전송됨.
- **로그**: `greeting_phase_gap_tts_complete_timeout`, `fallback_gap_sec=7.35`, `wait_timeout_sec=11.5`
- **원인**: RAGLLMProcessor가 Phase1 TTS 재생 완료를 알리는 **TTSCompleteNotifier의 event**를 기다리는데, **event가 11.5초 안에 해제되지 않아** 타임아웃 후 fallback 대기(7.35초)로 Phase2 전송.
- **추가**: 동일 구간에서 `tts_duration_known`(7.055초), `tts_complete_notifier_signalled` 는 **로그에 없음**.  
  → Notifier가 EndFrame을 받아 event.set() 한 시점이 로그에 없었을 수 있음(또는 upstream EndFrame이 너무 일찍 와서 duration=0으로 처리된 뒤, 실제 오디오 완료와 순서가 꼬였을 수 있음).
- **조치**: 
  - TTS 로그에 `ts_iso`(읽기 쉬운 시각), `call_id` 추가.
  - `tts_complete_notifier_signalled` 로그에 `note="… event.set() (Phase2 대기 해제)"` 로 명시.
  - `greeting_phase_waiting_tts_complete` 로그 추가(대기 시작 시점 확인용).
  - 다음 통화에서 `tts_complete_notifier_signalled` vs `greeting_phase_gap_tts_complete_timeout` 순서로 원인 추적 가능.

### 1.3 LLM 응답 잘림 ("네, 오늘 날씨 예보를" 12자)

- **현상**: 사용자 "오늘의 날씨가 궁금합니다." → 캐시 히트 후 응답이 **"네, 오늘 날씨 예보를"** 12자에서 끊김.
- **로그**: `llm_exchange_full`, `response_full="네, 오늘 날씨 예보를"`, `response_len=12`
- **원인**: (기존 분석과 동일) Semantic cache 히트 시 저장된 짧은 응답이 반환되었거나, LLM이 토큰/스트리밍 조건으로 12자에서 종료된 경우.
- **조치**: 캐시 저장/조회 시 응답 길이·완결성 검사, 또는 프롬프트/토큰 설정 검토 (별도 태스크).

### 1.4 409 Stream timed out (통화 종료 후)

- **현상**: Pipecat 로그에 `409 Stream timed out after receiving no more client requests` (Google STT/TTS 스트림).
- **판단**: 통화 BYE 수신 후 스트림이 닫히면서 나오는 **정상적인 타임아웃**으로 보는 것이 타당. 치명적 오류 아님.

### 1.5 SileroVAD(stop=0.2s) 로그

- **현상**: `pipecat_pipeline_built` 에 `SileroVAD(stop=0.2s)` 로 찍힘.
- **판단**: 해당 통화는 **config `silero_vad.stop_secs` 적용 전** 빌드된 파이프라인. 이후 배포에서는 `stop_secs: 0.7`(및 config) 적용 시 `SileroVAD(stop=0.7s)` 로 찍힐 것.

---

## 2. 로그 가독성 변경 (ts → ts_iso)

- **변경**: TTS 관련 로그의 `"ts": 1771608044.779` 형태를 **ISO 시각**으로 통일.
- **필드명**: `ts_iso` (예: `2026-02-21T02:20:44.779`).
- **적용 위치**:
  - `tts_duration_known`
  - `tts_complete_notifier_signalled`
  - `tts_first_audio_received`
  - `tts_first_chunk_sent_to_engine`
  - `tts_first_audio_sent_to_rtp`

---

## 3. TTS 디버깅용 로그 보강

- **call_id**: TTSCompleteNotifier 로그에 `call_id` 추가 (sync_context에서 `_call_id` 사용).
- **Notifier**: `tts_complete_notifier_signalled` 에 `note="TTS 해당 응답 출력 완료 → event.set() (Phase2 대기 해제)"` 추가.
- **인사 대기**: RAGLLMProcessor에서 Phase1 전송 후 event 대기 **시작** 시 `greeting_phase_waiting_tts_complete` (wait_timeout_sec, estimated_phase1_sec) 로그 추가.

이제 로그에서 **대기 시작 → Notifier event.set() 시각** 순서로 Phase2 지연 원인 추적 가능.
