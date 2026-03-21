# 2·3차 호 AI 묵음 원인 분석 (app.log)

첫 번째 호는 정상 AI 응대, 두 번째·세 번째 호는 AI 응대 없이 묵음이 난 현상에 대한 로그 점검 결과입니다.

---

## 1. 요약

| 호 | call_id | INVITE | AI 터치오버 | 통화 연결 | BYE | TTS→RTP 전송 | 결과 |
|----|---------|--------|-------------|-----------|-----|--------------|------|
| 1차 | QOT6HiI1zP | 10:14:36 | 10:14:46 | 10:14:46.853 | 10:15:16 | **817 패킷** (인사말 재생됨) | ✅ 정상 |
| 2차 | akZa~pnHsf | 10:45:04 | 10:45:14 | 10:45:14.941 | 10:45:34 | **0 패킷** | ❌ 묵음 |
| 3차 | rkoAdwR~Hr | 10:45:37 | 10:45:47 | 10:45:47.798 | 10:46:18 | **0 패킷** | ❌ 묵음 |

**결론**: 2·3차 호에서는 TTS 오디오가 **한 번도 RTP로 전송되지 않음** (rtp_tts_packets_sent: 0). Phase1 인사말 텍스트는 생성·전송되었지만, TTS→오디오→Output→RTP 구간에서 끊겼습니다.

---

## 2. 로그로 확인된 사실

### 2.1 1차 호 (정상)

- `tts_first_audio_received`, `tts_first_audio_sent_to_rtp`, `notifier_endframe_processed`, `output_endframe_processed` 모두 **QOT6HiI1zP** 기준으로 기록됨.
- `rtp_tts_packets_sent`: 817, `callee_frames`: 817 → AI 음성이 RTP로 나감.

### 2.2 2차 호 (묵음)

- **인사말 Phase1 텍스트는 생성·전송됨**  
  - 10:45:15.096 `rag_llm_greeting_phase1` "안녕하세요. 기상청 AI 상담원입니다. 어떤 도움이 필요하신가요?"  
  - 10:45:15.098 `greeting_phase1_sent`, `greeting_phase_waiting_tts_complete` (wait_timeout_sec: 28.1)
- **TTS 오디오는 한 번도 로그에 없음**  
  - `tts_first_audio_received` (call_id=akZa~pnHsf) 없음  
  - `tts_first_audio_sent_to_rtp` (call_id=akZa~pnHsf) 없음  
  - `notifier_endframe_processed` / `output_endframe_processed` (call_id=akZa~pnHsf) 없음
- **PCM 큐가 계속 비어 있음**  
  - 10:45:15.575 ~ 10:45:34.596 `rtp_tts_queue_empty_timeout` (call_id=akZa~pnHsf), **packets_sent: 0** 유지
- **Phase1 TTS 완료 대기 타임아웃**  
  - 10:45:50.534 `greeting_phase_gap_tts_complete_timeout` (wait_timeout_sec: 28.1)  
  - 10:45:50.536 `greeting_phase2_sent`, `initial_greeting_sent` (**call_id=akZa~pnHsf**)  
  - 이 시점에는 이미 10:45:34에 **BYE 수신** 후 정리 중 → 사용자는 약 20초 동안 묵음만 들음
- **녹음/통계**  
  - `callee_frames`: **0**, `rtp_tts_packets_sent`: **0**  
  - "Empty buffer, skipping WAV save" (callee.wav 없음), mixed는 caller만 사용

### 2.3 3차 호 (묵음)

- **Phase1 텍스트는 생성·전송됨**  
  - 10:45:47.769 `rag_llm_greeting_phase1` "안녕하세요. 기상청 AI 통화 비서입니다. 무엇을 도와드릴까요?"  
  - 10:45:47.773 `greeting_phase1_sent`, `greeting_phase_waiting_tts_complete` (wait_timeout_sec: 27.7)
- **TTS 오디오 없음**  
  - `tts_first_audio_received` / `tts_first_audio_sent_to_rtp` (call_id=rkoAdwR~Hr) 없음  
  - `notifier_endframe_processed` / `output_endframe_processed` (rkoAdwR~Hr) 없음
- **PCM 큐 비어 있음**  
  - `rtp_tts_queue_empty_timeout` (call_id=rkoAdwR~Hr), **packets_sent: 0**
- **Phase1 대기 타임아웃**  
  - 10:46:22.688 `greeting_phase_gap_tts_complete_timeout`  
  - 10:46:22.689 `greeting_phase2_sent`, `initial_greeting_sent` (call_id=rkoAdwR~Hr)  
  - BYE는 10:46:18에 수신됨 → 사용자는 약 31초 묵음 후 끊음
- **통화 종료 시**  
  - `rtp_tts_packets_sent`: **0**, `callee_frames`: **0**

### 2.4 파이프라인 오류 로그

```
RAGLLMProcessor#2 Trying to process LLMFullResponseEndFrame#5 but StartFrame not received yet
```

- **의미**: 어떤 응답의 **EndFrame**을 처리하려 할 때, 해당 응답의 **StartFrame**을 아직 받지 않은 상태.
- **가능 원인**:  
  - 여러 통화/파이프라인이 동시에 돌 때, **프로세서 내부 상태가 통화별로 격리되지 않음** (공유 상태로 인해 다른 호의 EndFrame이 먼저 처리됨).  
  - 또는 **프레임 순서가 꼬여** EndFrame이 StartFrame보다 먼저 도착.

---

## 3. 원인 정리

1. **TTS 오디오가 2·3차 호 파이프라인으로 나오지 않음**  
   - Phase1 TextFrame → TTS 구간까지는 진입했지만, **TTS → 오디오 프레임 → Output → RTP** 구간에서 **한 번도 오디오가 생성/전달되지 않은 상태**로 보는 것이 타당함.
2. **가능한 구조적 원인**  
   - **TTS 서비스(싱글톤)가 동시/연속 호를 하나의 스트림으로만 처리**  
     - 두 번째·세 번째 파이프라인이 같은 TTS 인스턴스를 쓰면, 한 쪽만 오디오를 받거나 나머지는 블록/무시될 수 있음.  
   - **프로세서(예: RAGLLMProcessor, TTS 쪽)의 응답 상태가 통화별로 격리되지 않음**  
     - EndFrame/StartFrame 순서 오류 로그와 맞물려, 한 호의 EndFrame이 다른 호의 StartFrame 전에 처리되는 식으로 꼬일 수 있음.  
   - **파이프라인/태스크가 BYE 후에도 일부 계속 동작**  
     - 로그에 2·3차 호 **call_id**로 `rtp_tts_queue_empty_timeout`이 통화 정리 후에도 계속 찍힘 → RTP 발송 루프/타이머가 정리 시 취소되지 않았을 가능성 (별도 이슈).

---

## 4. 권장 조치

1. **TTS 사용 방식**  
   - Google TTS 싱글톤을 **통화당 세션/스트림**으로 분리할 수 있는지 확인.  
   - 불가능하면 **통화당 전용 TTS 인스턴스**를 쓰거나, **동시에 한 통화만 TTS를 사용**하도록 직렬화(큐) 후, 해당 통화의 파이프라인에만 오디오가 가도록 보장.

2. **프레임 순서/상태 격리**  
   - `LLMFullResponseEndFrame` / `StartFrame`을 다루는 프로세서(RAGLLMProcessor 등)에서 **call_id(또는 task_id)별로 상태를 완전히 분리**.  
   - 한 호의 EndFrame이 다른 호의 StartFrame과 섞이지 않도록, 프레임에 call_id(또는 response_id)를 붙여서 같은 호/같은 응답 단위로만 처리하도록 수정.

3. **통화 종료 시 정리**  
   - BYE/정리 시 해당 호의 **RTP 발송 루프·empty_timeout 타이머**를 즉시 취소해, `rtp_tts_queue_empty_timeout`이 정리된 call_id로 더 이상 발생하지 않도록 함.

4. **재현 및 검증**  
   - 1차 호 종료 후, 2차·3차 호를 연속으로 걸어 같은 현상이 나오는지 확인.  
   - 수정 후에는 2·3차 호에서도 `tts_first_audio_sent_to_rtp`, `notifier_endframe_processed`, `rtp_tts_packets_sent > 0`이 나오는지 로그로 확인.

---

## 5. 참고 코드 위치

- 인사말 Phase1/Phase2 대기: `sip-pbx/src/ai_voicebot/pipecat/processors/rag_processor.py` — `send_greeting()`, `event.wait()`, `greeting_phase_gap_tts_complete_timeout`
- Output·TTS 동기화: `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py` — `SIPPBXOutputTransport`, `tts_sync_context`
- 파이프라인·컨텍스트 생성: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` — `build_and_run()` 내 `tts_sync_context = {}`, `build_pipeline(..., tts_sync_context=tts_sync_context)`
- RTP 발송 루프/empty_timeout: `sip-pbx/src/media/rtp_relay.py` — `_pipecat_tts_sender_loop`, empty_timeout 로깅

---

**[토큰 정보: 컨텍스트에 미제공]**
