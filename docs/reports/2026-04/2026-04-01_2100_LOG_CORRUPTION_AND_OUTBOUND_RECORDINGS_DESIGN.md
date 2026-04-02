# 로그 파일 손상 수정 및 아웃바운드 Recordings 설계

- **작성일**: 2026-04-01 21:00 (KST)
- **상태**: 수정 완료
- **관련 파일**:
  - `src/common/call_data_record_logger.py`
  - `src/sip_core/sip_call_recorder.py`
  - `src/sip_core/sip_endpoint.py`
  - `src/api/routers/call_history.py`

---

## 1. 로그 파일 손상 문제 (call_data_record_*.log 잘림)

### 현상

`call_data_record_20260401.log` 49번 라인에서 JSON이 중간에 잘려 다음 라인과 연결됨:

```
48|{"ts": "...T14:27:57.417", ..., "call_id": "outbound-ob-98df573b-30841689", ..., "event": "call_ended", ...}
49|psed_sec": 15.015, "total_elapsed_sec": 15.015, ...}          ← 잘린 채 이전 엔트리 이어짐
50|{"ts": "...T15:19:36.112", "call_id": "outbound-ob-ac766156-50807332", ...}
```

라인 49는 `agent_graph_total` 이벤트의 JSON 앞부분이 누락된 채 이전 라인에 붙어 있음.

### 원인 분석

`call_data_record_logger.py`의 `_ensure_file()`은 `open(path, "a")` 모드로 파일을 열어 `f.write(line)`을 호출한다.

서버가 비정상 종료(crash, SIGKILL, 전원 차단 등)될 때 OS 버퍼에 있던 마지막 write가 **개행(`\n`) 없이** 디스크에 플러시된 채로 남을 수 있다. 다음 서버 기동 시 append 모드로 이어 쓰면 새 JSON이 잘린 이전 JSON 뒤에 직접 붙어버린다.

예시:
```
...call_ended"}\n              ← 정상 write
{"ts": "..."}                  ← 서버 crash 시 \n 없이 끝남
{"ts": "next"}                 ← 재시작 후 새 라인 → 같은 줄로 인식됨
```

### 수정 내용

`_ensure_file()` 내 파일을 처음 열기 직전, 기존 파일의 **마지막 바이트**를 확인한다:

```python
if path.exists() and path.stat().st_size > 0:
    with open(path, "rb") as _rb:
        _rb.seek(-1, 2)
        last_byte = _rb.read(1)
    if last_byte != b"\n":
        # 잘린 라인 뒤에 개행 추가
        with open(path, "ab") as _ab:
            _ab.write(b"\n")
```

이렇게 하면 재기동 시 직전 손상 라인 뒤에 안전한 개행이 삽입되므로 다음 JSON이 새 줄에 기록된다. (파싱 시 잘린 JSON은 `json.JSONDecodeError`로 무시됨)

---

## 2. 아웃바운드 Recordings 현황 및 설계

### 2-1. 현황

`sip_endpoint.py`의 `_start_rtp_relay` 함수에서 아웃바운드 통화도 이미 `start_recording`을 호출한다:

```python
_direction = "outbound" if call_info.get('is_outbound') else "inbound"
await sip_recorder.start_recording(
    call_id=call_id,
    caller_id=caller_username,
    callee_id=callee_username,
    direction=_direction,
)
```

즉 **녹음 자체는 정상 동작** 중이며, `metadata.json`에도 `"direction": "outbound"`가 기록된다.

### 2-2. 발견된 문제: 디렉토리명에 direction 구분 없음

기존 녹음 디렉토리명:
```
20260401_142556_1003_to_1004/   ← 인바운드인지 아웃바운드인지 불명
```

이렇게 되면 파일 탐색기나 로그 분석 시 방향 구분이 불가능하다.

### 2-3. 수정 내용

`sip_call_recorder.py`의 `start_recording`에서 `direction`에 따라 접두사를 추가:

```python
prefix = "ob" if direction == "outbound" else "ib"
dir_name = f"{timestamp}_{prefix}_{caller_id}_to_{callee_id}"
```

수정 후 디렉토리명 예시:
```
20260401_142556_ib_1004_to_1003/   ← 인바운드: callee=1004 수신
20260401_152005_ob_1003_to_1004/   ← 아웃바운드: caller=1003이 1004에 발신
```

### 2-4. 통화이력(call_history) 연동 현황

`call_history.py` API는 `recordings/` 아래 각 하위 디렉토리의 `metadata.json`을 스캔하며:

```python
"direction": m.get("direction", "inbound"),
```

이미 `direction` 필드를 반환하므로 **프론트엔드에서 인바운드/아웃바운드 구분 표시가 가능**하다.

또한 `_owner_matches_row`가 `caller_id`와 `callee_id` 양쪽을 검사하므로 아웃바운드 통화도 owner 필터에 매칭된다.

### 2-5. 아웃바운드 Recordings에서 남은 고려사항

| 항목 | 현황 | 비고 |
|------|------|------|
| 녹음 파일 생성 | ✅ 정상 | `caller.wav`, `callee.wav`, `mixed.wav` |
| `metadata.json` direction 기록 | ✅ 정상 | `"direction": "outbound"` |
| 디렉토리명 direction 구분 | ✅ **이번에 수정** | `ob_` / `ib_` 접두사 |
| 통화이력 API 아웃바운드 조회 | ✅ 정상 | `_owner_matches_row` 양방향 검사 |
| 프론트엔드 direction 배지 표시 | ✅ 정상 | 이전 대화에서 구현됨 |
| Transcript(대화 기록) | ⚠️ AI 아웃바운드는 pipeline transcript | `conversation.json` 생성 여부 점검 필요 |
| call_insights / summary | ⚠️ 아웃바운드 통화 목적 달성 여부 | `call_insights.json`에 outbound 미션 결과 미포함 |

### 2-6. 향후 개선 권고 (call_insights 아웃바운드 통화 목적 기록)

아웃바운드 통화 종료 시 `call_insights.json`에 다음 필드를 추가하면 통화이력에서 미션 달성 여부를 확인할 수 있다:

```json
{
  "outbound_mission_completed": true,
  "outbound_answers": {
    "서비스 만족도 점수": "5점",
    "재이용 의향": "예"
  }
}
```

이는 `rag_processor.py`의 `_trigger_mission_complete` 호출 시 `call_insights_buffer`에 저장하는 방식으로 구현 가능하다.

---

## 요약

| 이슈 | 원인 | 수정 |
|------|------|------|
| `call_data_record_*.log` JSON 라인 손상 | 서버 비정상 종료 시 개행 없이 write 종료 후 재기동 시 이어 쓰기 | `_ensure_file()`에서 마지막 바이트 확인 후 개행 보정 |
| 아웃바운드 녹음 디렉토리 구분 불가 | 디렉토리명에 direction 없음 | `ob_` / `ib_` 접두사 추가 |
