# B2BUA (Back-to-Back User Agent) 구현 상태

SIP PBX는 B2BUA(Back-to-Back User Agent)로 동작하며, 양쪽 SIP leg을 독립적으로 제어합니다.

## 구현된 기능 ✅

### 1. 사용자 등록 관리
- ✅ REGISTER 요청 처리
- ✅ 사용자 정보 저장 (username, IP, port, contact)
- ✅ 등록 해제 (Expires: 0)
- ✅ 등록된 사용자 목록 추적

### 2. B2BUA 통화 처리
- ✅ INVITE 요청 수신 및 발신자에게 100 Trying 응답
- ✅ 수신자(callee) 등록 상태 확인
- ✅ 수신자에게 새로운 INVITE 전송 (독립적인 Call-ID, Via 헤더)
- ✅ 수신자의 180 Ringing을 발신자에게 전달
- ✅ 수신자의 200 OK를 발신자에게 전달
- ✅ ACK 처리 (양방향)
- ✅ BYE 처리 (양방향)
- ✅ CANCEL 처리 (진행 중인 INVITE 취소)
- ✅ UPDATE 처리 (세션 업데이트)
- ✅ PRACK 처리 (신뢰성 있는 provisional 응답)
- ✅ OPTIONS 처리 (Keep-alive 및 헬스 체크)

### 3. 미디어 처리
- ✅ SDP 파싱 및 조작
- ✅ 미디어 포트 동적 할당 (포트 풀 관리)
- ✅ RTP Bypass 모드 (직접 relay, 저지연)
- ✅ 코덱 디코딩 지원 (G.711, Opus)

### 4. 세션 관리
- ✅ 통화 상태 추적 (CallSession)
- ✅ Dialog 관리 (Call-ID, From/To 태그)
- ✅ Transaction 관리
- ✅ 세션 타임아웃 및 정리

### 5. 이벤트 및 알림
- ✅ 통화 이벤트 생성 (시작, 종료)
- ✅ Webhook 알림 (HTTP POST)
- ✅ CDR (Call Detail Record) 생성
- ✅ 구조화된 로깅

### 6. 모니터링
- ✅ Prometheus 메트릭
- ✅ 활성 통화 수 추적
- ✅ 포트 사용률 모니터링
- ✅ HTTP 헬스체크 엔드포인트

## 미구현 기능 (향후 계획) ⚠️

### 1. 보안 기능
- ❌ SIP TLS/SRTP 암호화
- ❌ SIP 인증 (Digest Authentication)

### 2. 추가 SIP 메서드
- ❌ SUBSCRIBE/NOTIFY (이벤트 구독)
- ❌ PUBLISH (상태 게시)
- ❌ MESSAGE (인스턴트 메시지)
- ❌ INFO (세션 내 정보 전송)
- ❌ REFER (통화 전환)

### 3. 고급 기능
- ❌ 통화 녹음
- ❌ 실시간 통화 품질 모니터링 (MOS 점수)
- ❌ GUI 관리 인터페이스
- ❌ 데이터베이스 통합

## 통화 흐름 예시

### REGISTER
```
Client → PBX: REGISTER sip:user@domain
PBX: 사용자 정보 저장
PBX → Client: 200 OK
```

### 완전한 INVITE 흐름 (B2BUA)
```
Caller → PBX: INVITE to Callee
PBX → Caller: 100 Trying
PBX: Callee가 등록되어 있는지 확인
PBX → Callee: INVITE (새 Call-ID, Via 헤더)
Callee → PBX: 100 Trying
Callee → PBX: 180 Ringing
PBX → Caller: 180 Ringing
Callee → PBX: 200 OK (SDP)
PBX: 미디어 포트 할당 및 SDP 조작
PBX → Caller: 200 OK (수정된 SDP)
Caller → PBX: ACK
PBX → Callee: ACK
[RTP 미디어 스트림 relay 시작]
Caller → PBX: BYE
PBX → Callee: BYE
Callee → PBX: 200 OK
PBX → Caller: 200 OK
[세션 종료, 포트 해제, CDR 생성]
```

### 미등록 사용자 호출
```
Caller → PBX: INVITE to Unknown
PBX: Unknown이 등록되어 있지 않음
PBX → Caller: 404 Not Found
```

## 테스트 시나리오

### 1. 기본 통화 테스트
1. 두 사용자 (1004, 1008) REGISTER
2. 1004 → 1008 INVITE
3. 1008 응답 (180 Ringing, 200 OK)
4. 통화 연결 확인
5. BYE로 통화 종료
6. CDR 생성 확인

### 2. 통화 취소 테스트
1. 1004 → 1008 INVITE
2. 180 Ringing 수신
3. 1004가 CANCEL 전송
4. 양쪽 leg 모두 종료 확인

### 3. 미등록 사용자 테스트
1. 1004 → 9999 INVITE
2. 404 Not Found 응답 확인

### 4. 미디어 포트 테스트
1. 여러 동시 통화 설정
2. 각 통화당 8개 포트 할당 확인
3. 통화 종료 시 포트 해제 확인

## 성능 및 제한사항

### 검증된 성능
- 동시 통화: 100호 목표 (현재 테스트 완료: 소규모)
- SIP 응답 시간: <100ms
- RTP Bypass 지연: <5ms
- 메모리: 통화당 ~10MB

### 알려진 제한사항
- IPv4만 지원 (IPv6 미지원)
- UDP 전송만 지원 (TCP/TLS 미지원)
- 단일 코덱 협상 (transcoding 미지원)

