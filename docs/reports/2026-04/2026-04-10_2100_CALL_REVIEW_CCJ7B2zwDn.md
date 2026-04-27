# 통화 리뷰 — call_id: CCJ7B2zwDn

작성일: 2026-04-10 21:00  
상태: 원인 확인 및 즉시 수정 완료

---

## 통화 개요

| 항목 | 내용 |
|---|---|
| call_id | CCJ7B2zwDn |
| 방향 | 수신 (inbound) |
| 발신 | 1004 |
| 착신 | 1003 |
| 시작 | 2026-04-10 18:46:00 |
| AI 전환 | 18:46:10 (무응답 10초 후) |
| 종료 | 18:47:35 |
| 발화 횟수 | 고객 3회 (예약, 내일예약, 주차) |

---

## 발견된 이슈

### 🔴 P1 (Critical) — `NameError: _BOOKING_KEYWORDS is not defined`

**증상**: 모든 발화 턴에서 `conversation_agent_invoke_error` 발생, `invoke_error` 응답("죄송합니다. 일시적인 오류...")

**에러 로그**:
```
"event": "conversation_agent_invoke_error",
"error": "name '_BOOKING_KEYWORDS' is not defined"
```

**근본 원인**:

오늘(2026-04-10) `classify_intent.py` 수정 시 `_BOOKING_KEYWORDS = frozenset()` 변수를 삭제하고 `_BOOKING_ACTION_PATTERNS`로 대체했으나, **0차 예약 키워드 매칭 블록**에서 `_BOOKING_KEYWORDS`를 여전히 참조하는 코드가 남아 `NameError` 발생.

```python
# 잘못된 코드 (삭제된 변수 참조)
_booking_matched = next((kw for kw in _BOOKING_KEYWORDS if kw in _query_lower), None)
```

해당 블록은 원래 `_BOOKING_KEYWORDS = frozenset()` (빈 집합)이었으므로 항상 `None`을 반환하여 실제 로직에는 영향 없었지만, 변수 삭제 후 `NameError`로 전체 노드가 크래시됨.

**수정**: 해당 0차 예약 키워드 매칭 블록 전체 제거 (`_query_lower` 변수 선언은 이후 로직에서 사용하므로 유지)

---

### ⚠️ P2 (경고) — STT 동결 의심 (`stt_silence_watchdog_alert`)

**증상**: `18:46:40.416` — STT 29초 동안 `UserStartedSpeakingFrame` 없음

```
"event": "stt_silence_watchdog_alert"
"elapsed_sec": 29.0
"speech_count": 0
```

**분석**: P1 `invoke_error`로 인해 첫 발화(18:46:25)부터 응답이 오류 응답으로 처리됨. 고객이 재발화를 시도하는 동안 STT 워치독이 동결 경보를 발생시킴. P1 해결 시 STT 동결도 자연 해소 예상.

---

## 수정 내역

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `src/ai_voicebot/langgraph/nodes/classify_intent.py` | 수정 | `_BOOKING_KEYWORDS` 참조 0차 블록 제거 (`NameError` 수정) |

---

## 영향 범위

이 서버에서 발생한 **모든 통화**가 오늘 `_BOOKING_ACTION_PATTERNS` 코드 배포 이후 동일한 `NameError`로 실패했을 가능성 있음. 서버 재시작 또는 코드 핫픽스 적용 필요.
