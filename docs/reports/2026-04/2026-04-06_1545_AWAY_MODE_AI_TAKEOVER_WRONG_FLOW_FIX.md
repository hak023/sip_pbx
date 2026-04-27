# away 모드 AI Takeover 잘못된 흐름 수정

- **작성일**: 2026-04-06 (로컬)
- **상태**: 수정 완료
- **관련 파일**: `src/sip_core/sip_endpoint.py`
- **관련 call_id 예시**: `Qlq5z5UFp5` (13:15), `4Dn0Cl1wjk` (13:47)

---

## 1. 증상

착신자(1003)가 **away(부재) 상태**인데도 유저간 통화가 **bypass 릴레이 모드**로 정상 연결되고, 연결 후 **15초 뒤**에 `call_established_wait_timeout_starting_greeting`이 찍히며 AI가 인사를 발화함.

```
callee_is_away_activating_ai
→ no_answer_timeout_activating_ai
→ (B2BUA INVITE → 착신자 응답 → call_established, bypass_realtime_stt_feed_started)
→ [15초 경과]
→ call_established_wait_timeout_starting_greeting
→ 🔄 [AI Takeover] 2-Phase Greeting start
```

---

## 2. 근본 원인 (3가지 복합)

### 원인 A: call_info 덮어씌움으로 `ai_mode_activated` 소실

`handle_no_answer_timeout` 내부에서 `_active_calls[call_id]['ai_mode_activated'] = True`를 설정하지만, 이 시점에는 `_active_calls[call_id]`가 아직 없는 경우가 있음. 이후 `call_info = {...}` dict를 새로 만들어 `_active_calls[call_id] = call_info`로 할당하면 **`ai_mode_activated` 키가 없는 새 dict로 덮어씌워짐**.

ACK 수신 시 `call_info.get('ai_mode_activated', False)` → `False` → `notify_call_established` 미호출.

### 원인 B: away 모드에서도 B2BUA INVITE를 착신자에게 그대로 전송

away 판단 후 AI 활성화를 하고도 코드 흐름이 계속 이어져 **착신자에게 INVITE를 전송**함. 착신자가 응답(200 OK)하고 양방향 미디어(bypass 릴레이)가 열림.

### 원인 C: `notify_call_established` 미호출 → 15초 타임아웃

`_call_established_event`는 `handle_no_answer_timeout`에서 등록되었으나, ACK 처리에서 `is_ai_mode=False`로 판단해 B2BUA relay 경로를 탐 → `notify_call_established` 미호출 → Legacy 오케스트레이터 `handle_call()`에서 15초 대기 후 타임아웃 발생 → AI 인사 강제 시작.

---

## 3. 수정 내용 (`sip_endpoint.py`)

### 3.1 `call_info` 생성 시 away 플래그 포함

```python
_is_away_call = status_manager.is_away(callee_username)
...
call_info = {
    ...
    'ai_mode_activated': _is_away_call,
    'is_ai_call': _is_away_call,
}
self._active_calls[call_id] = call_info  # 이후 덮어씌움 없음

# call_info 등록 후 AI 활성화 (순서 중요)
if _is_away_call and self.call_manager:
    await self.call_manager.handle_no_answer_timeout(call_id, callee_username)
```

### 3.2 away 모드에서 B2BUA INVITE 전송 생략

```python
if _is_away_call:
    logger.info("away_mode_skip_invite_to_callee", ...)
else:
    self._send_response(invite_to_callee, callee_addr)
    # Transaction Timer, no_answer_timer 시작
    ...
```

### 3.3 away 모드: RTP 바인딩 후 즉시 `call_established` 이벤트 set

ACK가 오지 않으므로 `notify_call_established`를 RTP 바인딩 완료 직후 직접 호출.

```python
if _is_away_call:
    self.call_manager.notify_call_established(call_id)
    logger.info("away_mode_call_established_notified", ...)
```

---

## 4. 수정 후 기대 흐름

```
callee_is_away_activating_ai
→ call_info 생성 (ai_mode_activated=True 포함)
→ handle_no_answer_timeout → AI 이벤트 등록
→ away_mode_skip_invite_to_callee  ← INVITE 미전송
→ early_bind_success (RTP 소켓 바인딩)
→ away_mode_call_established_notified  ← 이벤트 즉시 set
→ (오케스트레이터) call_established_received_starting_greeting  ← 타임아웃 없이 정상 진행
→ 🔄 [AI Takeover] 2-Phase Greeting start
```

---

## 5. 확인 포인트 (재기동 후)

- `away_mode_skip_invite_to_callee` 로그 출현
- `away_mode_call_established_notified` 로그 출현
- `call_established_received_starting_greeting` (타임아웃 아닌 정상 경로)
- `call_established_wait_timeout_starting_greeting` **미출현**
- bypass 릴레이(`bypass_realtime_stt_feed_started`) **미출현**
