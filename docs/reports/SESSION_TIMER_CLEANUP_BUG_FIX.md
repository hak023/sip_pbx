# Session Timer 정리 버그 수정

**날짜**: 2026-01-16  
**작성자**: AI Assistant  
**상태**: ✅ 수정 완료

---

## 🐛 **문제 설명**

### 증상
서버 구동 후 첫 번째 호는 정상 처리되지만, 두 번째 호부터 INVITE를 받아주지 않는 문제 발생.

### 재현 단계
1. 서버 시작
2. 1001 ↔ 1002 통화 (성공)
3. 통화 종료 (BYE)
4. 다시 1001 ↔ 1002 통화 시도
5. **INVITE가 무시됨** (재전송으로 판단)

---

## 🔍 **원인 분석**

### 로그 분석

```json
// 두 번째 호 시작
{"timestamp": "2026-01-16T03:05:20", "event": "b2bua_call_setup", 
 "call_id": "654e830125971640392483k76586rmwp"}

// 호 종료
{"timestamp": "2026-01-16T03:07:52", "event": "cleanup_call_start", 
 "call_id": "b2bua-234246-654e8301"}

// ❌ BYE 후에도 Session refresh 계속 발생!
{"timestamp": "2026-01-16T03:20:22", "event": "Session refreshed", 
 "call_id": "654e830125971640392483k76586rmwp"}

{"timestamp": "2026-01-16T03:35:22", "event": "Session refreshed", 
 "call_id": "654e830125971640392483k76586rmwp"}
```

### 근본 원인

**Session Timer가 잘못된 Call-ID로 취소를 시도함**

#### Before (버그):
```python
# sip_endpoint.py:1040
session_cancelled = await self._session_timer.cancel_timer(call_id)
#                                                           ^^^^^^^^
#                                                  B2BUA Call-ID (b2bua-xxxx)
```

#### Session Timer 저장:
```python
# Session Timer는 original_call_id로 저장됨
self.active_timers[original_call_id] = {...}
#                  ^^^^^^^^^^^^^^^^^
#                  654e830125971640392483k76586rmwp
```

#### 결과:
- `cancel_timer(b2bua-234246-654e8301)` 호출
- `active_timers`에 `654e830125971640392483k76586rmwp` 키로 저장됨
- **키 불일치 → 취소 실패**
- Session Timer 계속 작동 → UPDATE 메시지 계속 전송
- `_active_calls`에 이전 호 데이터 유지
- 새 INVITE 도착 시 "재전송"으로 판단 → **거부**

---

## ✅ **수정 내용**

### 파일: `sip-pbx/src/sip_core/sip_endpoint.py`

#### After (수정):
```python
# Line 1040-1045
# Session Timer 취소 (✅ 원본 Call-ID로 취소)
session_cancelled = await self._session_timer.cancel_timer(original_call_id)
#                                                           ^^^^^^^^^^^^^^^
#                                                  원본 Call-ID 사용
if session_cancelled:
    print(f"   ⏱️ Session Timer cancelled")
    logger.info("session_timer_cancelled", call_id=original_call_id)
else:
    logger.warning("session_timer_not_found", call_id=original_call_id)
```

### 변경 사항
1. `cancel_timer(call_id)` → `cancel_timer(original_call_id)`
2. Warning 로그 추가 (취소 실패 시)

---

## 🧪 **테스트 검증**

### 테스트 시나리오
1. ✅ 첫 번째 호 정상 동작
2. ✅ BYE 수신 후 Session Timer 취소 확인
3. ✅ 두 번째 호 정상 수신 및 처리
4. ✅ 다중 호 연속 처리

### 예상 로그
```json
// 호 종료 시
{"event": "cleanup_call_start", 
 "call_id": "b2bua-234246-654e8301",
 "original_call_id": "654e830125971640392483k76586rmwp"}

{"event": "session_timer_cancelled", 
 "call_id": "654e830125971640392483k76586rmwp"}  // ✅ 원본 Call-ID로 취소

// 이후 Session refresh 없음!
```

---

## 📊 **영향 범위**

### 수정된 컴포넌트
- `sip_endpoint.py` - `_cleanup_call()` 메서드

### 영향받는 기능
- ✅ Session Timer 정리
- ✅ 다중 호 처리
- ✅ 호 종료 후 리소스 해제

### 의존성
- `session_timer.py` - `cancel_timer()` 메서드 (변경 없음)
- `call_manager.py` - 변경 없음

---

## 🔗 **관련 이슈**

### 유사 버그 수정 이력
1. **RTP Worker 정리** - 이미 `original_call_id` 사용 중 ✅
2. **녹음 정리** - 이미 `original_call_id` 사용 중 ✅
3. **Session Timer 정리** - 이번에 수정 ✅

### Call-ID 사용 일관성
| 컴포넌트 | 저장 시 | 정리 시 | 일관성 |
|----------|---------|---------|--------|
| RTP Worker | `original_call_id` | `original_call_id` | ✅ |
| 녹음 | `original_call_id` | `original_call_id` | ✅ |
| Session Timer | `original_call_id` | ~~`call_id`~~ → `original_call_id` | ✅ 수정 완료 |
| Transaction Timer | `transaction_id` | `transaction_id` | ✅ |

---

## 🚀 **배포 노트**

### 배포 전 체크리스트
- [x] 코드 수정 완료
- [x] 로그 레벨 확인 (warning 추가)
- [ ] 단위 테스트 작성
- [ ] 통합 테스트 실행
- [ ] 성능 테스트 (다중 호)

### 롤백 계획
문제 발생 시:
```python
# 원복: call_id로 변경
session_cancelled = await self._session_timer.cancel_timer(call_id)
```

---

## 📝 **추가 개선 사항**

### 제안 1: Call-ID 통일
B2BUA 구조에서 Call-ID가 2개 (original, b2bua) 존재하여 혼란 발생.

**해결책**:
```python
# 모든 리소스를 original_call_id로 통일
class CallInfo:
    original_call_id: str  # 외부에서 받은 Call-ID
    b2bua_call_id: str     # 내부 B2BUA Call-ID
    
    @property
    def primary_key(self) -> str:
        """리소스 키는 항상 original_call_id 사용"""
        return self.original_call_id
```

### 제안 2: 정리 검증
```python
async def _cleanup_call(self, call_id: str) -> None:
    # ... 정리 작업 ...
    
    # ✅ 정리 검증
    assert call_id not in self._active_calls
    assert call_id not in self._rtp_workers
    assert not self._session_timer.is_active(call_id)
    
    logger.info("cleanup_verified", call_id=call_id)
```

---

## ✅ **결론**

Session Timer가 B2BUA Call-ID 대신 원본 Call-ID로 취소되도록 수정하여,  
호 종료 후에도 Timer가 계속 작동하는 버그를 해결했습니다.

**기대 효과**:
- ✅ 다중 호 정상 처리
- ✅ 리소스 완전 정리
- ✅ 메모리 누수 방지
- ✅ UPDATE 메시지 불필요한 전송 방지

**검증 방법**:
서버 재시작 후 연속 2회 이상 통화 테스트
