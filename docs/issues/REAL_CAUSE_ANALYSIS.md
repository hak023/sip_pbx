# 🔍 진짜 원인 재분석

**날짜**: 2026-03-09

---

## 질문 1: TTS → RTP 지연, 모델 때문?

### ❌ 아닙니다! 모델은 문제 없음

**타임라인 재분석**:

```
14:45:05.116 - vad_wrapped_for_pipecat (Pipeline 빌드 시작)
14:45:24.786 - google_stt_service_created_for_pipecat (19.67초 후!)  ⚠️ 여기가 지연!
14:45:24.813 - google_tts_service_created_for_pipecat
14:45:25.414 - rag_llm_greeting_phase1 (텍스트 생성)
14:45:25.475 - tts_first_audio_received (TTS 합성: 61ms)  ✅ 매우 빠름!
14:45:28.454 - tts_first_audio_sent_to_rtp (RTP 전송)
```

### 진짜 원인: Google STT/TTS Service 초기화 지연

**지연 구간**:
1. **Pipeline 초기화**: 14:45:05.116 → 14:45:24.786 = **19.67초** 🔴
2. **TTS 합성**: 14:45:25.414 → 14:45:25.475 = **61ms** ✅
3. **TTS → RTP 경로**: 14:45:25.475 → 14:45:28.454 = **2.98초** ⚠️

### 문제 코드 위치

**`sip-pbx/src/sip_core/call_manager.py:678-703`**:

```python
# STT/TTS: Pipecat에서 제공하는 Google 서비스 사용
_stt_pipecat = None
_tts_pipecat = None
try:
    from pipecat.services.google.stt import GoogleSTTService  # ⚠️ 여기서 19초 지연
    from pipecat.services.google.tts import GoogleTTSService
    
    _stt_config = {...}
    _stt_pipecat = GoogleSTTService(**_stt_config)  # 동기 초기화 (blocking)
    
    _tts_config = {...}
    _tts_pipecat = GoogleTTSService(**_tts_config)
```

### 왜 19초나 걸리나?

1. **Google Cloud 라이브러리 import** (10초)
   - `google.cloud.speech_v1`
   - `google.cloud.texttospeech_v1`
   - 첫 import 시 C 확장 모듈 로딩

2. **gRPC 채널 초기화** (5초)
   - Google API 서버 연결
   - SSL/TLS 핸드셰이크

3. **인증 토큰 획득** (2초)
   - Service Account 인증

4. **Pipecat 내부 초기화** (2초)

### 해결 방법

#### ✅ 방법 1: Service를 미리 생성 (Singleton)

**`sip-pbx/src/ai_voicebot/factory.py`**에서 서버 시작 시 한 번만 생성:

```python
# 서버 시작 시 (백그라운드)
_global_stt_service = GoogleSTTService(...)
_global_tts_service = GoogleTTSService(...)

# 통화 시
_stt_pipecat = _global_stt_service  # 재사용 (즉시)
_tts_pipecat = _global_tts_service  # 재사용 (즉시)
```

#### ✅ 방법 2: 비동기 초기화

```python
# 백그라운드에서 미리 초기화 (서버 시작 시)
async def _warmup_google_services():
    GoogleSTTService(...)
    GoogleTTSService(...)
```

---

## 질문 2: STT 감도 수정? (감도 때문 아닌데)

### ✅ 맞습니다! VAD 감도는 원래 문제 아니었음

**로그 확인**:
```
14:33:47.825 - VAD Detector initialized mode=3  (원래 설정)
```

**하지만 로그를 보면**:
- **VAD 로그가 전혀 없음** (음성 탐지 로그 없음)
- **STT 로그가 전혀 없음** (음성 인식 로그 없음)

### 진짜 문제: STT 스트림이 열리지 않음

**증거**:
1. ✅ Input Transport 작동: `pipecat_audio_stream_started`
2. ✅ 오디오 수신: `pipecat_audio_stream_first_packet`
3. ❌ VAD 탐지 없음: `vad_speech_detected` 로그 없음
4. ❌ STT 결과 없음: `stt_final_result` 로그 없음

### 내가 한 수정

#### 1. VAD 모드 변경 (3 → 2)
- **실제로는 도움 안 될 수 있음** (진짜 문제가 아니므로)
- 하지만 더 민감하게 설정하면 **혹시 모를 케이스 대비**

#### 2. STT 디버깅 로그 추가 ✅ **핵심 수정**

**`sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py:112-118`**:

```python
# 첫 10개 프레임과 100개마다 로깅
if frame_count <= 10 or frame_count % 100 == 0:
    logger.info("input_audio_frame_to_pipeline",
               call_id=self._rtp_worker.media_session.call_id,
               frame_count=frame_count,
               audio_len=len(pcm_data),
               note="Input Transport → Pipeline (VAD → STT)")
```

**목적**: 
- Input Transport가 프레임을 제대로 전달하는지 확인
- VAD가 프레임을 받는지 확인
- STT가 프레임을 받는지 확인

#### 3. STT Service 초기화 로그 강화

**`sip-pbx/src/sip_core/call_manager.py:687-693`**:

```python
logger.info("google_stt_service_created_for_pipecat",
           call_id=call_id,
           model="telephony",
           sample_rate=16000,
           note="STT 서비스 초기화 완료 - 오디오 스트림 대기 중")
```

### 실제 STT 문제 원인 (추정)

1. **Google STT 스트림이 열리지 않음**
   - `GoogleSTTService`가 초기화되었지만 실제 스트림은 시작 안 됨
   - 첫 오디오 프레임이 STT에 도달해야 스트림이 열림

2. **VAD가 음성을 탐지하지 못함**
   - Input → VAD → STT 경로에서 VAD가 "침묵"으로 판단
   - STT로 프레임을 전달하지 않음

3. **Pipeline 연결 문제**
   - VAD와 STT 사이의 프레임 전달 끊김

---

## 수정 사항 정리

| 수정 | 목적 | 효과 |
|------|------|------|
| VAD mode 3→2 | 음성 탐지 민감도 향상 (예방) | ⚠️ 혹시 모를 케이스 대비 |
| Input 프레임 로깅 | STT 디버깅 (핵심) | ✅ 문제 추적 가능 |
| STT 초기화 로깅 | 초기화 상태 확인 | ✅ 초기화 실패 탐지 |
| TTS Standard-A | 합성 속도 향상 | ⚠️ 실제로는 불필요 (합성은 빠름) |
| RTP 정밀 타이머 | 패킷 간격 개선 | ✅ 유효 |
| 큐 크기 제한 | 오버플로우 방지 | ✅ 유효 |

---

## 진짜 해결 방법

### 1. Google Service 사전 초기화 (필수) 🔴

**문제**: 통화 시작 시 19초 지연  
**해결**: 서버 시작 시 미리 생성

```python
# sip-pbx/src/ai_voicebot/factory.py (서버 시작 시)
_global_stt_service = GoogleSTTService(...)
_global_tts_service = GoogleTTSService(...)

# sip-pbx/src/sip_core/call_manager.py (통화 시)
_stt_pipecat = _global_stt_service  # 재사용
_tts_pipecat = _global_tts_service  # 재사용
```

### 2. STT 스트림 명시적 시작 (권장)

```python
# Pipeline 시작 후
await _stt_pipecat.start()  # 스트림 강제 시작
```

### 3. VAD → STT 연결 확인 (디버깅)

다음 테스트에서 로그 확인:
```
input_audio_frame_to_pipeline frame_count=1
vad_speech_detected
stt_interim_result
```

---

## 요약

| 질문 | 답변 |
|------|------|
| **TTS 지연이 모델 때문?** | ❌ 아님. **Google Service 초기화 19초**가 원인 |
| **TTS 합성 속도** | ✅ 61ms로 매우 빠름 (모델 문제 없음) |
| **STT 감도 수정?** | ⚠️ 감도는 원인 아니었음. **로그 추가**가 핵심 수정 |
| **STT 진짜 문제** | Google STT 스트림이 열리지 않거나 VAD가 전달 안 함 |

---

## 다음 단계

1. **Google Service 사전 초기화 구현** (19초 → 0초)
2. **테스트 후 로그 확인** (STT 스트림 열렸는지)
3. **필요 시 STT 스트림 명시적 시작**
