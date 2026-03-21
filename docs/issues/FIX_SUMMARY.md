# 수정 완료 요약

## 1. Deprecation Warning 수정 ✅

**문제**: `pipecat.services.google` 모듈이 deprecated

**수정**: `sip-pbx/src/sip_core/call_manager.py:599`
```python
# Before
from pipecat.services.google import GoogleSTTService, GoogleTTSService

# After
from pipecat.services.google.stt import GoogleSTTService
from pipecat.services.google.tts import GoogleTTSService
```

## 2. 인사말 Phase 1/2 자동 전송 추가 ✅

**문제**: Pipeline 시작 후 인사말이 자동으로 전송되지 않음

**수정**: `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py:212`
```python
# Pipeline 시작 후 인사말 자동 전송
async def _send_initial_greeting():
    await asyncio.sleep(0.5)  # Pipeline 초기화 대기
    for proc in pipeline.processors:
        if hasattr(proc, 'send_greeting'):
            await proc.send_greeting()
            break

asyncio.create_task(_send_initial_greeting())
```

## 3. RTP 출력 문제 원인 파악 🔍

**문제**: AI 응대 시 RTP가 거의 나가지 않음

**근본 원인**: **통화 종료 후 TTS 생성**
```
13:26:48.326 - BYE received
13:26:48.326 - cleanup_call_start
13:26:53.358 - tts_first_audio_sent (5초 후!)
```

**원인 분석**:
1. 사용자가 말함 ("Welcome", "To") → STT 처리
2. LLM 응답 생성 중 (10초 소요)
3. **그 사이에 사용자가 BYE 전송** (통화 종료)
4. Cleanup 시작
5. 그런데 **LLM 응답이 완료되어 TTS 생성**
6. 이미 통화 종료된 상태라 RTP 전송 안됨

**문제점**:
- BYE 수신 시 Pipeline을 즉시 취소해야 하는데 안하고 있음
- LLM 처리가 너무 느림 (10초)
- Pipeline이 통화 종료를 감지하지 못하고 계속 동작

## 4. 터미널 멈춤 문제

**원인**: Pipeline이 제대로 종료되지 않아서 asyncio event loop이 hang

**해결 필요**:
1. BYE 수신 시 Pipeline 즉시 취소
2. Pipeline cleanup 로직 강화
3. Timeout 추가

## 다음 단계

1. **BYE 수신 시 Pipeline 취소 로직 추가** (중요!)
2. **LLM 응답 속도 개선** (10초 → 3초 이하)
3. **Pipeline cleanup 개선**
4. **프로세스 재시작 후 테스트**

## 테스트 방법

1. 프로세스 종료 (이미 완료)
2. 서버 재시작
3. AI 통화 시작
4. **인사말이 자동으로 나오는지 확인**
5. **사용자가 말하기 전에 전화 끊지 않기**
6. 정상 대화 후 BYE 전송

## 파일 수정 내역

- `sip-pbx/src/sip_core/call_manager.py`
  - Deprecation warning 수정
- `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`
  - 초기 인사말 자동 전송 로직 추가
- `sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`
  - Output Transport 에코 수정 (이전)
- `sip-pbx/src/media/rtp_relay.py`
  - Audio stream timeout 증가 (이전)
