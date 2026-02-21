# SIP PBX 타이머 설정 현황 분석

**생성일**: 2026-01-08  
**분석 대상**: SIP 세션 및 트랜잭션 타이머

---

## 📊 현재 구현된 타이머

### 1️⃣ **RTP 미디어 타임아웃** ✅
- **위치**: `config/config.yaml`
- **설정값**: 60초
- **용도**: RTP 패킷이 60초 동안 수신되지 않으면 통화 자동 종료
- **상태**: ✅ **구현 완료**

```yaml
media:
  rtp_timeout: 60  # seconds without RTP → auto-terminate
```

---

### 2️⃣ **INVITE 타임아웃** ✅
- **위치**: `src/sip_core/call_manager.py`
- **설정값**: 30초 (하드코딩)
- **용도**: 착신자가 응답하지 않을 때 타임아웃 처리
- **상태**: ✅ **구현 완료**

```python
def handle_invite_timeout(
    self,
    call_session: CallSession,
    timeout_seconds: int = 30,  # 30초 기본값
) -> int:
```

---

### 3️⃣ **부재중 (No Answer) 타임아웃** ✅
- **위치**: `src/sip_core/call_manager.py`
- **설정값**: 10초 (하드코딩)
- **용도**: AI 보이스봇 활성화 판단 시점
- **상태**: ✅ **구현 완료**

```python
no_answer_timeout: int = 10,  # AI 활성화 타임아웃 (초)
```

**동작 방식:**
- 착신자가 10초 내 응답 없으면 → AI 자동 응답
- 10초 초과 30초 이내 응답 없으면 → 408 Request Timeout

---

### 4️⃣ **REGISTER Expires** ✅
- **위치**: `src/sip_core/register_handler.py`
- **설정값**: 3600초 (1시간, 하드코딩)
- **용도**: SIP 등록 만료 시간
- **상태**: ✅ **구현 완료**

```python
if expires is None:
    expires = 3600  # 기본 1시간
```

---

## ❌ 미구현 / 누락된 타이머

### 5️⃣ **SIP 트랜잭션 타이머 (RFC 3261)** ❌

| 타이머 | 기본값 | 용도 | 상태 |
|-------|--------|------|------|
| **T1** | 500ms | RTT Estimate (UDP 재전송 기본 간격) | ❌ 미구현 |
| **T2** | 4초 | 최대 재전송 간격 | ❌ 미구현 |
| **T4** | 5초 | 최대 메시지 수명 | ❌ 미구현 |
| **Timer A** | T1 | INVITE 재전송 간격 (초기) | ❌ 미구현 |
| **Timer B** | 64*T1 (32초) | INVITE 트랜잭션 타임아웃 | ❌ 미구현 |
| **Timer D** | 32초 이상 | 응답 재전송 수락 대기 | ❌ 미구현 |
| **Timer F** | 64*T1 (32초) | Non-INVITE 트랜잭션 타임아웃 | ❌ 미구현 |
| **Timer H** | 64*T1 (32초) | ACK 수신 대기 시간 | ❌ 미구현 |
| **Timer I** | T4 (5초) | ACK 재전송 수락 대기 | ❌ 미구현 |

**참고**: RFC 3261 Section 17 (Transaction Layer)

---

### 6️⃣ **Session-Expires (RFC 4028)** ❌

| 항목 | 기본값 | 용도 | 상태 |
|------|--------|------|------|
| **Min-SE** | 90초 | 최소 세션 갱신 간격 | ❌ 미구현 |
| **Session-Expires** | 1800초 (30분) | 세션 만료 시간 | ❌ 미구현 |
| **Refresher** | UAC/UAS | 누가 세션 갱신할지 결정 | ❌ 미구현 |

**용도**: 장시간 통화 시 주기적 UPDATE/re-INVITE로 세션 유지

---

### 7️⃣ **다이얼로그 관리 타이머** ❌

| 타이머 | 기본값 | 용도 | 상태 |
|-------|--------|------|------|
| **BYE Timeout** | 32초 | BYE 응답 대기 시간 | ❌ 미구현 |
| **Dialog Cleanup** | 설정 없음 | 좀비 다이얼로그 정리 | ❌ 미구현 |

---

## 🚨 주요 문제점

### 1. **재전송 메커니즘 없음** ⚠️
- UDP 환경에서 SIP 메시지 손실 시 재전송 없음
- **결과**: 패킷 손실 시 통화 실패 가능성

### 2. **트랜잭션 타임아웃 없음** ⚠️
- INVITE, BYE 등 요청에 대한 응답을 무한정 대기
- **결과**: 좀비 트랜잭션 누적 가능

### 3. **세션 갱신 메커니즘 없음** ⚠️
- 장시간 통화 시 NAT 바인딩 타임아웃 가능
- **결과**: 네트워크 장애 시 RTP 패킷 손실

### 4. **설정 파일 미반영** ⚠️
- 대부분의 타임아웃이 하드코딩됨
- **결과**: 운영 환경에 맞는 유연한 튜닝 불가

---

## 💡 권장 개선 사항

### Priority 1: 필수 (Essential)

1. **설정 파일화**
   ```yaml
   sip:
     timers:
       invite_timeout: 30        # 초
       no_answer_timeout: 10     # 초
       bye_timeout: 32           # 초
       register_expires: 3600    # 초
   ```

2. **Session-Expires 구현**
   - 장시간 통화 안정성 향상
   - NAT 바인딩 유지

3. **BYE Timeout 처리**
   - BYE 요청 시 응답 타임아웃 (32초)
   - 타임아웃 시 강제 세션 종료

### Priority 2: 중요 (Important)

4. **트랜잭션 타이머 (T1, T2, T4)**
   - UDP 환경 안정성 향상
   - 재전송 메커니즘 구현

5. **Dialog Cleanup 메커니즘**
   - 주기적으로 좀비 다이얼로그 정리
   - 메모리 누수 방지

### Priority 3: 선택 (Optional)

6. **동적 타이머 조정**
   - 네트워크 상태에 따라 T1 값 동적 조정
   - RTT 측정 및 반영

---

## 📋 구현 체크리스트

- [ ] `config.yaml`에 SIP 타이머 섹션 추가
- [ ] `Config` 모델에 타이머 설정 추가
- [ ] Session-Expires 헤더 처리 (INVITE, UPDATE)
- [ ] UPDATE 메서드 구현 (세션 갱신용)
- [ ] BYE 타임아웃 처리
- [ ] 트랜잭션 레이어 타이머 (T1, T2, T4)
- [ ] 재전송 메커니즘 구현
- [ ] Dialog cleanup 스케줄러
- [ ] 타이머 관련 로깅 강화

---

## 📚 참고 문서

- **RFC 3261**: SIP: Session Initiation Protocol (Section 17: Transaction Layer)
- **RFC 4028**: Session Timers in the Session Initiation Protocol (SIP)
- **RFC 3264**: An Offer/Answer Model with the Session Description Protocol (SDP)

---

**작성자**: AI Assistant  
**검토 필요**: SIP 전문가, 운영 팀

