# 🔑 Gemini API 키 설정 가이드

## 1. Gemini API 키 발급

1. 브라우저에서 https://aistudio.google.com/app/apikey 접속
2. Google 계정으로 로그인
3. **"Create API key"** 버튼 클릭
4. 생성된 API 키를 복사 (예: `AIzaSyAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp`)

---

## 2. API 키 설정 방법

### ✅ 방법 1: `.env` 파일 사용 (권장)

**프로젝트 루트**에 있는 `.env` 파일을 열어서 다음 줄을 수정합니다:

**파일 경로**: `c:\work\workspace_sippbx\sip-pbx\.env`

```env
# 이 줄을 찾아서 수정
GEMINI_API_KEY=your-gemini-api-key-here

# 발급받은 API 키로 변경 (예시)
GEMINI_API_KEY=AIzaSyAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp
```

**장점**:
- ✅ 안전 (Git에 커밋되지 않음)
- ✅ 영구적 (재부팅 후에도 유지)
- ✅ 프로젝트별로 다른 키 사용 가능

---

### 방법 2: PowerShell 환경 변수 (임시)

PowerShell에서 직접 환경 변수를 설정합니다.

```powershell
# 현재 PowerShell 세션에만 적용 (재부팅하면 사라짐)
$env:GEMINI_API_KEY="AIzaSyAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp"
```

**단점**:
- ❌ PowerShell을 닫으면 사라짐
- ❌ 테스트용으로만 적합

---

### ⚠️ 방법 3: config.yaml 파일 (권장하지 않음)

보안상 권장하지 않지만, 테스트 목적으로는 가능합니다.

**파일 경로**: `c:\work\workspace_sippbx\sip-pbx\config\config.yaml`

```yaml
# 파일 끝에 추가 (또는 기존 항목 수정)
google_cloud:
  gemini:
    api_key: "AIzaSyAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp"  # 여기에 API 키 입력
```

**⚠️ 주의사항**:
- Git에 커밋하면 API 키가 노출됩니다
- 프로덕션 환경에서는 절대 사용하지 마세요

---

## 3. 설정 확인

API 키 설정 후, 다음 명령어로 테스트합니다:

```powershell
# 프로젝트 루트에서
cd c:\work\workspace_sippbx\sip-pbx
python tests/test_google_auth.py
```

**성공 시 출력 예시**:

```
================================================================================
  Google Cloud 인증 및 API 테스트
================================================================================

[OK] Service Account 키 파일 발견: config/gcp-key.json
[OK] Speech-to-Text 클라이언트 생성 성공
[OK] Text-to-Speech 클라이언트 생성 성공
[OK] Gemini API 키 발견: AIzaSyAaBbCcDdEeFfGg...

[OK] 인증 테스트: 성공

================================================================================
  2. Speech-to-Text (STT) API 테스트
================================================================================

[OK] STT 클라이언트 생성 성공
[OK] STT API 연결 성공

================================================================================
  3. Text-to-Speech (TTS) API 테스트
================================================================================

[OK] TTS 클라이언트 생성 성공
[OK] TTS 음성 합성 성공
[OK] 테스트 오디오 저장: ./test_outputs/tts_test_20260105_185730.wav

================================================================================
  4. Gemini LLM API 테스트
================================================================================

[OK] Gemini API 키 설정 완료
[OK] Gemini 모델 생성: gemini-1.5-flash

Gemini 응답:
   안녕하세요, 저는 Gemini입니다. 대규모 언어 모델로, 다양한 작업을 도와드릴 수 있습니다.

[OK] 응답 시간: 650ms
[OK] 추정 토큰 수: ~120 토큰
[OK] 추정 비용: $0.000045 (이번 호출)

================================================================================
  전체 테스트 결과 요약
================================================================================

총 테스트: 4
[OK] 성공: 4
[FAIL] 실패: 0

모든 테스트가 성공했습니다!
Google Cloud API가 정상적으로 작동하고 있습니다.
```

---

## 4. 무료 할당량 확인

### Gemini 1.5 Flash 무료 할당량

- **무료 요청 수**: 일 1,500 요청
- **무료 토큰 수**: 월 200만 토큰

### 무료 범위 내 사용 예시

| 통화 수 | 평균 토큰/통화 | 월간 총 토큰 | 비용 |
|---------|---------------|-------------|------|
| 100통화 | 500 토큰 | 50,000 | **무료** ✅ |
| 500통화 | 500 토큰 | 250,000 | **무료** ✅ |
| 1,000통화 | 500 토큰 | 500,000 | **무료** ✅ |
| 5,000통화 | 500 토큰 | 2,500,000 | ~$0.19 💰 |

소규모 서비스는 **완전 무료**로 사용 가능합니다!

---

## 5. 문제 해결

### 문제: "GEMINI_API_KEY 환경 변수가 설정되지 않았습니다"

**해결 방법**:
1. `.env` 파일에 API 키를 올바르게 입력했는지 확인
2. `.env` 파일이 프로젝트 루트에 있는지 확인
3. PowerShell을 재시작한 후 다시 시도

### 문제: "API key not valid. Please pass a valid API key."

**해결 방법**:
1. API 키를 다시 복사해서 붙여넣기 (공백 제거)
2. https://aistudio.google.com/app/apikey 에서 새 키 발급
3. API 키가 활성화되었는지 확인 (발급 직후는 몇 분 소요)

### 문제: "Quota exceeded"

**해결 방법**:
1. 무료 할당량 초과 여부 확인
2. https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas 에서 할당량 확인
3. 결제 정보 등록 (유료 사용 필요 시)

---

## 6. 보안 주의사항

### ✅ DO (해야 할 것)

- `.env` 파일에 API 키 저장
- `.gitignore`에 `.env` 포함 (이미 설정됨)
- 정기적으로 API 키 교체
- API 키별 사용량 모니터링

### ❌ DON'T (하지 말아야 할 것)

- Git에 API 키 커밋
- 공개 저장소에 API 키 업로드
- 소스 코드에 직접 하드코딩
- 다른 사람과 API 키 공유

---

## 7. 추가 문의

문제가 계속되면 다음을 확인하세요:

1. **Google Cloud Console**: https://console.cloud.google.com/
2. **Gemini API 문서**: https://ai.google.dev/
3. **할당량 확인**: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

---

**작성일**: 2026-01-05  
**문서 버전**: 1.0

