# 일반 통화(유저간) 실시간 STT → 대시보드 연동
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


일반 통화(bypass, AI 미응대)에서도 실시간 STT로 통화 내용을 대시보드에 표시하기 위한 설계 및 연동 방법.

## 흐름

1. **RTP Relay** (bypass 모드): caller/callee RTP 수신 시 `BypassRealtimeSTT.feed_audio(call_id, direction, payload, codec)` 호출.
2. **BypassRealtimeSTT**: G.711 디코딩 → 8kHz PCM 버퍼 → Google Cloud 스트리밍 STT(telephony) → 결과 시 **브로드캐스트 콜백** 호출.
3. **브로드캐스트 콜백**: WebSocket 서버(포트 8001)에서 등록. 콜백이 `stt_transcript` 이벤트를 해당 통화 room에 emit하면 프론트엔드 대시보드에 실시간 대화가 표시됨.

## 백엔드: 브로드캐스트 콜백 등록

WebSocket 서버(예: Socket.IO, 8001) 기동 시 다음을 한 번 호출하면 됨.

```python
from datetime import datetime
from src.media.bypass_realtime_stt import set_broadcast_callback

def on_stt_for_dashboard(call_id: str, text: str, is_final: bool, channel: str):
    # call_id room에 구독한 클라이언트(대시보드)에게만 전송
    payload = {
        "call_id": call_id,
        "text": text,
        "is_final": is_final,
        "channel": channel,  # "caller" | "callee"
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    # Socket.IO 예시 (실제 변수명은 서버 구현에 맞게)
    socketio_server.emit("stt_transcript", payload, room=call_id)

set_broadcast_callback(on_stt_for_dashboard)
```

- **시그니처**: `(call_id: str, text: str, is_final: bool, channel: str) -> None`
- `channel`: `"caller"`(발신자), `"callee"`(수신자). 대시보드에서 발신/수신 구분 표시에 사용.

## 프론트엔드

- 이미 `stt_transcript` 이벤트를 구독하고 `transcriptByCallId`에 반영하며, `channel`로 발신자/수신자 구분 표시함.
- 일반 통화 카드에서도 동일 이벤트가 오면 실시간 대화 영역에 표시됨. 빈 상태 문구는 "대화가 시작되면 여기에 표시됩니다"로 통일.

## 통화 종료 시

- RTP Relay `stop()` 호출 시 `get_bypass_realtime_stt().end_call(call_id)`가 호출되어 해당 통화의 STT 스트림이 정리됨.

## 비활성화

- `get_bypass_realtime_stt().set_enabled(False)` 로 실시간 STT 비활성화 가능.
- Google Cloud Speech-to-Text 미설정 시 스트리밍 세션은 시작되지 않고, 로그만 남김.

## 참고

- `src/media/bypass_realtime_stt.py`: 실시간 STT 서비스 및 `set_broadcast_callback`.
- `src/media/rtp_relay.py`: bypass 시 `feed_audio` 호출, `stop()` 시 `end_call` 호출.
