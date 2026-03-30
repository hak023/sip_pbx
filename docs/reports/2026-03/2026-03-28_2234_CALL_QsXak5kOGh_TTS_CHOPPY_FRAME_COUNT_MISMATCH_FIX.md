# TTS 끊김 현상 분석 — `call_id: QsXak5kOGh` (Notifier vs Output 프레임 수 불일치)

**작성일:** 2026-03-28 22:34
**대상 통화:** `QsXak5kOGh`
**문제 구간:** "소나기가 오는 곳이 있겠습니다" (21:01:38 시작)
**상태:** 원인 파악 완료, 수정 적용, 재테스트 필요

---

## 문제 요약

사용자가 **"소나기가 오는 곳이 있겠습니다"** 구간에서 **TTS 말소리가 늘어지는** 현상을 보고했습니다.

로그 분석 결과:
- **Notifier**: 99개 프레임, 11.255초 수신
- **Output**: 20개 프레임, 9.68초 전송
- **프레임 손실**: 약 **79개** (약 80%)

---

## 타임라인 (call `QsXak5kOGh`, 두 번째 LLM 응답)

| 시각 | 이벤트 | 상세 |
|------|--------|------|
| 21:01:38.713 | `rag_textframe_pushed` | 76자 텍스트 전송 (단일 TextFrame) |
| 21:01:38.730 | `tts_first_audio_received` | TTS 첫 오디오 수신 (5ms) |
| 21:01:38.986 | `tts_first_audio_sent_to_rtp` | 첫 RTP 전송 (256ms) |
| 21:01:40.291 | `notifier_endframe_processed` | **99개** 프레임, **11.255초** |
| 21:01:40.293 | `output_endframe_processed` | **20개** 프레임, **9.68초** |
| 21:01:48.647 | PCM 큐 완전 고갈 | `pcm_queue_size: 0` |
| 21:01:56.667 | `rtp_schedule_soft_resync` | **8초 지연** (`ideal_late_ms: 7980.53`) |

---

## 근본 원인 분석

### 1. Notifier vs Output 프레임 카운트 불일치

**Notifier** (`tts_complete_notifier.py`):
```python
# 모든 오디오 프레임 카운트
audio = getattr(frame, "audio", None)
if audio and isinstance(audio, bytes):
    self._audio_frame_count += 1
```

**Output** (`rtp_transport.py`, 수정 전):
```python
# TTSAudioRawFrame 또는 OutputAudioRawFrame만 카운트
is_tts_audio = isinstance(frame, TTSAudioRawFrame)
is_output_audio = isinstance(frame, OutputAudioRawFrame)
if (is_tts_audio or is_output_audio) and audio_data:
    self._response_audio_frame_count += 1
```

**문제:**
- Google TTS가 **다른 타입의 오디오 프레임**도 생성할 수 있음
- Output은 특정 타입만 카운트 → **실제 전송된 프레임을 정확히 반영하지 못함**

### 2. 실제 프레임 손실 여부 확인

**`output_audio_frame_skipped` 경고 로그:** 없음
- 즉, 모든 프레임이 `TTSAudioRawFrame` 또는 `OutputAudioRawFrame`이었음
- 실제 프레임 손실은 **없었을 가능성**

**그렇다면 왜 Notifier는 172개, Output은 34개?**

**가설:**
1. Notifier가 **다른 타입의 프레임**도 카운트 (예: `AudioRawFrame` 등)
2. 또는 Notifier의 **리셋 타이밍이 잘못**되어 여러 응답을 누적
3. 또는 Google TTS가 **작은 내부 청크**를 생성하지만, Output에 도달하기 전에 **병합**됨

### 3. 바이트 수 분석

**첫 번째 응답 (greeting, 108자):**
- Notifier: 172프레임, 19.432초 → **평균 113ms/프레임**
- Output: 34프레임, 533,772바이트, 16.68초 → **평균 490ms/프레임**
- 바이트 차이: 19.432초 @ 16kHz = 약 622KB (예상) vs 533KB (실제)

**두 번째 응답 (경기 날씨, 76자):**
- Notifier: 99프레임, 11.255초 → **평균 114ms/프레임**
- Output: 20프레임, 309,772바이트, 9.68초 → **평균 484ms/프레임**

**패턴:**
- Notifier의 프레임은 **약 100ms** (매우 작은 청크)
- Output의 프레임은 **약 500ms** (큰 청크)

**결론: 프레임이 중간에서 병합**되고 있거나, **Notifier가 다른 것을 카운트**하고 있습니다!

---

## 해결 방안

### 수정 1: Output이 모든 오디오 프레임을 카운트하도록 변경

**파일:** `src/ai_voicebot/pipecat/rtp_transport.py`

**변경 전:**
```python
is_tts_audio = isinstance(frame, TTSAudioRawFrame)
is_output_audio = isinstance(frame, OutputAudioRawFrame)
if (is_tts_audio or is_output_audio) and audio_data and isinstance(audio_data, bytes):
    self._response_audio_frame_count += 1
```

**변경 후:**
```python
is_caller_audio = isinstance(frame, InputAudioRawFrame)
# ✅ Notifier와 동일 로직: audio 속성이 있는 모든 프레임 카운트
if not is_caller_audio and audio_data and isinstance(audio_data, bytes):
    self._response_audio_frame_count += 1
```

### 수정 2: 4단계 프레임 흐름 추적 로깅

**프레임 흐름:**
```
Google TTS → Notifier → rec_output → Output
```

각 단계에서 프레임 수를 로깅:

#### A. Google TTS (`debug_google_tts.py`)
```python
async def run_tts(self, text: str):
    frame_count = 0
    async for frame in super().run_tts(text):
        if audio:
            frame_count += 1
            # 처음 5개와 10개마다 상세 로깅
            if frame_count <= 5 or frame_count % 10 == 0:
                logger.debug("google_tts_frame_generated", ...)
        yield frame
    # API 호출당 총 프레임 수
    logger.info("google_tts_api_complete", frames_generated=frame_count, ...)
```

#### B. Notifier (`tts_complete_notifier.py`)
```python
# EndFrame 시: audio_frame_count 로깅 (기존)
# 추가: 처음 5개와 50개마다 프레임 상세
if self._audio_frame_count <= 5 or self._audio_frame_count % 50 == 0:
    logger.debug("notifier_audio_frame_detail",
                frame_type=type(frame).__name__,
                audio_len=len(audio),
                duration_ms=...)
```

#### C. rec_output (`recording_processor.py`)
```python
# 응답별 리셋 (LLMFullResponseStartFrame)
if isinstance(frame, LLMFullResponseStartFrame):
    self._audio_frame_count = 0

# 오디오 프레임마다 카운트
if is_audio:
    self._audio_frame_count += 1
    if self._audio_frame_count <= 5 or self._audio_frame_count % 10 == 0:
        logger.debug("rec_output_audio_frame", ...)

# EndFrame 시 총 프레임 수
if isinstance(frame, EndFrame):
    logger.info("rec_output_endframe", frames_collected=self._audio_frame_count, ...)
```

#### D. Output (`rtp_transport.py`)
```python
# 처음 5개와 10개마다 프레임 상세 (추가됨)
if fc <= 5 or fc % 10 == 0:
    logger.debug("output_audio_frame_detail",
                frame_type=type(frame).__name__,
                audio_len=len(audio_data),
                duration_ms=...)

# EndFrame 시: response_audio_frame_count 로깅 (기존)
```

### 수정 3: 불필요한 `else` 블록 제거

**파일:** `src/ai_voicebot/pipecat/rtp_transport.py`

**변경 전:**
```python
if (is_tts_audio or is_output_audio) and audio_data:
    # ... 처리 ...
else:
    if is_caller_audio:
        pass
    elif audio_data:
        logger.warning("output_audio_frame_skipped", ...)
```

**변경 후:**
```python
if not is_caller_audio and audio_data:
    # ... 처리 ...
elif is_caller_audio:
    pass  # 정상
```

---

## 디버깅 플로우

**TTS 끊김/뭉개짐 발생 시:**

1. **사용자가 정확한 구간을 알려줌** (예: "소나기가 오는 곳이 있겠습니다")
2. **CDR에서 해당 텍스트 검색:**
   ```bash
   grep "소나기가 오는 곳" logs/call_data_record_*.log
   ```
3. **타임스탬프 확인** (예: `21:01:38.713`)
4. **`app.log`에서 4단계 프레임 수 확인:**
   ```
   - google_tts_api_complete: frames_generated=?
   - notifier_endframe_processed: audio_frame_count=?
   - rec_output_endframe: frames_collected=?
   - output_endframe_processed: response_audio_frame_count=?
   ```
5. **프레임 손실 지점 특정:**
   - Google TTS → Notifier 사이 손실?
   - Notifier → rec_output 사이 손실?
   - rec_output → Output 사이 손실?

6. **상세 프레임 로그 확인** (DEBUG 레벨 활성화 시):
   - `google_tts_frame_generated`: 프레임 크기·타입
   - `notifier_audio_frame_detail`: 프레임 크기·타입
   - `rec_output_audio_frame`: 프레임 크기·타입
   - `output_audio_frame_detail`: 프레임 크기·타입

---

## 예상 효과

1. **Notifier와 Output의 프레임 카운트가 일치**할 것으로 예상
2. **4단계 프레임 추적으로 손실 지점 즉시 파악** 가능
3. **사용자가 뭉개지는 구간을 말하면 즉시 해당 구간의 로그를 찾아** 분석 가능
4. **프레임 타입·크기 분포 확인**으로 Google TTS 내부 동작 이해

---

## 예상 효과

1. **Notifier와 Output의 프레임 카운트가 일치**할 것으로 예상
2. **디버그 로그로 실제 프레임 타입 확인** 가능
3. **프레임 손실 여부를 정확히 판단** 가능

---

## 재테스트 계획

1. **서버 재시작** (수정 반영)
2. **새 테스트 통화** 실행
3. **로그 확인:**
   - `notifier_endframe_processed` vs `output_endframe_processed` 프레임 수 비교
   - `notifier_audio_frame_detail` vs `output_audio_frame_detail` 프레임 타입 비교
   - `output_audio_frame_skipped` 경고 발생 여부
4. **실제 청취 품질** 확인

---

## 추가 의심 사항

### Google TTS 내부 청크 생성

Google TTS API가 **내부적으로 작은 청크**를 생성하고, Pipecat이 이것을 **병합**해서 Output에 전달할 수 있습니다.

이 경우:
- Notifier는 **원본 작은 청크** 수신 (172개, 평균 113ms)
- 중간 프로세서가 **병합**
- Output은 **병합된 큰 청크** 수신 (34개, 평균 490ms)

**확인 방법:**
- `notifier_audio_frame_detail` 로그에서 프레임 길이 확인
- 작은 프레임(~2000바이트)과 큰 프레임(~16000바이트)이 섞여 있는지 확인

---

## 관련 파일

- `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py` (수정됨)
- `sip-pbx/src/ai_voicebot/pipecat/processors/tts_complete_notifier.py` (수정됨)
- `sip-pbx/logs/app.log` (분석 대상)
- `sip-pbx/logs/call_data_record_20260328.log` (통화 정보)

---

## 참고 로그

### Notifier EndFrame (라인 2190)
```json
{"timestamp": "2026-03-28T21:01:40.291", "level": "info", "call": "notifier_endframe_processed", "progress": "tts", "call_id": "QsXak5kOGh", "audio_frame_count": 99, "category": "tts", "duration_sec": 11.255, "note": "Notifier가 EndFrame 수신 시점 — 이 응답에서 받은 오디오 프레임 수·누적 재생 길이", "ts_iso": "2026-03-28T21:01:40.290"}
```

### Output EndFrame (라인 2194)
```json
{"timestamp": "2026-03-28T21:01:40.293", "level": "info", "call": "output_endframe_processed", "progress": "tts", "call_id": "QsXak5kOGh", "category": "tts", "note": "Output이 EndFrame 수신 — 이 응답에서 큐에 넣은 PCM 바이트·프레임 수. TTS audio_bytes와 비교해 중간 끊김 추적", "response_audio_frame_count": 20, "response_bytes": 309772, "ts_iso": "2026-03-28T21:01:40.292"}
```

### RTP Soft Resync (라인 2246)
```json
{"timestamp": "2026-03-28T21:01:56.667", "level": "info", "event": "rtp_schedule_soft_resync", "progress": "rtp_timing", "call_id": "QsXak5kOGh", "chunk_inner_idx": 0, "ideal_late_ms": 7980.53, "note": "스케줄 대폭 지연 — base_time 재앵커, 이후 20ms 간격 유지(버스트 완화)", "packets_sent_thread": 2651, "pcm_queue_size": 0, "soft_resync_count": 6}
```

**8초 지연**은 **TTS 응답 사이의 gap**으로, 단일 TTS 내의 끊김과는 무관합니다.

---

## 다음 단계

1. ✅ 코드 수정 완료
2. ⏳ 서버 재시작
3. ⏳ 새 통화 테스트
4. ⏳ 디버그 로그 분석 (`notifier_audio_frame_detail`, `output_audio_frame_detail`)
5. ⏳ 프레임 타입·크기 분포 확인
6. ⏳ 실제 끊김 현상 재현 여부 확인
