---
title: 근본 원인 미해결 종합 분석
date: 2026-03-11
type: root_cause_analysis
severity: CRITICAL
status: IDENTIFIED
---

# 근본 원인 미해결 종합 분석

## 🔴 사용자 보고

> "NULL출력이슈와 RTP 문제가 이전과같이 해결되지않았어. 포인트를 못잡는거같은데?"

## 🎯 실제 상황 분석

### 1. 서버 종료 오해

**사용자 인식**: "전화를 수신했더니 stopping_server가 되었다"

**실제 상황**:
```
17:39:50 - INVITE 수신 (전화 시작)
17:40:01 - AI Takeover 시도 (AI 없음)
17:40:32 - 통화 종료 (정상)
17:44:04 - stopping_server (사용자가 Ctrl+C로 서버 종료)
```

✅ **결론**: 서버는 정상 작동. 전화를 받고 통화가 끝난 후 **사용자가 직접 서버 종료**

### 2. AI Orchestrator 여전히 NULL

**로그 증거**:
```json
{"timestamp": "2026-03-11T16:42:53.428", "level": "warning", 
 "event": "🔄 [AI Takeover] AI Orchestrator not available", 
 "call_id": "MUUhqjzS4h"}

{"timestamp": "2026-03-11T17:40:01.004", "level": "warning", 
 "event": "🔄 [AI Takeover] AI Orchestrator not available", 
 "call_id": "QyshVOJ-Cc"}
```

**근본 원인**:
1. **코드 수정이 적용되지 않음** - `ai_voicebot_config` 에러로 서버 시작 실패
2. 이전 버전의 서버가 여전히 실행 중
3. AI 초기화는 성공했지만 **RTP Worker에 전달 안됨**

### 3. NULL 바이트 문제 여전히 존재

**확인 필요**: 로그 파일에 여전히 대량의 NULL 바이트

**원인**:
1. `logger.py` 수정이 적용되지 않음 (서버 재시작 안함)
2. 기존 로그 파일이 이미 NULL로 오염됨

## 🔍 근본 원인 재진단

### 문제 1: AI Orchestrator NULL

**이전 수정들**:
1. ✅ `sip_endpoint.py:287` - `CallManager`에 `ai_orchestrator` 파라미터 추가
2. ✅ `sip_endpoint.py:1702` - `RTPRelayWorker`에 `call_manager.ai_orchestrator` 전달
3. ✅ `main.py:300` - `ai_voicebot_config` 외부 스코프로 이동
4. ✅ `main.py:426-441` - AI 준비 대기 후 SIP 서버 시작

**문제**: 코드는 수정했지만 **서버가 재시작되지 않음**

**검증 방법**:
```bash
# 1. 서버 프로세스 확인
ps aux | grep "python.*src.main"

# 2. 기존 서버 종료
pkill -f "python.*src.main"

# 3. 새 서버 시작
cd sip-pbx
python -m src.main

# 4. AI 준비 확인
tail -f logs/app.log | grep "ai_voicebot_ready"
```

### 문제 2: RTP Skip Invalid Remote

**로그에서 확인 못함**: 이번 로그에는 `rtp_relay_skip_invalid_remote` 없음

**원인**: AI Orchestrator가 NULL이라 RTP 전송 자체가 안일어남

### 문제 3: NULL 바이트 로깅

**근본 원인**: Windows 파일 시스템 + `"w"` 모드 문제

**수정 완료**: `logger.py:142` - `"w"` → `"a"` 모드 변경

**적용 필요**: 
1. 서버 재시작
2. 기존 `app.log` 삭제 또는 백업

## 🚨 왜 "포인트를 못잡는" 것처럼 보이는가?

### 1. 코드 수정 vs 실행 중인 코드

```
코드 수정함 (src/main.py, src/sip_core/sip_endpoint.py, src/common/logger.py)
     ↓
하지만 서버는 재시작 안함
     ↓
실행 중인 코드 = 수정 전 코드
     ↓
문제 여전히 발생
     ↓
"해결되지 않았어"
```

### 2. 순환 참조 문제

```
AI Orchestrator NULL
     ↓
RTP Worker에 NULL 전달
     ↓
AI Takeover 실패
     ↓
오디오 전송 안됨
     ↓
"RTP 문제"로 인식
```

### 3. 로그 파일 오염

```
기존 app.log (2MB, 86% NULL)
     ↓
서버 재시작 안함
     ↓
append 모드 수정 적용 안됨
     ↓
여전히 NULL 바이트
     ↓
"NULL 문제 해결 안됨"
```

## ✅ 완전 해결 방법

### Step 1: 기존 서버 완전 종료

```bash
# Windows
taskkill /F /IM python.exe

# 또는 Ctrl+C로 종료
```

### Step 2: 기존 로그 정리

```bash
cd sip-pbx

# 백업
cp logs/app.log logs/app.log.backup_$(date +%Y%m%d_%H%M%S)

# 삭제
rm logs/app.log

# 또는 빈 파일로 초기화
> logs/app.log
```

### Step 3: 새 서버 시작

```bash
cd sip-pbx
python -m src.main
```

**예상 시퀀스**:
```
1. SIP Endpoint 생성
2. 🚀 AI Voicebot 초기화 중... (최대 60초 대기)
3. ✅ AI Voicebot 준비 완료! (25초)
4. SIP 서버 시작
5. ✅ 서버 준비 완료
```

### Step 4: 검증

```bash
# 1. AI 준비 확인
grep "ai_orchestrator_connected_to_call_manager" logs/app.log

# 2. NULL 바이트 확인
python -c "with open('logs/app.log', 'rb') as f: print(f'NULL: {f.read().count(b\"\\x00\")}')"
# 예상: NULL: 0

# 3. 통화 테스트
# 1003 → 1004 전화
# 예상: AI 인사말 송출

# 4. AI Orchestrator 확인
grep "AI Orchestrator not available" logs/app.log
# 예상: 결과 없음
```

## 🎯 핵심 문제

### 코드는 수정했지만 실행은 안했다

```python
# ✅ 수정 완료
sip-pbx/src/main.py
sip-pbx/src/sip_core/sip_endpoint.py
sip-pbx/src/common/logger.py

# ❌ 적용 안됨
실행 중인 서버 = 이전 버전
```

### 해결책: 서버 재시작!

**중요**: Python은 컴파일 언어가 아니므로 **서버를 재시작해야 코드 변경이 적용됩니다**

---

**작성일**: 2026-03-11  
**상태**: 🔴 **근본 원인 파악 완료, 서버 재시작 필요**
