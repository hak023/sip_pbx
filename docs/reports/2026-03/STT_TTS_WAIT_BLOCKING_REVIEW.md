# STT/TTS 관련 Wait·Blocking 로직 점검

**점검일**: 2026-03-12  
**범위**: `src/ai_voicebot`, `src/media/rtp_relay.py` 내 STT/TTS 경로의 `wait`/`queue.get`/이벤트 대기

---

## 1. 요약

| 위치 | 유형 | 타임아웃 | 블로킹 영향 |
|------|------|----------|-------------|
| RAG `_user_message_queue.get()` | 큐 대기 | 없음 | 워커 태스크만 대기, process_frame 비블로킹 |
| RAG `_hitl_response_queue.get()` | 큐 대기 | 없음 | HITL 소비 태스크만 대기 |
| RAG `_greeting_phase2_done.wait()` | 이벤트 | 60초 | 워커 내부, 타임아웃 후 진행 |
| RAG Phase2 `event.wait()` (TTS 완료) | 이벤트 | 최대 60초(가변) | 인사말 send_greeting 코루틴만 대기 |
| RTP `_pipecat_pcm_queue.get()` | 큐 대기 | 1초 | TTS 발송 루프만 대기 |
| RTP `_pipecat_audio_queue.get()` | 큐 대기 | 5초 | STT 입력 스트림만 대기 |

**전체**: STT/TTS 경로에서 **파이프라인 process_frame을 직접 블로킹하는 무한 대기**는 없음.  
워커/루프 전용 태스크에서만 `queue.get()` 또는 `event.wait()` 사용하며, 필요한 곳은 타임아웃 있음.

---

## 2. 상세

### 2.1 RAGLLMProcessor (rag_processor.py)

#### 2.1.1 `_user_message_worker` — 사용자 발화 큐

- **코드**: `user_text = await self._user_message_queue.get()` (238행)
- **의미**: 사용자 발화(STT 최종)를 큐에서 한 건 꺼낼 때까지 대기.
- **타임아웃**: 없음 (무한 대기).
- **영향**: 이 대기는 **워커 태스크(`_user_message_worker`) 안에서만** 발생.  
  `process_frame()` 은 큐에 `put_nowait()` 만 하고 return 하므로 **파이프라인 스레드는 블로킹되지 않음**.
- **이후 대기**: `await asyncio.wait_for(self._greeting_phase2_done.wait(), timeout=60.0)`  
  Phase2 인사말 끝날 때까지 최대 60초 대기 후, 타임아웃 시 로그하고 LLM 처리 진행.

**결론**: 파이프라인 블로킹 아님. 워커가 “다음 사용자 발화” 올 때까지 기다리는 설계.

---

#### 2.1.2 `_consume()` (HITL 응답 소비)

- **코드**: `response_data = await proc._hitl_response_queue.get()` (162행)
- **의미**: HITL 응답(담당자 입력) 한 건을 큐에서 꺼낼 때까지 대기.
- **타임아웃**: 없음.
- **영향**: **HITL 소비 전용 태스크**만 대기. process_frame과 STT/TTS 스트림은 블로킹되지 않음.
- **정리**: 통화 종료 시 큐에 None 등 sentinel 넣어 워커 종료하는 방식이면 무한 대기 방지 가능 (현재 코드는 `if not response_data: continue` 로 빈 값은 스킵).

**결론**: 파이프라인/STT/TTS 블로킹 아님.

---

#### 2.1.3 `send_greeting()` — Phase2 전송 전 TTS 완료 대기

- **코드**: `await asyncio.wait_for(event.wait(), timeout=wait_timeout)` (863–866행)
- **의미**: Phase1 TTS가 끝났다는 이벤트(TTSCompleteNotifier가 EndFrame 수신 시 set)를 기다린 뒤 Phase2 전송.
- **타임아웃**: `wait_timeout` (최대 `_TTS_COMPLETE_WAIT_TIMEOUT_SEC` 60초, 공식 상한).
- **영향**: **인사말을 보내는 `send_greeting()` 코루틴만** 대기.  
  이 코루틴은 파이프라인 process_frame 체인이 아니라, “Pipeline 시작 후 0.5초 뒤” `send_greeting()` 태스크로 실행되므로 **STT/TTS 프레임 처리 루프를 블로킹하지 않음**.

**결론**: TTS 완료 동기화용 대기이며, 타임아웃 있음. STT/TTS 스트림 블로킹 아님.

---

### 2.2 RTP Relay (rtp_relay.py)

#### 2.2.1 `_pipecat_tts_sender_loop` — TTS PCM → RTP

- **코드**: `pcm_data = await asyncio.wait_for(self._pipecat_pcm_queue.get(), timeout=1.0)` (687–688행)
- **의미**: TTS에서 내려준 PCM 한 청크를 큐에서 꺼낼 때까지 대기.
- **타임아웃**: 1초. 타임아웃 시 루프 한 번 더 돌며, `None` 수신 시 루프 종료.
- **영향**: **TTS RTP 발송 전용 태스크**만 대기. STT/파이프라인 process_frame과는 별개.

**결론**: 블로킹 구간이지만 1초 타임아웃으로 제한됨.

---

#### 2.2.2 `get_caller_audio_stream()` — STT 입력 스트림

- **코드**: `pcm_data = await asyncio.wait_for(self._pipecat_audio_queue.get(), timeout=5.0)` (1053–1055행)
- **의미**: Caller RTP → PCM 변환된 데이터를 한 번 꺼낼 때까지 대기 (Pipecat Input Transport가 STT로 넘길 오디오 소스).
- **타임아웃**: 5초. 주석대로 “Google STT 스트림 타임아웃 방지”용.
- **영향**: **STT가 소비하는 오디오 스트림**만 대기. 타임아웃 시 `continue` 로 다음 get() 재시도.

**결론**: STT 입력 공급 루프만 블로킹, 5초 타임아웃 있음.

---

## 3. 무한 대기 가능 지점 및 권장 사항

1. **`_user_message_queue.get()`**  
   - **위치**: `_user_message_worker`  
   - **현재**: 타임아웃 없음. 워커는 “다음 사용자 발화”가 올 때까지 대기하는 것이 설계상 맞음.  
   - **권장**: 파이프라인/통화 종료 시 `_user_message_queue.put(None)` 등 sentinel로 워커를 종료하고 있으면 유지. 없으면 정리 시 sentinel 넣어 워커가 무한 대기하지 않도록 처리.

2. **`_hitl_response_queue.get()`**  
   - **위치**: HITL 소비 태스크  
   - **현재**: 타임아웃 없음. HITL 미사용 시 해당 태스크만 계속 대기.  
   - **권장**: 통화/파이프라인 종료 시 큐에 sentinel 넣어 소비 루프 종료하면 됨. (이미 그렇게 하고 있다면 변경 불필요.)

3. **Phase2 / TTS 완료 대기**  
   - **현재**: `asyncio.wait_for(event.wait(), timeout=wait_timeout)` 로 상한 있음.  
   - **권장**: 유지.

4. **RTP 쪽 큐**  
   - **현재**: 1초(TTS 발송), 5초(STT 입력) 타임아웃 있음.  
   - **권장**: 유지.

---

## 4. Pipecat 라이브러리 내부

- **`push_interruption_task_frame_and_wait()`**  
  - InterruptionTaskFrame 푸시 후 해당 이벤트가 set 될 때까지 대기.  
  - 우리 측 **BargeInSuppressProcessor** 에서 InterruptionTaskFrame 흡수 시 `frame.event.set()` 호출하므로, Pipecat 쪽에서 무한 대기하지 않음.

- **Google STT/TTS (Pipecat 서비스)**  
  - 내부에 스트리밍/요청별 대기가 있을 수 있으나, 일반적으로 비동기 I/O + 타임아웃 사용.  
  - 우리 코드에서 **동기 `time.sleep` / `run_until_complete`** 로 STT/TTS를 호출하는 구간은 없음.

---

## 5. 결론

- **STT/TTS 관련해 파이프라인 process_frame을 블로킹하는 무한 wait 로직은 없음.**
- 큐/이벤트 대기는 모두 **워커 태스크** 또는 **인사말 전송 코루틴**, **RTP 발송/입력 루프** 안에만 있고, 필요한 곳은 **타임아웃** 있음.

### 5.1 무한 대기 방지 현황

- **`_user_message_queue.get()`**  
  `reset()` 호출 시 `_user_message_worker_task.cancel()` 로 워커를 취소하므로, 통화 종료(또는 새 통화) 시 워커가 `get()`에서 무한 대기하지 않음.
- **`_hitl_response_queue.get()`**  
  HITL 응답은 외부 `get_hitl_service()`가 큐에 put. 통화 종료 시 해당 큐에 **sentinel(예: `None`)** 을 넣어 소비 루프를 종료하는 처리가 있으면 무한 대기 방지됨. (HITL 미사용 시에도 소비 태스크가 종료되도록 권장.)
