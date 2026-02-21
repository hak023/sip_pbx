# Google Cloud API 설정 가이드

## 📍 설정 위치

### 1. 메인 설정 파일: `config/config.yaml`

```yaml
ai_voicebot:
  google_cloud:
    project_id: "your-gcp-project-id"  # ← 여기에 GCP 프로젝트 ID
    credentials_path: "credentials/gcp-key.json"  # ← Service Account 키 경로
    
    stt:
      model: "telephony"
      language_code: "ko-KR"
    
    tts:
      voice_name: "ko-KR-Neural2-A"
      speaking_rate: 1.0
    
    gemini:
      model: "gemini-2.5-flash"
      temperature: 0.7
```

### 2. 환경 변수: `env.example` → `.env`

```bash
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json
GEMINI_API_KEY=your-gemini-api-key
```

---

## 🚀 Google Cloud 설정 단계

### Step 1: Google Cloud 프로젝트 생성

1. **Google Cloud Console 접속**
   ```
   https://console.cloud.google.com/
   ```

2. **프로젝트 생성**
   - 상단 "프로젝트 선택" → "새 프로젝트"
   - 프로젝트 이름: `sip-pbx-ai` (예시)
   - 조직: 선택 (선택사항)
   - **프로젝트 ID 복사** → `config/config.yaml`의 `project_id`에 입력

3. **결제 계정 연결**
   - 좌측 메뉴 → "결제"
   - 결제 계정 생성/연결

### Step 2: API 활성화

```bash
# gcloud CLI 설치 후 (https://cloud.google.com/sdk/docs/install)

# 프로젝트 설정
gcloud config set project YOUR_PROJECT_ID

# 필요한 API 활성화
gcloud services enable speech.googleapis.com
gcloud services enable texttospeech.googleapis.com
gcloud services enable generativelanguage.googleapis.com
```

**또는 Console에서:**
1. "API 및 서비스" → "라이브러리"
2. 검색 후 활성화:
   - Cloud Speech-to-Text API
   - Cloud Text-to-Speech API
   - Generative Language API (Gemini)

### Step 3: Service Account 생성

#### Option A: gcloud CLI

```bash
# Service Account 생성
gcloud iam service-accounts create sip-pbx-ai-sa \
  --display-name="SIP PBX AI Service Account"

# 권한 부여
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:sip-pbx-ai-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/speech.client"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:sip-pbx-ai-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/texttospeech.client"

# 키 생성 (JSON)
gcloud iam service-accounts keys create credentials/gcp-key.json \
  --iam-account=sip-pbx-ai-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

#### Option B: Console에서

1. **Service Account 생성**
   - "IAM 및 관리자" → "서비스 계정"
   - "서비스 계정 만들기"
   - 이름: `sip-pbx-ai-sa`
   - 설명: "SIP PBX AI Service Account"

2. **권한 부여**
   - 역할 추가:
     - `Cloud Speech-to-Text API 사용자`
     - `Cloud Text-to-Speech API 사용자`
     - `Generative AI API 사용자`

3. **키 생성**
   - 생성된 Service Account 클릭
   - "키" 탭 → "키 추가" → "새 키 만들기"
   - JSON 선택 → 다운로드
   - **파일을 `sip-pbx/credentials/gcp-key.json`에 저장**

### Step 4: Gemini API 키 발급 (선택)

generativeai SDK 사용 시:

1. **Google AI Studio 접속**
   ```
   https://makersuite.google.com/app/apikey
   ```

2. **API 키 생성**
   - "Create API Key" 클릭
   - 프로젝트 선택
   - API 키 복사 → `.env` 파일의 `GEMINI_API_KEY`에 저장

### Step 5: 설정 파일 업데이트

#### `config/config.yaml` 수정

```yaml
ai_voicebot:
  google_cloud:
    project_id: "sip-pbx-ai-prod"  # ← 실제 프로젝트 ID
    credentials_path: "credentials/gcp-key.json"  # ← 키 파일 경로
```

#### `.env` 파일 생성

```bash
# env.example을 .env로 복사
cp env.example .env

# .env 파일 편집
nano .env  # 또는 메모장
```

```bash
# .env 파일 내용
GCP_PROJECT_ID=sip-pbx-ai-prod
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json
GEMINI_API_KEY=AIzaSyAaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPp
```

### Step 6: 인증 테스트

```python
# test_google_auth.py
import os
from google.cloud import speech, texttospeech
import google.generativeai as genai

# 환경 변수 로드
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "./credentials/gcp-key.json"

# STT 테스트
try:
    stt_client = speech.SpeechClient()
    print("✅ STT 인증 성공")
except Exception as e:
    print(f"❌ STT 인증 실패: {e}")

# TTS 테스트
try:
    tts_client = texttospeech.TextToSpeechClient()
    print("✅ TTS 인증 성공")
except Exception as e:
    print(f"❌ TTS 인증 실패: {e}")

# Gemini 테스트
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    print("✅ Gemini 인증 성공")
except Exception as e:
    print(f"❌ Gemini 인증 실패: {e}")
```

```bash
python test_google_auth.py
```

---

## 📋 설정 요약

### 필수 설정

| 항목 | 파일 | 키 | 설명 |
|-----|------|-----|------|
| 프로젝트 ID | `config/config.yaml` | `ai_voicebot.google_cloud.project_id` | GCP 프로젝트 ID |
| 인증 키 경로 | `config/config.yaml` | `ai_voicebot.google_cloud.credentials_path` | Service Account 키 파일 |
| 프로젝트 ID | `.env` | `GCP_PROJECT_ID` | 환경 변수 (옵션) |
| 인증 키 경로 | `.env` | `GOOGLE_APPLICATION_CREDENTIALS` | 환경 변수 (권장) |

### 선택 설정

| 항목 | 파일 | 키 | 설명 |
|-----|------|-----|------|
| Gemini API 키 | `.env` | `GEMINI_API_KEY` | generativeai SDK 사용 시 |

---

## 💰 비용 관리

### 무료 티어

- **STT**: 월 60분 무료
- **TTS**: 월 100만 문자 무료 (Standard), 10만 문자 (Neural2)
- **Gemini**: 60 requests/minute 무료

### 예상 비용 (월 1000 통화, 평균 3분)

```
STT:  1000 * 3분 = 3000분
      무료 60분 제외 = 2940분
      $0.006 / 15초 = $0.024 / 분
      2940 * $0.024 = $70.56

TTS:  1000 * 100자 = 100,000자
      무료 100,000자 (Standard) = $0
      또는 Neural2: $16 / 1M = $1.6

Gemini: 1000 * 500자 = 500,000자
      무료 또는 $0.00025 / 1K = $0.125

총계: 약 $70 - $72 / 월
```

### 비용 절약 팁

1. **Quota 설정**
   ```yaml
   quota_management:
     daily_request_limit: 100  # 일일 제한
     cost_alert_threshold_usd: 50  # 알람
   ```

2. **STT 모델 선택**
   - `telephony`: 전화 음성 최적화 (권장)
   - `latest_long`: 긴 오디오 (비용 동일)

3. **TTS 음성 선택**
   - `Standard`: 무료 티어 많음
   - `Neural2`: 고품질, 유료

---

## 🔒 보안

### 1. 인증 키 보호

```bash
# credentials 디렉토리는 .gitignore에 추가됨
echo "credentials/" >> .gitignore
echo ".env" >> .gitignore

# 파일 권한 설정 (Linux/Mac)
chmod 600 credentials/gcp-key.json
chmod 600 .env
```

### 2. Service Account 권한 최소화

```bash
# 필요한 권한만 부여 (Least Privilege)
roles/speech.client  # STT
roles/texttospeech.client  # TTS
roles/generativeai.user  # Gemini
```

### 3. API 키 로테이션

- Service Account 키: 90일마다 교체 권장
- Gemini API 키: 필요 시 재생성

---

## ❓ 문제 해결

### 인증 실패

```
google.auth.exceptions.DefaultCredentialsError
```

**해결:**
1. `GOOGLE_APPLICATION_CREDENTIALS` 환경 변수 확인
2. 키 파일 경로 확인
3. 키 파일 JSON 형식 유효성 확인

### API 비활성화

```
google.api_core.exceptions.PermissionDenied: 403
```

**해결:**
1. Google Cloud Console → "API 및 서비스" → "라이브러리"
2. 해당 API 검색 후 활성화

### Quota 초과

```
google.api_core.exceptions.ResourceExhausted: 429
```

**해결:**
1. Google Cloud Console → "IAM 및 관리자" → "할당량"
2. 할당량 증가 요청 또는 요청 제한 설정

---

## 📞 지원

- Google Cloud 지원: https://cloud.google.com/support
- Gemini API 문서: https://ai.google.dev/docs
- SIP PBX 이슈: https://github.com/hak023/sip_pbx/issues

