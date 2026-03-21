# 🔍 "Beautiful" 원인 분석

**날짜**: 2026-03-09 15:03:20
**Call ID**: `UztQDCBEBq`

---

## 문제: 사용자가 말하지 않은 "Beautiful" STT 인식

### 로그 증거
```
15:03:20.562 | rag_llm_user_input: text="Beautiful."
15:03:20.562 | timing_stt_final_to_rag: text_preview="Beautiful."
15:03:27.232 | llm_response: "감사합니다. 더 궁금하신 점 있으시면..."
```

---

## 원인 분석

### 1. 테스트 로직이 아님 ✅
- 코드 전체 검색 결과: **"Beautiful" 문자열이 존재하지 않음**
- 하드코딩된 테스트 데이터 없음
- **실제 Google STT API가 인식한 결과**

### 2. 진짜 원인: **음향 에코 / 배경 소음**

#### 가능성 1: TTS 에코 (가장 유력)
**타임라인 분석**:
```
15:02:50.xxx - TTS 인사말 재생 중 (28.775초 재생)
15:03:19.126 - TTS Phase 2 종료
15:03:19.148 - 새로운 TTS 시작
15:03:20.562 - STT 인식: "Beautiful" ⚠️
```

**문제**:
1. **TTS가 스피커로 재생**
2. **마이크가 TTS 소리를 다시 수신** (음향 에코)
3. **STT가 왜곡된 TTS를 "Beautiful"로 오인식**

**증거**:
- `input_audio_frame_to_pipeline`: frame_count 계속 증가 중 (오디오 계속 유입)
- TTS 재생 직후 STT 인식 발생
- 사용자가 실제로 말하지 않았음에도 인식됨

#### 가능성 2: 배경 소음 오인식
- 주변 환경 소음 (음악, TV, 다른 사람 대화 등)
- Google STT가 영어로 오인식

#### 가능성 3: RTP 패킷 오류
- RTP 패킷 유실로 인한 왜곡된 오디오
- 간격 이탈률 54% → 오디오 품질 저하
- 저품질 오디오를 STT가 오인식

---

## 근본 원인: **음향 에코 캔슬레이션 미적용**

### 현재 문제
```
TTS (Speaker) → [음향 경로] → Microphone → STT
         ↓
    RTP 전송됨
         ↓
    스피커 재생 → 마이크 재유입 → STT 오인식
```

### 정상 동작 (필요한 구조)
```
TTS → Speaker
         ↓
    AEC (Acoustic Echo Cancellation) 적용
         ↓
    Microphone (TTS 에코 제거) → STT
```

---

## 해결 방법

### 방법 1: AEC (Acoustic Echo Cancellation) 적용 🔴 권장

#### WebRTC AEC 사용
```python
# sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py

import webrtcvad
from scipy.signal import wiener  # 또는 noisereduce

class SIPPBXInputTransport(FrameProcessor):
    def __init__(self, rtp_worker, **kwargs):
        super().__init__(**kwargs)
        self._rtp_worker = rtp_worker
        self._running = False
        self._audio_task = None
        self._aec_enabled = True  # AEC 활성화
        self._tts_reference = []  # TTS 참조 신호 저장
    
    async def _read_audio_loop(self):
        frame_count = 0
        async for pcm_data in self._rtp_worker.get_caller_audio_stream():
            if not self._running:
                break
            
            if pcm_data:
                # AEC 적용: TTS 참조 신호 제거
                if self._aec_enabled and self._tts_reference:
                    cleaned_audio = self._apply_aec(pcm_data)
                else:
                    cleaned_audio = pcm_data
                
                frame = InputAudioRawFrame(
                    audio=cleaned_audio,
                    sample_rate=PIPECAT_SAMPLE_RATE,
                    num_channels=PIPECAT_NUM_CHANNELS,
                )
                await self.push_frame(frame)
    
    def _apply_aec(self, input_audio):
        """간단한 AEC (TTS 에코 제거)"""
        # 실제 구현은 WebRTC AEC 또는 Speex AEC 사용
        # 여기서는 개념만 표시
        return input_audio  # Placeholder
```

#### 상용 라이브러리 사용
```bash
pip install webrtcvad-wheels  # WebRTC VAD + AEC
pip install speexdsp-python   # Speex AEC
```

---

### 방법 2: VAD 강화 (임시 방편)

**현재**: VAD mode=2 (보통 민감도)

**개선**: **TTS 재생 중 STT 비활성화**

```python
# sip-pbx/src/ai_voicebot/orchestrator/ai_orchestrator.py

class AIOrchestrator:
    def __init__(self, ...):
        self._tts_playing = False  # TTS 재생 상태
    
    async def _on_stt_result(self, text: str, is_final: bool):
        # TTS 재생 중에는 STT 무시
        if self._tts_playing:
            logger.debug("stt_ignored_during_tts",
                        call_id=self.call_id,
                        text=text,
                        note="TTS 재생 중이라 STT 무시 (에코 방지)")
            return
        
        # 기존 STT 처리 로직
        ...
```

**TTS 재생 상태 추적**:
```python
# LLMFullResponseStartFrame 수신 시
self._tts_playing = True

# LLMFullResponseEndFrame 수신 시
self._tts_playing = False
```

---

### 방법 3: 하드웨어 개선 (근본 해결)

1. **헤드셋 사용**: 스피커와 마이크 분리
2. **지향성 마이크**: 에코 감소
3. **전화기 자체 AEC**: 일부 SIP 전화기는 AEC 내장

---

## 검증 방법

### 1. 로그로 확인
```python
# STT 결과 전에 TTS 재생 여부 로깅
logger.info("stt_result_with_context",
           text=text,
           tts_playing=self._tts_playing,
           last_tts_end_time=self._last_tts_end_time,
           elapsed_since_tts=time.time() - self._last_tts_end_time)
```

### 2. 테스트 시나리오
1. **조용한 환경**에서 테스트 (배경 소음 제거)
2. **헤드셋** 사용 (에코 제거)
3. **TTS 재생 직후** STT 발생하는지 확인

### 3. 로그 패턴 분석
```
TTS EndFrame (15:03:19.126)
↓ 1.4초 후
STT 인식 (15:03:20.562) → 에코 가능성 높음
```

---

## 우선순위

| 방법 | 효과 | 난이도 | 권장 |
|------|------|--------|------|
| **TTS 중 STT 차단** | 🟡 중간 | ✅ 낮음 | **즉시 적용** |
| **WebRTC AEC** | 🟢 높음 | 🟠 중간 | 권장 |
| **하드웨어 개선** | 🟢 높음 | 🔴 높음 | 장기 |

---

## 즉시 적용 가능한 임시 수정

**`ai_orchestrator.py`에 TTS 재생 중 STT 차단 추가**:

```python
# _on_tts_start 추가
async def _on_tts_start(self):
    self._tts_playing = True
    logger.debug("tts_playback_started", call_id=self.call_id)

# _on_tts_end 추가  
async def _on_tts_end(self):
    self._tts_playing = False
    self._last_tts_end_time = time.time()
    logger.debug("tts_playback_ended", call_id=self.call_id)

# _on_stt_result 수정
async def _on_stt_result(self, text: str, is_final: bool):
    # TTS 재생 중 또는 종료 직후 1초 이내 STT 무시
    if self._tts_playing:
        return
    
    if hasattr(self, '_last_tts_end_time'):
        elapsed = time.time() - self._last_tts_end_time
        if elapsed < 1.0:  # TTS 종료 후 1초간 STT 무시
            logger.debug("stt_ignored_after_tts",
                        text=text,
                        elapsed=elapsed)
            return
    
    # 기존 로직...
```

---

## 결론

**"Beautiful"은 테스트 로직이 아니라, TTS 에코를 Google STT가 오인식한 결과입니다.**

**즉시 해결**: TTS 재생 중 STT 차단  
**근본 해결**: AEC (Acoustic Echo Cancellation) 적용
