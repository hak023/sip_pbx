# 🚀 Quick Start Guide

SIP PBX를 5분 안에 실행해보세요!

## 1단계: 설치 (2분)

```powershell
# 저장소 클론
git clone https://github.com/your-org/sip-pbx.git
cd sip-pbx

# 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt
```

## 2단계: 설정 (1분)

```powershell
# 예제 설정 복사
Copy-Item config\config.example.yaml config\config.yaml
```

## 3단계: 실행 (1분)

```powershell
.\start-server.ps1
```

## 4단계: 테스트

### Health Check

```powershell
curl http://localhost:8080/health
```

**예상 응답:**
```json
{
  "status": "healthy",
  "timestamp": "2025-10-27T10:00:00Z"
}
```

### 메트릭 확인

```powershell
curl http://localhost:9090/metrics
```

### 통계 확인

```powershell
curl http://localhost:8080/api/stats
```

## 다음 단계

✅ **성공!** 서버가 실행 중입니다!

### SIP 클라이언트 연결

1. **Softphone 사용** (예: Zoiper, X-Lite, MicroSIP)
   - SIP Server: `localhost:5060`
   - Username: (any)
   - Password: (any)

2. **통화 시작**
   - 두 개의 SIP 클라이언트로 통화 시작
   - 통화 품질 확인

### 이벤트 확인

```powershell
# 실시간 통계
curl http://localhost:8080/api/stats

# CDR 확인
Get-Content .\cdr\cdr-*.jsonl | Select-Object -Last 10
```

## 문제 해결

### 포트 충돌

```powershell
# 다른 포트로 실행
.\start-server.ps1 -Port 5080
```

### 디버그 모드

```powershell
.\start-server.ps1 -LogLevel DEBUG
```

## 더 알아보기

- 📘 [상세 매뉴얼](USER_MANUAL.md)
- 🐛 [디버깅 가이드](DEBUGGING.md)
- 🔧 [B2BUA 상태](B2BUA_STATUS.md)

---

**🎉 축하합니다! SIP PBX가 실행되고 있습니다!**

