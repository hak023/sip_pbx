# TTS 비교 분석 결과

## 현재 Pipeline TTS vs 이전 Legacy TTS

### 현재 Pipeline TTS (Pipecat)

**위치**: `sip-pbx/src/sip_core/call_manager.py:698-703`

```python
from pipecat.services.google.tts import GoogleTTSService

_tts_config = {
    "sample_rate": 16000,
    "voice_name": "ko-KR-Chirp3-HD-Kore",
    "language_code": "ko-KR",
}
_tts_pipecat = GoogleTTSService(**_tts_config)
```

**특징**:
- **Google Cloud TTS (Chirp3-HD-Kore)**
- Sample rate: 16000Hz
- Pipecat 프레임워크 통합
- 스트리밍 TTS (실시간 오디오 생성)

---

### 이전 Legacy TTS (사용 안함)

**위치**: `sip-pbx/src/ai_voicebot/factory.py:109-114` (주석 처리됨)

```python
# from .ai_pipeline.tts_client import TTSClient
# tts = TTSClient(tts_config)
```

**파일 존재 여부**: ❌ `tts_client.py` 파일이 삭제됨

---

## 결론: 동일한 TTS 엔진 사용

### ✅ 같은 점
1. **TTS 엔진**: 둘 다 **Google Cloud Text-to-Speech** 사용
2. **Voice 모델**: 둘 다 `ko-KR-Chirp3-HD-Kore` (또는 유사 모델)
3. **Sample rate**: 둘 다 16000Hz

### ⚠️ 다른 점
1. **프레임워크**:
   - 현재: Pipecat의 `GoogleTTSService` (스트리밍 최적화)
   - 이전: 커스텀 `TTSClient` (파일 삭제됨, 세부 구현 미확인)

2. **오디오 처리**:
   - 현재: Pipecat Pipeline을 통한 실시간 스트리밍
   - 이전: 직접 구현한 오디오 처리 (추정)

---

## TTS 품질이 안 좋은 이유

### 1. RTP 전송 품질 문제 (가능성 높음)
- TTS 자체는 동일하지만 **RTP 전송 과정에서 유실**
- 이전 대화에서 확인한 문제들:
  - 큐 오버플로우
  - 20ms 간격 이탈
  - UDP sendto 실패

### 2. 음향 에코 (확인됨)
- 스피커에서 나온 TTS가 마이크로 재유입
- 왜곡된 오디오 재생

### 3. 네트워크 지터
- 전화기 지터 버퍼 문제
- RTP 패킷 순서 뒤바뀜

---

## 개선 방안

### 1. Voice 모델 변경 (즉시 적용 가능)

**현재**: `ko-KR-Chirp3-HD-Kore`

**대안**:
```python
# Standard 모델 (빠르지만 품질 낮음)
"voice_name": "ko-KR-Standard-A"  # 여성
"voice_name": "ko-KR-Standard-B"  # 남성
"voice_name": "ko-KR-Standard-C"  # 여성
"voice_name": "ko-KR-Standard-D"  # 남성

# Wavenet 모델 (높은 품질, 느림)
"voice_name": "ko-KR-Wavenet-A"  # 여성
"voice_name": "ko-KR-Wavenet-B"  # 남성
"voice_name": "ko-KR-Wavenet-C"  # 여성
"voice_name": "ko-KR-Wavenet-D"  # 남성

# Neural2 모델 (최신, 균형잡힌 품질/속도)
"voice_name": "ko-KR-Neural2-A"  # 여성
"voice_name": "ko-KR-Neural2-B"  # 남성
"voice_name": "ko-KR-Neural2-C"  # 여성
```

**권장**: `ko-KR-Neural2-A` 또는 `ko-KR-Wavenet-A`

### 2. 오디오 파라미터 조정

```python
_tts_config = {
    "sample_rate": 16000,  # 유지
    "voice_name": "ko-KR-Neural2-A",  # 변경
    "language_code": "ko-KR",
    
    # 추가 파라미터 (GoogleTTSService가 지원하는 경우)
    "speaking_rate": 1.0,  # 발화 속도 (0.25 ~ 4.0)
    "pitch": 0.0,          # 음높이 (-20.0 ~ 20.0)
    "volume_gain_db": 0.0, # 볼륨 (+16dB 권장)
}
```

### 3. RTP 전송 품질 개선 (이미 적용됨)
- 큐 오버플로우 모니터링
- 20ms 간격 준수
- UDP 전송 에러 로깅

### 4. 코덱 변경 검토
- 현재: G.711 (PCMU/PCMA)
- 대안: Opus (더 나은 품질, 낮은 대역폭)

---

## 즉시 테스트할 수 있는 변경

`sip-pbx/src/sip_core/call_manager.py:700` 수정:

```python
# Before
"voice_name": "ko-KR-Chirp3-HD-Kore",

# After (Neural2 - 권장)
"voice_name": "ko-KR-Neural2-A",

# 또는 (Wavenet - 최고 품질)
"voice_name": "ko-KR-Wavenet-A",
```

---

## 참고 자료

- Google Cloud TTS 음성 목록: https://cloud.google.com/text-to-speech/docs/voices
- Pipecat GoogleTTSService: https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/services/google.py
