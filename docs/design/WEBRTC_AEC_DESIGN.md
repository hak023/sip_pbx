# WebRTC AEC (Acoustic Echo Cancellation) 설계

**목적**: TTS 재생 중에도 STT를 차단하지 않고, 스피커→마이크 에코를 제거하여 오인식("Beautiful" 등) 방지.

---

## 1. 왜 TTS 중 STT 차단이 안 되는가

- **바지인(Barge-in)**: 사용자가 AI 말하는 도중 말을 걸면 즉시 인식되어야 함.
- **자연스러운 대화**: TTS 구간을 무시하면 “말했는데 안 들었다”는 체감이 발생.
- 따라서 **에코만 제거**하고, 실제 사용자 음성은 STT로 들어가야 함.

---

## 2. 에코가 생기는 구조

```
[서버] TTS PCM → RTP → [전화기] 스피커 재생
                              ↓
                        (음향 경로: 방, 지연, 반사)
                              ↓
[전화기] 마이크 수집 → RTP → [서버] STT
```

- **Far-end**: TTS(스피커에서 나가는 소리) = 우리가 아는 “참조 신호”.
- **Near-end**: 마이크 입력 = 참조(에코) + 사용자 음성 + 잡음.
- AEC는 **참조 신호를 이용해 near-end에서 에코 성분을 빼서** 사용자 음성만 남기는 과정.

---

## 3. WebRTC AEC 개요

### 3.1 동작 원리 (AEC3)

- **적응형 필터**: 스피커→마이크 구간을 “필터”로 모델링.
- **에코 예측**: Far-end(참조) 신호로 “마이크에 이렇게 들릴 것”을 예측.
- **제거**: Near-end에서 예측 에코를 빼서 **에코 제거 신호** 생성.
- **적응**: NLMS 등으로 필터를 실시간 갱신 → 방 조건·볼륨 변화, 이중 통화(double-talk)에도 대응.

### 3.2 특징

- **실시간·저지연**: 10ms 단위 프레임 처리.
- **Double-talk**: 사용자가 말하는 동안에도 TTS 에코를 줄이도록 설계됨.
- **비선형 왜곡**: 스피커/앰프 비선형성도 일부 보정 (AEC3).

---

## 4. Python에서 사용 가능한 라이브러리

| 라이브러리 | 설명 | 설치 | 비고 |
|------------|------|------|------|
| **aec-audio-processing** | WebRTC 기반 AEC/NS/AGC | `pip install aec-audio-processing` | PyPI, 16kHz 지원 |
| **py-webrtcaec** | WebRTC AEC Python 바인딩 | GitHub 설치 | AEC 전용 |
| **python-webrtc-audio-processing** | WebRTC 오디오 처리 전체 | GitHub | AEC/NS/AGC 등 |

권장: **aec-audio-processing** (설치·API 단순, 실시간 스트림 처리).

### 4.1 aec-audio-processing 사용 예

```python
from aec_audio_processing import AudioProcessor

# 16kHz 모노, AEC+NS+AGC
ap = AudioProcessor(enable_aec=True, enable_ns=True, enable_agc=True)
ap.set_stream_format(16000, 1)

# 10ms 단위 (160 samples = 320 bytes at 16kHz)
near_end = ...   # 마이크 입력 (caller RTP → PCM)
far_end = ...    # TTS 참조 (우리가 스피커로 보낸 PCM)
cleaned = ap.process_stream(near_end, far_end)  # 에코 제거된 near-end
```

- **Far-end**: 우리가 TTS로 보내는 PCM (RTP로 나가기 직전 버퍼).
- **Near-end**: Caller RTP를 디코딩한 PCM.
- **출력**: 에코가 제거된 PCM → STT 파이프라인으로 전달.

---

## 5. SIP PBX 연동 구조

### 5.1 데이터 흐름

```
[Output Transport] TTS PCM
       │
       ├──► send_audio_to_caller() → RTP → 전화기
       │
       └──► AEC far-end 버퍼에 복사 (ring buffer, 예: 최근 200ms)

[Caller RTP] → rtp_to_pcm16k → near_end
       │
       ▼
   AEC.process_stream(near_end, far_end_from_buffer)
       │
       ▼
   cleaned_pcm → _pipecat_audio_queue → Input Transport → VAD → STT
```

- **Far-end 버퍼**: TTS PCM을 10ms(또는 20ms) 단위로 쌓음. AEC가 “참조”로 사용.
- **정렬**: RTP 지연·네트워크 지터를 고려해 near/far 타임스탬프 정렬이 필요할 수 있음. 첫 단계는 “최근 far-end”만 사용해도 됨.

### 5.2 배치 위치

| 위치 | 역할 |
|------|------|
| **RTPRelayWorker** | Caller RTP 수신 시 near_end 생성; TTS 전송 직전 far_end 버퍼에 쓰기. |
| **AEC 모듈** | Worker 내부 또는 `audio_utils` 근처. `process_stream(near, far)` 호출. |
| **Input Transport 직전** | `get_caller_audio_stream()`에서 yield하기 전에 AEC 적용. |

즉, **RTP → PCM 변환 직후, Pipecat 입력 큐에 넣기 전**에 AEC를 한 번 거치면 됨.

### 5.3 선택 사항

- **AEC 비활성화 플래그**: 설정으로 끄면 기존과 동일하게 near_end만 STT로 전달.
- **Far-end 버퍼 크기**: 200ms~500ms (예: 16kHz 기준 3200~8000 샘플). 너무 크면 지연·메모리 증가.
- **샘플 정렬**: 나중에 RTP 타임스탬프로 near/far 정렬하면 품질이 더 좋아질 수 있음.

---

## 6. 구현 단계 제안

1. **의존성 추가**: `aec-audio-processing` (또는 선호 라이브러리) 설치 및 16kHz 모노 테스트.
2. **Far-end 수집**: `send_audio_to_caller()`(또는 RTP 전송 직전)에서 TTS PCM을 ring buffer에 누적.
3. **Near-end 처리**: Caller RTP → PCM 변환 후, AEC `process_stream(near, far)` 호출.
4. **출력**: AEC 출력만 `_pipecat_audio_queue`에 넣어 기존 Input Transport → STT 경로 유지.
5. **설정**: `config`에 `aec_enabled`, `aec_far_end_buffer_ms` 등 추가 후 동작 검증.

---

## 7. 구현 현황

- **의존성**: 선택 패키지 `aec-audio-processing` (PyPI). `pip install aec-audio-processing` 또는 `pip install -e ".[aec]"`로 설치. 미설치 시 AEC 비활성화, 기존처럼 raw PCM이 STT로 전달됨.
- **구현 위치**:
  - **래퍼**: `sip-pbx/src/media/aec_processor.py` — `create_aec_processor()`, `AECProcessor.feed_reverse_stream()`(far-end 10ms), `process_stream()`(near-end 10ms → 에코 제거 출력).
  - **연동**: `sip-pbx/src/media/rtp_relay.py`
    - **Far-end**: `_pipecat_tts_sender_loop`에서 TTS PCM을 RTP로 보내기 직전, 10ms(320 bytes) 단위로 `_aec_processor.feed_reverse_stream(chunk)` 호출.
    - **Near-end**: Caller RTP 수신 콜백에서 `rtp_to_pcm16k` 후 `_aec_near_buffer`에 누적. 320 bytes씩 꺼내 `_aec_processor.process_stream(chunk)` 호출한 결과를 `_pipecat_audio_queue`에 넣음. AEC 미사용 시 기존처럼 수신 PCM을 그대로 큐에 넣음.
  - **설정**: 현재는 AEC 사용 가능 시 자동 활성화. 나중에 `config`에 `aec_enabled` 등 추가 가능.
- **프레임**: 16kHz 모노, 10ms = 320 bytes (`AEC_FRAME_BYTES`). `set_stream_delay(50)`으로 50ms 지연 설정.

---

## 8. 참고 자료

- [How WebRTC AEC3 Works (Switchboard)](https://switchboard.audio/hub/how-webrtc-aec3-works/)
- [aec-audio-processing (PyPI)](https://pypi.org/project/aec-audio-processing/)
- [py-webrtcaec (GitHub)](https://github.com/sunchang272/py-webrtcaec)

---

**결론**: 대화를 위해 TTS 중 STT를 막지 않고, **WebRTC AEC로 far-end(TTS) 참조를 두고 near-end(마이크)에서 에코만 제거**하는 방식이 적절하다. 위 구현대로 far-end는 TTS 발송 루프에서, near-end는 RTP 수신 콜백에서 처리된다.
