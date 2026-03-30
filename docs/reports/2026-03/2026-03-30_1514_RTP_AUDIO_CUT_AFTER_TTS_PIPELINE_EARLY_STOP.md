# RTP 오디오 절단 — 파이프라인 조기 종료 원인 분석 및 수정

- **작성일**: 2026-03-30 15:14
- **상태**: 수정 완료
- **관련 콜**: `T4lqULMfOi` (14:59:29 "재난 방송" 질의)
- **증상**: TTS 응답 "재난 방송 관련 문의는..." 이후 RTP가 뭉개지다가 아예 안 들림

---

## 1. 현상 타임라인

| 시각 | 이벤트 | 비고 |
|---|---|---|
| 14:59:29.939 | LangGraph 응답 완료 (7.829s) | intent=nlu_fallback, confidence=0.187 |
| 14:59:29.942 | RAG → TextFrame 2개 전송 | 문장1: 52자, 문장2: 20자 |
| 14:59:31.193 | TTS #18 완료 (1248ms) | 문장1: 239,372B = **7.48초** |
| 14:59:31.201 | PCM 큐잉 시작 | chunk_seq 148~162, 일괄 15프레임 |
| 14:59:31.776 | TTS #19 완료 (582ms) | 문장2: 79,372B = **2.48초** |
| 14:59:31.776 | **EndFrame 전파** | notifier_endframe_processed |
| 14:59:34.318 | RTP health OK | rtp_tts_packets_sent=14880, pcm_buffer=0→325 (드레인 중) |
| **14:59:35.059** | **pipecat_input_transport_stopped** | ← 파이프라인 종료! |
| 14:59:35.164 | rtp_absolute_timing_summary | session=14,922 packets (298.44초) |
| **14:59:39.180** | **pipecat_mode_stopped** | stop_pipecat_mode() 완료 |
| 15:00:04.722 | BYE 수신 | 통화 종료 |

## 2. 근본 원인

### TTS 오디오 전체가 RTP로 전송되기 전에 파이프라인이 종료됨

**흐름**:
1. TTS 오디오 ~10초 분량(7.48초 + 2.48초)이 PCM 큐에 **일괄** 들어감 (14:59:31)
2. RTP sender thread는 20ms 간격으로 소비 → **완전 소진까지 ~10초 필요** (→ ~14:59:41)
3. 그런데 `DebugGoogleTTSService`가 일괄 yield 완료 후 Pipecat 내부에서 `EndFrame` 전파
4. `EndFrame` → `SIPPBXInputTransport._running = False` → `get_caller_audio_stream()` 루프 종료
5. `PipelineRunner.run(task)` 정상 반환 → `finally` 블록 → `stop_pipecat_mode()`
6. `stop_pipecat_mode()`에서:
   - `self._pipecat_mode = False` ← **sender thread 메인 루프 조건 `while self._pipecat_mode`가 즉시 False**
   - `pcm_q.put_nowait(None)` ← sentinel 전송
   - sender thread에서 sentinel 읽기 시 **pcm_buffer에 남은 데이터 무시하고 즉시 `return`**

### 결과: PCM 큐에 남아있는 ~6초 분량의 오디오가 전송되지 않고 폐기

## 3. 수정 내용

### 3.1 sender thread 메인 루프 조건 변경

```
# 변경 전
while self._pipecat_mode and self._pipecat_pcm_queue is not None:

# 변경 후
while self._pipecat_pcm_queue is not None:
```
- `_pipecat_mode` 체크 제거 → sentinel(`None`)만이 유일한 종료 시그널
- `stop_pipecat_mode`에서 `_pipecat_mode = False` 설정과의 race condition 해소

### 3.2 sentinel 수신 시 잔여 버퍼 드레인

```
# 변경 전: sentinel 수신 → 즉시 return (pcm_buffer 폐기)

# 변경 후: sentinel 수신 → 큐 잔여 청크를 모두 pcm_buffer로 이동
#         → _session_ending = True → 메인 루프에서 pcm_buffer 소진 후 종료
```
- 20ms 페이싱을 유지하면서 정상적으로 전송

### 3.3 드레인 완료 시 종료

```
# pcm_buffer가 비고 _session_ending이면 → rtp_sender_session_end 로그 후 return
```

### 3.4 join timeout 확대

```
# 변경 전: th.join(timeout=6.0)
# 변경 후: th.join(timeout=20.0)
```
- 10초 이상의 TTS 오디오 드레인 시간 고려

## 4. 관련 파일

- `sip-pbx/src/media/rtp_relay.py`: sender thread 드레인 로직 수정

## 5. 부수 발견 — nlu_fallback 이슈 지속

이 콜에서도 `intent=nlu_fallback`, `confidence=0.187`로 HITL 트리거됨.
이전 수정(classify_intent fallback → question)이 이 콜 이전 시점이므로 아직 적용되지 않은 상태.
