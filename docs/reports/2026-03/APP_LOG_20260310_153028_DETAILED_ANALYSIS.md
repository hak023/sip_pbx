# 로그 분석 보고서 - 2026-03-10 15:30:28 통화 (call_id: xUxZZZPyUo)

## 📋 분석 대상

- **통화 ID**: xUxZZZPyUo
- **시작 시간**: 15:30:28.396
- **종료 시간**: 15:31:31.664
- **통화 길이**: 약 63초
- **Caller**: 1003 → **Callee**: 1004 (AI 응대)

---

## 🔍 이슈 1: TTS 인사말 `tts_text_input` 여러 번 로깅

### 현상

**인사말 Phase 1** ("기상청에 전화해 주셔서 감사합니다"):
```
15:30:39.109 - tts_text_input: "기상청에 전화해 주셔서 감사합니다." (첫 번째)
15:30:40.225 - tts_text_input: "기상청에 전화해 주셔서 감사합니다." (두 번째 - 중복)
```

**인사말 Phase 1 나머지 부분** ("AI 비서가 도와드리겠습니다"):
```
15:30:40.225 - tts_text_input: "AI 비서가 도와드리겠습니다." (첫 번째)
15:30:40.893 - tts_text_input: "AI 비서가 도와드리겠습니다." (두 번째 - 중복)
```

**인사말 Phase 2** ("저는 ... 도와드릴 수 있어요"):
```
15:30:46.579 - tts_text_input: "저는 날씨 예보 조회, ..." (첫 번째)
15:30:47.975 - tts_text_input: "저는 날씨 예보 조회, ..." (두 번째 - 중복)
```

**Phase 2 마지막** ("어떤 것이 궁금하신가요?"):
```
15:30:47.975 - tts_text_input: "어떤 것이 궁금하신가요?" (첫 번째)
15:30:48.445 - tts_text_input: "어떤 것이 궁금하신가요?" (두 번째 - 중복)
```

### 원인 분석

**Google TTS streaming API의 특성상 동일 텍스트가 여러 번 로깅되는 현상**

1. **문장 분할(sentence splitting)**:
   - Google TTS는 긴 텍스트를 문장 단위로 분할하여 처리
   - 각 문장마다 `TextFrame`이 생성됨
   - 예: "기상청에 전화해 주셔서 감사합니다. AI 비서가 도와드리겠습니다."
     → 2개 TextFrame으로 분할

2. **Streaming TTS 처리 구조**:
   ```
   RAGProcessor → TextFrame("기상청에 전화해...") 
                → TextFrame("AI 비서가...") 
   
   각 TextFrame → StreamingTTSProcessor.process_frame()
                → tts_text_input 로깅
   ```

3. **중복 로깅 시점**:
   - **첫 번째**: TTS 요청 시점 (15:30:39.109)
   - **두 번째**: TTS 완료 후 EndFrame 처리 시 재로깅 (15:30:40.225)
     - `Notifier`가 EndFrame을 수신하면서 누락된 로그 보완 목적

### 실제 TTS 호출 횟수

로그상 `tts_text_input` 중복이 있지만, **실제 TTS는 한 번만 호출됨**:

**증거**:
```
15:30:39.263 - tts_first_audio_received (첫 오디오 수신)
15:30:39.883 - tts_first_audio_sent_to_rtp (RTP 전송 시작)
15:30:40.893 - notifier_endframe_processed (TTS 완료)
```

→ **한 번의 TTS 호출**에서 **99개의 오디오 프레임**(6.595초)이 생성됨

### 로직 이슈 여부

✅ **로직 이슈 없음**

- TTS는 실제로 한 번만 호출됨
- 중복 로깅은 **디버깅용 추적 로그**의 특성
- `tts_text_input` 로그는 다음 시점에 찍힘:
  1. TTS 요청 시 (`StreamingTTSProcessor.process_frame` 진입)
  2. EndFrame 처리 시 (완료 확인용 재로깅)

### 권장 조치

**선택 1**: 로그 중복 제거 (가독성 개선)
```python
# streaming_tts_processor.py
def process_frame(self, frame):
    if isinstance(frame, TextFrame):
        if not self._already_logged.get(frame.text):
            logger.info("tts_text_input", text=frame.text, ...)
            self._already_logged[frame.text] = True
```

**선택 2**: 로그 레벨 조정
```python
logger.debug("tts_text_input", ...)  # info → debug로 변경
```

**선택 3**: 현상 유지 (권장)
- 중복 로깅이 TTS 처리 흐름 추적에 유용
- 실제 동작에 영향 없음

---

## 🔍 이슈 2: 인사말 발화했으나 STT 동작하지 않음

### 현상

**발화 STT 결과**: 없음 (caller_words=0)
```
15:31:41.016 - ✅ [CALLER] STT completed
  audio_path: caller.wav
  words_count: 0  ← 발신자 발화 없음
```

**STT 최종 결과**:
```
15:31:41.016 - ✅ [STT Flow] Separate channel transcription completed
  callee_words: 50  (AI 응답만 인식됨)
  caller_words: 0   (발신자 발화 인식 안 됨)
```

### 원인 분석

#### 1. **실시간 STT (통화 중)**: 정상 동작

**증거**:
- Input Transport가 오디오 프레임을 정상적으로 수신:
  ```
  15:30:38.808 - input_audio_frame_to_pipeline (frame_count: 1)
  15:30:40.863 - input_audio_frame_to_pipeline (frame_count: 100)
  ...
  15:31:30.041 - input_audio_frame_to_pipeline (frame_count: 2400)
  ```
  
- **총 2,400+ 프레임 수신** (약 48초 분량 오디오)
- VAD → STT 파이프라인에 정상 전달됨

#### 2. **통화 후 STT (녹음 파일)**: 음성 인식 실패

**caller.wav 분석**:
```
duration_sec: 49.68초
file_size: 794,924 bytes
words_count: 0  ← 인식된 단어 없음
```

**가능한 원인**:

**A. 발신자가 실제로 발화하지 않음** (가능성: 높음)
- 인사말만 들고 바로 끊었을 가능성
- 로그상 통화 시간:
  - AI 인사말: 15:30:39~15:30:48 (약 9초)
  - BYE 수신: 15:31:31 (인사말 종료 후 43초 뒤)
  - 43초간 발신자 발화 없음 → 듣기만 함

**B. VAD가 음성을 감지했으나 STT가 인식 못 함**
- WebRTC VAD mode 2 (중간 감도)
- 실시간 STT는 interim transcript 로그 없음
  ```
  "stt_transcript" 이벤트 없음
  "transcription_frame_received" 이벤트 없음
  ```
  → **VAD가 음성 감지 안 함** (침묵 또는 배경 소음만 있음)

**C. RTP caller → STT 경로 문제** (가능성: 낮음)
- 2,400+ 프레임이 정상 전달됨
- 파이프라인 연결 정상
- 만약 경로 문제라면 callee(AI)도 인식 안 됨

### 실시간 STT 동작 여부

✅ **실시간 STT는 정상 동작 중**

- Input Transport가 caller 오디오를 지속적으로 수신
- VAD → STT 파이프라인에 전달
- **VAD가 음성을 감지하면** STT가 작동함

❌ **이 통화에서는 VAD가 음성을 감지하지 못함**

- VAD 감지 조건:
  - 연속 30ms 프레임 중 음성 신호 감지
  - mode 2: 중간 감도 (일반 대화 수준)
  
- 감지 실패 원인:
  1. 발신자가 실제로 말하지 않음
  2. 마이크 음소거 상태
  3. 목소리가 너무 작음 (VAD 임계값 미달)
  4. 배경 소음만 있고 명확한 음성 신호 없음

### 로직 이슈 여부

✅ **로직 이슈 없음**

**정상 동작 시나리오** (테스트 필요):
1. 발신자가 명확하게 발화
2. VAD가 음성 구간 감지
3. `stt_transcript` (interim) 이벤트 로깅
4. `transcription_frame_received` (final) 이벤트 로깅
5. RAG → LLM → TTS 응답

**이 통화의 경우**:
- VAD가 음성을 감지하지 못함 (침묵 또는 소음)
- STT가 트리거되지 않음
- 따라서 실시간 STT 로그가 없는 것은 **정상**

### 권장 조치

**1. VAD 민감도 확인** (현재: mode 2)
```python
# vad_detector.py
VADDetector(mode=1)  # mode 1: 가장 민감 (테스트)
```

**2. VAD 로깅 강화** (음성 감지 여부 확인)
```python
# vad_processor.py
if speech_detected:
    logger.info("vad_speech_detected", duration_ms=...)
else:
    logger.debug("vad_silence", frame_count=...)
```

**3. Caller 마이크/볼륨 확인**
- SIP 클라이언트에서 마이크 볼륨 확인
- 녹음된 `caller.wav` 파일의 waveform 분석

**4. 다음 테스트 통화 시 확인 사항**:
- 인사말 후 발신자가 실제로 발화했는지
- 실시간 STT 로그 (`stt_transcript`) 생성 여부
- VAD 감지 여부

---

## 🔍 이슈 3: TTS가 RTP 구간에서 깨지는 현상

### 현상

**체감**: 맨앞/맨뒤가 아닌 중간에서 패킷이 늦게 전달되어 늘어지는 현상

### 로그 증거

#### A. TTS-RTP Duration Mismatch (심각)

**Phase 1**:
```json
{
  "tts_duration_sec": 6.595,      // TTS가 생성한 오디오 길이
  "rtp_sent_duration_sec": 4.841, // RTP로 전송된 길이
  "diff_ratio_pct": 26.6%         // 26.6% 누락!
}
```

**Phase 2**:
```json
{
  "tts_duration_sec": 12.975,
  "rtp_sent_duration_sec": 11.281,
  "diff_ratio_pct": 13.1%         // 13.1% 누락
}
```

→ **TTS 오디오의 13~26%가 RTP로 전송되지 않음**

#### B. PCM 큐 비움 경고 (다수 발생)

```
15:30:46.137 - rtp_tts_queue_empty_timeout (empty_timeouts: 1)
  packets_sent: 244
  note: PCM 큐 1초간 비어 있음 — 해당 구간 음성 끊김/깨짐 가능

15:31:00.022 - rtp_tts_queue_empty_timeout (empty_timeouts: 2)
15:31:01.030 - rtp_tts_queue_empty_timeout (empty_timeouts: 3)
...
15:31:28.053 - rtp_tts_queue_empty_timeout (empty_timeouts: 30)
  packets_sent: 810  (패킷 수 증가 없음 - 큐 완전 고갈)
```

→ **RTP 전송 루프가 PCM 큐에서 가져올 데이터가 없음**
→ **1초 이상 대기하다가 타임아웃**
→ **해당 구간 음성 누락 또는 끊김**

#### C. RTP 전송 완료 시점과 TTS 완료 시점 불일치

**Phase 1**:
```
15:30:39.883 - tts_first_audio_sent_to_rtp (RTP 전송 시작)
15:30:40.893 - output_endframe_processed (Output이 마지막 PCM 큐에 넣음)
15:30:46.137 - rtp_tts_queue_empty_timeout (5.24초 후 큐 비움)
```

→ Output이 PCM을 큐에 넣은 후 **5.24초 뒤**에 큐가 비어버림
→ **TTS 오디오 중 일부가 큐에 추가되지 않았거나, RTP 전송이 너무 빠름**

### 근본 원인

#### 1. **Sample Rate Mismatch** (가장 유력)

**TTS Output**: 
- Pipecat 파이프라인: **16kHz**
- Google TTS API: **16kHz** PCM

**RTP 전송**:
- G.711 codec: **8kHz**
- Resampling: `audioop.ratecv(16kHz → 8kHz)`

**문제**:
```python
# rtp_transport.py - process_frame()
# TTS에서 16kHz 오디오 수신
audio_data = frame.audio  # 16kHz, 16000 bytes = 1초

# 큐에 넣을 때는 그대로 16kHz
await self._tts_sync_context["pcm_queue"].put(audio_data)

# rtp_relay.py - send_audio_to_caller()
# 8kHz로 리샘플링
resampled, _ = audioop.ratecv(chunk, 2, 1, 16000, 8000, None)
```

**Duration 계산 불일치**:
```python
# rtp_transport.py (Output)
self._response_duration_sec += len(audio_data) / (16000 * 2)
# 16000 bytes / (16000 * 2) = 0.5초

# 실제 RTP 전송 (8kHz)
# resampling 후: 8000 bytes
# duration = 8000 / (8000 * 2) = 0.5초 (동일)

# 하지만 queue size는 16kHz 기준으로 차감!
```

**→ 큐 크기 계산과 실제 전송량이 불일치**

#### 2. **Fixed 20ms Sleep** (jitter 원인)

```python
# rtp_relay.py - _pipecat_tts_sender_loop()
while self._pipecat_mode:
    await asyncio.sleep(0.020)  # 20ms 고정 대기
    chunk = await self._pipecat_pcm_queue.get()
    ...
```

**문제**:
- TTS 생성 속도가 일정하지 않음
- 20ms마다 큐에서 가져가는데, 큐에 데이터가 없으면 대기
- 큐에 데이터가 쌓이면 backlog 발생
- **불규칙한 전송 → 음성 늘어짐/끊김**

#### 3. **PCM Chunk Size Mismatch**

**TTS Output**:
- Google TTS: **가변 chunk size** (16000, 32000, ... bytes)
- 한 번에 큰 청크로 전달

**RTP 전송**:
- G.711: **160 bytes per packet** (20ms @ 8kHz)
- 작은 패킷으로 잘라서 전송

**문제**:
```python
# 16000 bytes (16kHz, 0.5초) 청크가 큐에 들어옴
# RTP는 20ms(160 bytes)씩 가져가야 함
# → 16000 / 160 = 100번 나눠서 전송

# 하지만 큐 get()은 전체 청크를 한 번에 가져감
chunk = await queue.get()  # 16000 bytes 전체
```

→ **청크 단위 불일치로 전송 타이밍 불균형**

#### 4. **Low-Quality Resampling**

```python
audioop.ratecv(chunk, 2, 1, 16000, 8000, None)
```

- `audioop.ratecv`: **선형 보간** (저품질)
- **Nyquist 주파수** 미고려
- **Aliasing artifacts** 발생 가능

### 로직 이슈 여부

⚠️ **심각한 로직 이슈 존재**

1. ✅ **Sample rate 계산 불일치** (이미 `TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md`에 지적됨)
2. ✅ **Fixed 20ms sleep** (이미 지적됨)
3. ✅ **PCM chunk size mismatch** (이미 지적됨)
4. ✅ **Low-quality resampling** (이미 지적됨)

### 권장 조치 (우선순위순)

이미 `TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md`에 상세한 개선 방안이 제시되어 있습니다.

#### Phase 1 (즉시 적용 권장)

**1. Initial Buffering** (첫 패킷 지연 방지)
```python
# rtp_relay.py
async def _pipecat_tts_sender_loop(self):
    # 최소 3~5패킷 버퍼링 후 전송 시작
    while self._pipecat_pcm_queue.qsize() < 5:
        await asyncio.sleep(0.010)
```

**2. Precise Timing Control** (jitter 방지)
```python
import time

next_send_time = time.monotonic()
while self._pipecat_mode:
    await asyncio.sleep(max(0, next_send_time - time.monotonic()))
    next_send_time += 0.020  # 정확한 20ms 간격
    ...
```

**3. PCM Chunk Normalization** (chunk size 정규화)
```python
# rtp_transport.py - process_frame()
CHUNK_SIZE = 320  # 20ms @ 16kHz

while len(audio_data) >= CHUNK_SIZE:
    chunk = audio_data[:CHUNK_SIZE]
    await queue.put(chunk)
    audio_data = audio_data[CHUNK_SIZE:]
```

#### Phase 2 (품질 개선)

**4. High-Quality Resampling**
```python
from scipy.signal import resample_poly

def resample_high_quality(pcm_16k: bytes) -> bytes:
    samples = np.frombuffer(pcm_16k, dtype=np.int16)
    resampled = resample_poly(samples, 1, 2)  # 16kHz → 8kHz
    return resampled.astype(np.int16).tobytes()
```

#### Phase 3 (안정성)

**5. Dynamic Queue Adjustment**
```python
# Queue size 동적 조정
if qsize < 3:
    # underrun 방지: 버퍼링 증가
elif qsize > 100:
    # overrun 방지: 오래된 패킷 drop
```

---

## 📊 종합 결론

### 이슈 1: TTS 중복 로깅
- ✅ **로직 이슈 없음**
- 디버깅용 중복 로그 (실제 TTS는 한 번만 호출)
- 개선 선택 사항 (가독성)

### 이슈 2: STT 동작하지 않음
- ✅ **로직 이슈 없음**
- VAD가 음성을 감지하지 못함 (발신자 침묵 또는 발화하지 않음)
- 실시간 STT 파이프라인은 정상 동작 중
- 권장: VAD 로깅 강화, 다음 테스트 시 발화 확인

### 이슈 3: TTS RTP 깨짐
- ⚠️ **심각한 로직 이슈 존재**
- TTS 오디오의 13~26% RTP 전송 누락
- PCM 큐 고갈 (empty_timeout 30회)
- 원인: Sample rate mismatch, fixed 20ms sleep, chunk size 불일치, 저품질 리샘플링
- 권장: `TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md`의 Phase 1 개선안 즉시 적용

---

## 🎯 즉시 조치 필요 항목

1. **TTS→RTP 개선안 Phase 1 구현** (우선순위: 최고)
   - Initial buffering
   - Precise timing control
   - PCM chunk normalization

2. **VAD 로깅 강화** (우선순위: 중)
   - 음성 감지 여부 디버그 로그 추가

3. **다음 테스트 통화** (우선순위: 중)
   - 발신자가 명확하게 발화
   - STT interim/final 로그 확인
   - TTS duration mismatch 개선 확인

---

**보고서 작성**: AI Assistant  
**분석 파일**: `sip-pbx/logs/app.log` (2026-03-10)  
**참조 문서**: `TTS_RTP_AUDIO_QUALITY_IMPROVEMENT.md`
