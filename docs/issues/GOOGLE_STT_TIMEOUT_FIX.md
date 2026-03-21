# Google STT 409 Timeout 에러 해결

## 문제 설명

AI 응대 중 Google Cloud Speech-to-Text 서비스에서 **409 Stream timed out** 에러가 발생하여 통화가 중단되는 문제.

## 발생 증상

1. **Google STT 409 에러**
   ```
   GoogleSTTService#0 exception: Unknown error occurred: 409 Stream timed out 
   after receiving no more client requests.
   ```

2. **TTS 음성이 거의 안들림**
   - RTP 패킷은 큐에 쌓이지만 실제 전송이 느림
   - 큐 사이즈가 계속 증가 (393, 418, 443...)

3. **프로세스가 멈춤**
   - Ctrl+C로도 종료 안됨
   - 터미널 hang 상태

## 근본 원인 분석

### 1. Google STT 스트림 타임아웃

**타임라인:**
```
13:06:23.431 - Pipecat 모드 활성화
13:06:43.395 - Pipeline 시작 (20초 지연!)
13:06:43.399 - 첫 RTP 패킷 큐 투입
13:06:43.449 - Input Transport 시작 (50ms 지연)
13:06:53.014 - 첫 STT 결과 (10초 후)
13:07:36.416 - Google STT 409 에러 (53초 후)
```

**문제점:**
- Pipeline 빌드가 20초 소요 (ChromaDB/LangGraph 초기화)
- 이 시간 동안 RTP 패킷이 쌓이지만 STT로 전달 안됨
- `get_caller_audio_stream()`의 **0.1초 타임아웃**이 너무 짧음
  - 큐가 비면 0.1초마다 TimeoutError → continue
  - Google STT는 이를 "스트림에 데이터 없음"으로 인식
  - 일정 시간 동안 데이터 없으면 자동 타임아웃 (409)

### 2. RTP 발송 루프 문제

**문제점:**
- `_pipecat_outgoing_sender_loop()`의 **0.1초 타임아웃**도 짧음
- 큐에 패킷이 쌓여도 타임아웃으로 인한 loop 회전 지연
- 100개마다 찍혀야 할 `rtp_sender_progress` 로그가 없음 → 실제 전송 안됨

### 3. 로그 부족

- Input Transport가 오디오를 정상적으로 읽고 있는지 확인 불가
- RTP 발송 루프가 정상 동작하는지 확인 불가

## 해결 방법

### 1. `get_caller_audio_stream()` 타임아웃 증가

**변경:**
```python
# Before
pcm_data = await asyncio.wait_for(
    self._pipecat_audio_queue.get(), timeout=0.1  # 100ms
)

# After
pcm_data = await asyncio.wait_for(
    self._pipecat_audio_queue.get(), timeout=5.0  # 5초
)
```

**효과:**
- Google STT 스트림이 타임아웃되지 않음
- 오디오가 없어도 STT 연결 유지
- 사용자가 말하기 시작하면 즉시 처리

### 2. RTP 발송 루프 타임아웃 증가

**변경:**
```python
# Before
packet = await asyncio.wait_for(
    self._pipecat_outgoing_queue.get(), timeout=0.1
)

# After
packet = await asyncio.wait_for(
    self._pipecat_outgoing_queue.get(), timeout=1.0  # 1초
)
```

**효과:**
- 불필요한 TimeoutError 감소
- RTP 패킷 전송 안정성 향상

### 3. 디버깅 로그 추가

**추가된 로그:**
```python
# Input Transport
- pipecat_audio_stream_started: 스트림 시작
- pipecat_audio_stream_first_packet: 첫 패킷 처리
- pipecat_audio_stream_progress: 100개마다 진행상황
- pipecat_audio_stream_no_data: 5초 동안 오디오 없음 경고
- pipecat_audio_stream_stopped: 스트림 종료 + 총 패킷 수

# RTP 발송 루프 (기존)
- rtp_first_packet_sent: 첫 RTP 전송
- rtp_sender_progress: 100개마다 진행상황
- rtp_sender_session_end: 세션 종료 + 총 패킷 수
```

## 수정 파일

- `sip-pbx/src/media/rtp_relay.py`
  - `get_caller_audio_stream()`: 타임아웃 5초로 증가 + 로그 추가
  - `_pipecat_outgoing_sender_loop()`: 타임아웃 1초로 증가

## 테스트 방법

1. **서버 재시작**
   ```powershell
   cd sip-pbx
   ./start-all.ps1
   ```

2. **AI 통화 시작**
   - 1003에서 1004로 전화
   - 10초 대기 (AI 응대 시작)

3. **확인 사항**
   ```bash
   # 로그 확인
   tail -f logs/app.log | grep -E "pipecat_audio_stream|rtp_sender"
   ```

4. **성공 지표**
   - `pipecat_audio_stream_started` 로그 확인
   - `pipecat_audio_stream_first_packet` 로그 확인
   - Google STT 409 에러 없음
   - TTS 음성 정상적으로 들림
   - `rtp_sender_progress` 로그 100개마다 출력

## 예상 효과

1. **Google STT 안정성**
   - 스트림 타임아웃 문제 해결
   - 긴 대화도 안정적으로 처리

2. **RTP 전송 안정성**
   - TTS 음성이 정상적으로 들림
   - 큐 오버플로우 방지

3. **디버깅 개선**
   - 오디오 흐름 추적 가능
   - 문제 발생 시 빠른 원인 파악

## 추가 개선 사항 (향후)

1. **Pipeline 빌드 최적화**
   - ChromaDB/LangGraph 사전 초기화
   - 빌드 시간 20초 → 1초 이하로 단축

2. **Google STT Keep-alive**
   - 오디오가 없을 때 silence 프레임 전송
   - 스트림 연결 유지

3. **RTP 발송 패이싱 개선**
   - 큐 사이즈 기반 동적 interval 조정
   - 지터 버퍼 오버플로우 방지

## 관련 이슈

- 이전 대화 로그: [a6b3cebd-e2e3-4fde-aa1e-a2c2201dec19](../../agent-transcripts/a6b3cebd-e2e3-4fde-aa1e-a2c2201dec19.txt)
- Google Cloud STT API: https://cloud.google.com/speech-to-text/docs/streaming-recognize
