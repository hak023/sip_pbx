# BYE 처리 버그 수정 리포트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-06 14:30 |
| 상태 | 수정 완료 |
| 관련 파일 | `src/sip_core/sip_endpoint.py` |
| 관련 로그 | `logs/app.log` (라인 3588~3705) |

---

## 1. 문제 요약

`_handle_bye()` 메서드에서 **Call-ID 매핑 탐색 후 early return 버그**가 있어,
`_call_mapping`에서 peer call_id를 찾아도 실제 BYE 처리(AI 모드 체크, relay, cleanup)로 진행되지 않고
즉시 200 OK만 반환하고 종료되는 문제가 있었다.

---

## 2. 증상 (로그 근거)

```
# 첫 번째 BYE — callee(착신)에서 b2bua call_id로 수신
bye_received          call_id: b2bua-254835-hk70edxz  from: 10.69.15.47:34537
bye_not_relayed_ai_mode   (AI 모드)
bye_cleanup_triggered     call_id: hk70edxzFl

# 두 번째 BYE — 460ms 뒤 같은 callee에서 중복 수신
bye_received          call_id: b2bua-254835-hk70edxz
bye_not_relayed_ai_mode   ← cleanup이 끝나기 전 _active_calls에서 여전히 찾아짐
bye_cleanup_triggered     ← 이미 처리 중인데 또 cleanup 시도

# Caller BYE — 20초 뒤 원본 call_id로 수신
bye_received          call_id: hk70edxzFl  from: 10.69.15.197:59588
bye_call_id_mapped    received: hk70edxzFl → mapped_to: b2bua-254835-hk70edxz
                      (이후 로그 없음 — 처리 중단)
```

caller BYE 수신 시 `bye_call_id_mapped` 이후 로그가 없어 **BYE가 실질적으로 처리되지 않은 것처럼** 보였다.

---

## 3. 근본 원인

### 3-1. `_call_mapping` 탐색 로직 버그 (주요 버그)

**수정 전 코드 (들여쓰기 오류 + 탐색 비효율):**

```python
if call_id not in self._active_calls:
    for orig_id, mapped_id in self._call_mapping.items():   # O(n) 순회
        if mapped_id == call_id:
            call_id = orig_id
            break

    if call_id not in self._active_calls:          # inner if
        logger.warning("bye_unknown_call", ...)
        # 200 OK 전송 코드 ← 들여쓰기가 inner if 밖! (16 spaces)
    via = ...                                      ← outer if 블록에 속함
    ...
    return                                         ← 항상 실행됨
```

`via = ...` ~ `return` 블록이 **inner `if` (unknown call 체크) 밖**에 위치하여,
`_call_mapping`으로 peer를 찾은 경우에도 200 OK + return이 실행되었다.

즉, `_call_mapping`에서 찾아 `call_id`를 peer로 바꿔도 실제 BYE 처리로 진입하지 못했다.

**_call_mapping 탐색 방향 이슈:**
- 매핑은 양방향: `orig_id → b2bua_id`, `b2bua_id → orig_id`
- 기존 코드는 `for orig_id, mapped_id in ...` 순회하여 `mapped_id == call_id`를 찾음
- `call_id`가 orig_id일 때 `b2bua_id → orig_id` 방향의 엔트리에서 매칭되어
  `call_id = b2bua_id`(다른 쪽 call_id)로 바뀌는 경우가 발생
- `dict.get(call_id)`로 직접 조회하면 `O(1)`이며 방향 혼란 없음

### 3-2. AI 모드 중복 BYE 처리

- callee가 SIP UA 재전송으로 460ms 간격으로 동일 BYE를 2회 전송
- 첫 번째 BYE → `bye_not_relayed_ai_mode` → `_cleanup_call()` 비동기 시작
- 두 번째 BYE → cleanup 완료 전에 `_active_calls`에서 여전히 찾아짐 → 중복 cleanup 시도
- `_cleanup_call()` 내부에서 `_active_calls.pop(call_id)` 즉시 실행으로 이중 cleanup 방지되지만,
  정확한 로그 확인이 어려웠음

---

## 4. 수정 내용

**파일:** `src/sip_core/sip_endpoint.py` — `_handle_bye()` 메서드

```python
# 수정 전 (버그)
if call_id not in self._active_calls:
    for orig_id, mapped_id in self._call_mapping.items():
        if mapped_id == call_id:
            call_id = orig_id
            break
    if call_id not in self._active_calls:
        logger.warning("bye_unknown_call", ...)
    via = ...          # ← inner if 밖에 있어서 항상 실행
    ...
    return             # ← 항상 실행 (버그 핵심)

# 수정 후 (정상)
if call_id not in self._active_calls:
    mapped_peer = self._call_mapping.get(call_id)    # O(1) 직접 조회
    if mapped_peer and mapped_peer in self._active_calls:
        # peer call_id로 교체 후 정상 BYE 처리로 진행 (return 없음)
        logger.info("bye_call_id_mapped", ...)
        call_id = mapped_peer
        logger.info("bye_call_id_resolved_via_mapping", call_id=call_id)
    else:
        # 매핑 없거나 이미 cleanup된 late BYE → 200 OK + return
        logger.warning("bye_unknown_call", mapped_peer=mapped_peer,
                        note="이미 cleanup된 통화의 late BYE일 가능성 높음")
        ...
        self._send_response(bye_response, addr)
        return         # ← else 블록 내부에서만 return
```

**핵심 변경:**
1. `_call_mapping` 탐색을 O(n) 순회 → `dict.get()` O(1) 직접 조회로 변경
2. peer가 `_active_calls`에 있는 경우: call_id 교체 후 정상 BYE 처리 경로로 진행
3. peer가 없는 경우(이미 cleanup): 200 OK + return (late BYE 정상 처리)
4. `mapped_peer` 값을 warning 로그에 포함하여 원인 추적 용이화

---

## 5. 수정 전후 동작 비교

| 케이스 | 수정 전 | 수정 후 |
|--------|---------|---------|
| call_id가 `_active_calls`에 있음 | 정상 처리 | 정상 처리 (변경 없음) |
| call_id 없음, mapping에서 peer 찾음, peer는 active | **200 OK + return (버그)** | **정상 BYE 처리** |
| call_id 없음, mapping에서 peer 찾음, peer도 없음 | 200 OK + return | 200 OK + return (late BYE) |
| call_id 없음, mapping에도 없음 | 200 OK + return | 200 OK + return (unknown) |

---

## 6. 영향 범위

- **AI 모드 통화:** callee가 먼저 BYE를 보내 cleanup이 완료된 후 caller BYE가 도착하는 경우 → late BYE로 올바르게 처리됨
- **일반 B2BUA 통화:** b2bua call_id로 BYE가 도착했을 때 `_active_calls`에서 직접 찾아지므로 영향 없음
- **Outbound 통화:** call_id가 `_active_calls`에 있으므로 영향 없음

---

## 7. 향후 개선 제안

1. **중복 BYE 방지:** `call_info`에 `bye_received` 플래그를 추가하여 동일 통화에 대한 BYE 중복 처리를 명시적으로 차단
2. **`_call_mapping` 조기 정리:** cleanup 시작 시 `_call_mapping`에서도 즉시 제거하여 late BYE가 stale 매핑을 찾는 것을 방지
