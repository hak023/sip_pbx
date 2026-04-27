# Away 모드 AI 인계 시 RTP Worker 타이밍 버그 수정

- **작성일**: 2026-04-06 16:30
- **상태**: 수정 완료
- **관련 파일**: `src/sip_core/sip_endpoint.py`
- **증상 call_id**: `b4YxtR6uy5`

---

## 증상

Away 모드(부재중)에서 AI 인계 시 발신자에게 AI 음성이 전달되지 않음.

- `pipecat_no_rtp_worker` → legacy 폴백
- `TTS RTP callback not set` → TTS 오디오 미전달
- `rtp_tts_packets_sent: 0` → 실제 패킷 0개
- 발신자가 1분 이상 기다리다 CANCEL

---

## 로그 흐름 (버그 발생 시)

```
14:22:05.416  b2bua_invite_received (call_id: b4YxtR6uy5)
14:22:05.416  callee_is_away_activating_ai
14:22:05.416  handle_no_answer_timeout 호출   ← ❌ RTP worker 아직 없음
14:22:05.416  pipecat_no_rtp_worker → legacy 폴백
14:22:22.741  early_bind_starting / _start_rtp_relay  ← RTP worker 이제 생성됨
14:22:20.436  call_established_wait_timeout (15초 대기 후 타임아웃)
14:22:20.438  TTS RTP callback not set       ← 음성 미전달
14:23:34.176  CANCEL (발신자 포기)
```

---

## 근본 원인

`sip_endpoint.py`에서 Away 모드 처리 시 호출 순서 버그:

### 수정 전 순서 (❌)
```
1. _active_calls에 call_info 등록
2. handle_no_answer_timeout() 호출  ← RTP worker 조회 → 없음 → legacy 폴백
3. ...
4. _start_rtp_relay()               ← RTP worker 등록 (너무 늦음)
5. notify_call_established()
```

### 수정 후 순서 (✅)
```
1. _active_calls에 call_info 등록
2. ...
3. _start_rtp_relay()               ← RTP worker 등록 (Early Bind)
4. handle_no_answer_timeout()       ← RTP worker 조회 → 있음 → pipecat 경로
5. notify_call_established()        ← call_established_event set
```

`call_manager.handle_no_answer_timeout()`에서 pipecat_builder는 `_rtp_workers.get(call_id)`로 RTP worker를 찾는데, Away 모드에서는 `handle_no_answer_timeout`이 `_start_rtp_relay`보다 먼저 호출돼 항상 worker가 없었음.

---

## 수정 내용 (`sip_endpoint.py`)

### 제거된 코드 (line ~2636)
```python
# away 모드: call_info 생성 후 AI 모드 활성화
if _is_away_call and self.call_manager:
    await self.call_manager.handle_no_answer_timeout(call_id, callee_username)
```

### 추가된 코드 (Early Bind 이후 `_is_away_call` 블록 내)
```python
if _is_away_call:
    # RTP 바인딩 완료 후 handle_no_answer_timeout 호출
    if self.call_manager:
        await self.call_manager.handle_no_answer_timeout(call_id, callee_username)
        logger.info("ai_mode_activated_by_away_status", ...)

    # call_established 이벤트 set (기존 위치 유지)
    if self.call_manager:
        self.call_manager.notify_call_established(call_id)
```

---

## 수정 후 기대 로그 흐름

```
b2bua_invite_received
callee_is_away_activating_ai
early_bind_starting
early_bind_success            ← RTP worker 등록 완료
handle_no_answer_timeout
✅ [Pipecat] Pipeline task started   ← pipecat 경로 성공
away_mode_call_established_notified
call_established_received_starting_greeting
orchestrator_greeting_phase1_sent
TTS 오디오 → RTP 패킷 전송   ← 발신자가 AI 음성 수신
```
