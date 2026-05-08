# 유저간 통화 실시간 STT 기록 설계
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


## 목표

- **유저간 통화**(AI 미개입, RTP 릴레이만)에서도 프론트엔드 실시간 통화 모니터에 **STT가 기록·표시**되도록 한다.
- AI 통화와 동일하게 대시보드 실시간 대화 영역에 발신자/수신자 발화가 누적 표시된다.

## 현재 동작

| 구분 | STT 발생 위치 | 프론트 전달 | 대시보드 표시 |
|------|----------------|-------------|----------------|
| **AI 통화** | Pipecat 파이프라인 내 STT → RAG/LLM | `stt_transcript`, `tts_started`, `ai_greeting` WebSocket 이벤트 | ✅ 발신( user ) / AI( assistant ) |
| **유저간 통화** | 없음 (RTP 릴레이만) | 없음 | ❌ 기록 안 됨 |

## 설계 요약

1. **백엔드**: 유저간 통화(bypass/AI 미활성) 구간에서도 **오디오 스트림에 대한 실시간 STT**를 수행하고, 결과를 기존과 동일한 WebSocket 이벤트 **`stt_transcript`** 로 전송한다.
2. **페이로드 확장**: `stt_transcript` 에 선택 필드 **`channel`** (`'caller'` | `'callee'`) 을 넣어, 유저간 통화일 때 발신/수신 구분이 가능하도록 한다. (AI 통화는 기존처럼 생략 시 발신자 = user 로 처리)
3. **프론트엔드**: `stt_transcript` 수신 시 `channel` 이 있으면 **발신자/수신자** 로 표시하고, 없으면 기존처럼 **발신/AI** 로 표시한다.

---

## 1. WebSocket 이벤트 규격

### `stt_transcript` (기존 + 확장)

서버 → 클라이언트. 실시간 STT 결과 전달.

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `call_id` | string | ✅ | 통화 ID |
| `text` | string | ✅ | 인식된 문장 (또는 interim 텍스트) |
| `is_final` | boolean | 권장 | true: 최종 결과, false: interim |
| `timestamp` | string | 권장 | ISO 8601 |
| **`channel`** | `'caller'` \| `'callee'` | 유저간 통화 시 | 발신자/수신자 구분. 없으면 AI 통화 발신자로 간주 |

- **AI 통화**: `channel` 생략 → 프론트는 기존처럼 `role: 'user'` 로 표시.
- **유저간 통화**: `channel: 'caller'` / `channel: 'callee'` → 프론트는 "발신자" / "수신자" 로 표시.

---

## 2. 백엔드 연동 포인트 (구현 시 참고)

유저간 통화 시 실시간 STT를 넣으려면 아래 중 한 경로로 연동하면 된다.

### 2.1 RTP 워커에서 오디오 수집 후 STT 호출

- **위치**: RTP 릴레이 워커(또는 미디어 세션)에서 **caller → B2BUA**, **callee → B2BUA** 오디오 스트림을 각각(또는 믹스) 버퍼링.
- **조건**: `ai_enabled is False` (유저간 통화), `recording_enabled` 등 녹음 설정이 켜진 경우에만 실시간 STT 태스크 기동.
- **동작**:
  - 버퍼(예: 0.5~2초) 단위로 기존 **Google Cloud STT**(또는 프로젝트의 STT 클라이언트) **streaming recognize** 호출.
  - 결과(interim/final) 수신 시 **WebSocket manager** 로 `emit_stt_transcript(call_id, text, is_final, channel='caller'|'callee')` 호출.
- **주의**: RTP 포트가 caller/callee 별로 나뉘어 있으면 채널 구분이 자연스럽고, 믹스 시에는 채널 구분이 불가하므로 단일 채널로만 전송하거나, 별도 스트림 분리 로직 필요.

### 2.2 기존 녹음 파이프라인 활용 (배치 스타일)

- **위치**: 통화 종료 후 **SIPCallRecorder** 등에서 생성한 WAV(또는 caller/callee 분리 파일)에 대해 **post_stt**(diarization) 가 이미 있다면, 그 결과를 **통화 종료 시점에** 한 번에 WebSocket으로 보내는 방식.
- **한계**: “실시간”은 아니고, 통화가 끝난 뒤에만 대시보드에 반영됨. 실시간 기록 요구사항에는 **2.1** 이 적합.

### 2.3 WebSocket 발송 공통화

- **위치**: 예: `src/websocket/manager.py` (또는 동일 역할 모듈).
- **함수**: `emit_stt_transcript(call_id: str, text: str, is_final: bool, channel: Optional[Literal['caller','callee']] = None, timestamp: Optional[str] = None)`.
  - 해당 `call_id` 를 구독한 클라이언트 룸에 `stt_transcript` 이벤트로 전송.
  - 페이로드에 `channel` 이 있으면 그대로 포함, 없으면 생략(AI 통화 호환).

---

## 3. 프론트엔드 변경 사항

- **대시보드** (`frontend/app/dashboard/page.tsx`):
  - `stt_transcript` 수신 시 `data.channel` 확인.
  - `channel === 'caller'` → 메시지 role `'caller'` (발신자).
  - `channel === 'callee'` → 메시지 role `'callee'` (수신자).
  - `channel` 없음 → 기존과 동일 `role: 'user'` (발신).
  - 실시간 대화 카드에서 "발신자" / "수신자" / "발신" / "AI" 라벨을 role/channel 에 따라 표시.

---

## 4. 백엔드 구현 체크리스트 및 emit 예시

### 4.1 WebSocket 발송 예시 (Python)

유저간 통화 RTP에서 STT 결과가 나올 때마다 아래와 같이 호출하면 된다.

```python
# 예: src/websocket/manager.py 또는 동일 역할 모듈
from datetime import datetime

def emit_stt_transcript(
    call_id: str,
    text: str,
    is_final: bool,
    channel: Optional[Literal["caller", "callee"]] = None,
    timestamp: Optional[str] = None,
) -> None:
    """실시간 STT 결과를 해당 call_id 구독 클라이언트에 전송. 유저간 통화 시 channel 필수."""
    payload = {
        "call_id": call_id,
        "text": text,
        "is_final": is_final,
        "timestamp": timestamp or datetime.utcnow().isoformat() + "Z",
    }
    if channel is not None:
        payload["channel"] = channel  # "caller" | "callee"
    # 해당 call_id 구독 룸으로 전송 (기존 emit_stt_transcript 루틴이 있으면 그곳에 channel 추가)
    await socket_manager.emit_to_call_room(call_id, "stt_transcript", payload)
```

- **AI 통화**: 기존처럼 `channel` 없이 `emit_stt_transcript(call_id, text, is_final)` 만 호출.
- **유저간 통화**: caller 오디오 → `channel="caller"`, callee 오디오 → `channel="callee"` 로 호출.

### 4.2 실시간 STT 연동 위치 (요약)

| 항목 | 권장 위치 | 비고 |
|------|-----------|------|
| 오디오 수집 | RTP 워커(미디어 세션)에서 caller/callee PCM 버퍼 | ai_enabled=False 일 때만 실시간 STT 태스크 기동 |
| STT 호출 | 기존 Google Cloud STT streaming recognize | 언어/설정은 기존 STT와 동일 |
| emit 시점 | STT interim/final 결과 수신 시 | `emit_stt_transcript(call_id, text, is_final, channel=...)` |

---

## 5. 검증 포인트

- 유저간 통화만 걸어서 대시보드에서 해당 통화 선택 시, 실시간으로 발신자/수신자 STT가 쌓이는지 확인.
- AI 통화는 기존처럼 발신/AI만 나오는지 확인.
- `channel` 없이 보내는 기존 백엔드와의 호환성 유지.
