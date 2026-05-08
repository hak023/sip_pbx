# 🤖 AI 보이스봇 빠른 시작 가이드

## 📋 개요

이 가이드는 **Gemini 2.5 Flash** 기반 AI 보이스봇을 빠르게 설정하고 실행하는 방법을 안내합니다.

**예상 소요 시간**: 15~20분

---

## ✅ 사전 준비

### 1️⃣ 시스템 요구사항

- ✅ Python 3.11 이상
- ✅ 8GB RAM 권장 (AI 모델 로딩)
- ✅ 10GB 디스크 공간
- ✅ 안정적인 인터넷 연결

### 2️⃣ Google Cloud 계정

- ✅ Google Cloud 계정 (무료 계정 가능)
- ✅ 신용카드 등록 (무료 할당량 내 사용 시 과금 없음)

---

## 🚀 1단계: 프로젝트 설치

### Git Clone

```bash
git clone https://github.com/hak023/sip_pbx.git
cd sip_pbx
```

### 의존성 설치

```bash
# Python 가상환경 생성 (권장)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치 (AI 패키지 포함)
pip install -r requirements.txt
```

**설치 시간**: 약 5~10분 (PyTorch 등 대용량 패키지 포함)

---

## 🔑 2단계: Google Cloud API 설정

### 2-1. Google AI Studio에서 API 키 발급

1. **Google AI Studio** 접속
   - URL: https://aistudio.google.com/app/apikey

2. **API 키 생성**
   - "Create API Key" 버튼 클릭
   - 프로젝트 선택 (또는 새 프로젝트 생성)
   - API 키 복사 (예: `AIzaSyAaBbCcDdEeFfGgHhIiJjKk...`)

3. **무료 할당량 확인**
   - Gemini 2.5 Flash: 일 1,500 요청 무료
   - 소규모 서비스는 무료로 충분!

### 2-2. Google Cloud Console에서 Service Account 생성

1. **Google Cloud Console** 접속
   - URL: https://console.cloud.google.com/

2. **프로젝트 생성** (없는 경우)
   - 상단 프로젝트 선택 → "New Project"
   - 프로젝트 이름: `sip-pbx-ai` (예시)

3. **API 활성화**
   - Navigation Menu → "APIs & Services" → "Library"
   - 검색 후 활성화:
     - ✅ Cloud Speech-to-Text API
     - ✅ Cloud Text-to-Speech API

4. **Service Account 생성**
   - Navigation Menu → "IAM & Admin" → "Service Accounts"
   - "Create Service Account" 클릭
   - 이름: `sip-pbx-ai-sa` (예시)
   - 역할: "Cloud Speech Administrator", "Cloud Speech Client"

5. **키 생성 및 다운로드**
   - Service Account 클릭 → "Keys" 탭
   - "Add Key" → "Create new key" → JSON 선택
   - 다운로드된 JSON 파일을 `credentials/gcp-key.json`에 저장

```bash
# credentials 디렉토리 생성
mkdir -p credentials

# 다운로드한 키 파일을 credentials로 복사
cp ~/Downloads/sip-pbx-ai-sa-*.json credentials/gcp-key.json

# 권한 설정 (Linux/Mac)
chmod 600 credentials/gcp-key.json
```

---

## ⚙️ 3단계: 환경 변수 설정

### .env 파일 생성

```bash
# env.example을 .env로 복사
cp env.example .env
```

### .env 파일 수정

```bash
# .env 파일을 편집기로 열기
nano .env  # 또는 code .env, vim .env
```

**필수 항목만 설정:**

```bash
# Google Cloud 프로젝트 ID
GCP_PROJECT_ID=sip-pbx-ai  # 실제 프로젝트 ID로 변경

# Service Account 키 파일 경로
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json

# Gemini API 키 (2-1에서 발급한 키)
GEMINI_API_KEY=AIzaSyAaBbCcDdEeFfGgHhIiJjKk...  # 실제 키로 변경

# 로그 레벨 (선택)
LOG_LEVEL=INFO
```

**저장 후 종료**

---

## 🎛️ 4단계: 설정 파일 확인

### config/config.yaml 확인

AI 보이스봇 설정이 이미 최적화되어 있습니다:

```yaml
ai_voicebot:
  enabled: true  # AI 기능 활성화
  no_answer_timeout: 10  # 10초 후 AI 자동 응답
  
  google_cloud:
    gemini:
      model: "gemini-2.5-flash"  # ⚡ 최신 Flash 모델 (빠르고 저렴)
      temperature: 0.5
      max_output_tokens: 150  # 1~2문장 답변
```

**기본 설정 그대로 사용 권장** (필요 시 나중에 튜닝)

---

## 🏃 5단계: 실행

### 서버 시작

```bash
python src/main.py
```

**성공 시 출력:**

```
[INFO] SIP PBX starting...
[INFO] AI Voicebot enabled
[INFO] Loading Sentence Transformers model...
[INFO] ChromaDB initialized
[INFO] SIP endpoint listening on 0.0.0.0:5060
[INFO] HTTP server listening on 0.0.0.0:8080
[INFO] System ready!
```

### 헬스체크 확인

새 터미널에서:

```bash
curl http://localhost:8080/health
```

**응답 예시:**

```json
{
  "status": "healthy",
  "uptime_seconds": 123.45,
  "active_calls": 0,
  "ai_voicebot_enabled": true,
  "gemini_model": "gemini-1.5-flash"
}
```

---

## 📞 6단계: 테스트

### 테스트 시나리오

1. **SIP 전화기에서 전화 걸기**
   - 착신자: `sip:1234@<서버IP>:5060`
   - 발신자: 임의의 SIP URI

2. **10초 대기**
   - 착신자가 응답하지 않으면 AI 자동 활성화
   - 로그에서 확인: `[INFO] AI mode activated for call_id=...`

3. **AI와 대화**
   - "안녕하세요" → AI가 응답
   - "영업시간이 언제인가요?" → RAG 검색 후 응답
   - "감사합니다" → AI가 마무리

### 로그 확인

```bash
# 실시간 로그 보기
tail -f logs/app.log | jq .

# AI 관련 로그만 필터링
tail -f logs/app.log | jq 'select(.event | contains("ai"))'

# 응답 시간 확인
tail -f logs/app.log | jq 'select(.event == "ai_response_time_breakdown")'
```

**예상 응답 시간:**

```json
{
  "event": "ai_response_time_breakdown",
  "rag_search_ms": 75.2,
  "llm_generation_ms": 412.8,
  "tts_first_chunk_ms": 235.1,
  "total_response_ms": 923.5
}
```

**약 0.9초 응답!** ⚡

---

## 📊 7단계: 모니터링

### Prometheus 메트릭

브라우저에서 접속:

```
http://localhost:9090
```

**주요 메트릭:**

- `ai_response_time_seconds` - AI 응답 시간
- `llm_generation_time_seconds` - LLM 생성 시간
- `rag_search_time_seconds` - RAG 검색 시간
- `active_ai_sessions` - 활성 AI 세션 수

### CDR (통화 기록)

```bash
# 최근 통화 10건 조회
tail -n 10 cdr/cdr-$(date +%Y-%m-%d).jsonl | jq .

# AI가 응답한 통화만 필터링
cat cdr/cdr-*.jsonl | jq 'select(.is_ai_handled == true)'
```

---

## 💰 비용 확인

### Google Cloud Console

1. **Billing** 페이지 접속
   - https://console.cloud.google.com/billing

2. **비용 보고서** 확인
   - "Reports" 탭
   - 서비스별 비용 확인:
     - Speech-to-Text
     - Text-to-Speech
     - Generative AI (Gemini)

### 예상 비용 (월 100통 기준)

```
┌─────────────────────────────────────────┐
│  Gemini 1.5 Flash                        │
│  - 입력:  $0.56                          │
│  - 출력:  $0.45                          │
│  ────────────────────────────────────   │
│  총액: 약 ₩1,400/월                     │
│                                          │
│  STT + TTS: 약 ₩5,000/월 (추가)        │
│  ────────────────────────────────────   │
│  전체 비용: 약 ₩6,400/월 ✨             │
└─────────────────────────────────────────┘
```

**일 50통 미만은 무료 할당량으로 충분!**

---

## 🎨 8단계: 커스터마이징

### AI 응답 개인화

`config/config.yaml` 수정:

```yaml
ai_voicebot:
  gemini:
    system_prompt: |
      당신은 [회사명]의 AI 비서입니다.
      규칙:
      1. 친근하고 전문적인 톤으로 답변
      2. 회사 정보는 정확하게 전달
      3. 모르는 내용은 "담당자에게 연결하겠습니다"
```

### 지식 베이스 추가

```python
# scripts/add_knowledge.py
from src.ai_voicebot.knowledge.chromadb_client import ChromaDBClient
from src.ai_voicebot.knowledge.embedder import TextEmbedder

async def add_knowledge():
    embedder = TextEmbedder()
    db = ChromaDBClient()
    
    # FAQ 추가
    knowledge = [
        {
            "text": "영업시간은 평일 9시부터 6시까지입니다.",
            "category": "영업시간",
            "owner": "company"
        },
        {
            "text": "주소는 서울시 강남구 테헤란로 123입니다.",
            "category": "주소",
            "owner": "company"
        }
    ]
    
    for item in knowledge:
        embedding = await embedder.embed_single(item["text"])
        await db.upsert(
            doc_id=f"faq_{item['category']}",
            embedding=embedding,
            text=item["text"],
            metadata=item
        )

# 실행
import asyncio
asyncio.run(add_knowledge())
```

### 음성 변경

`config/config.yaml`:

```yaml
ai_voicebot:
  google_cloud:
    tts:
      voice_name: "ko-KR-Neural2-B"  # A, B, C 중 선택
      speaking_rate: 1.1  # 10% 빠르게
      pitch: 0.0
```

**음성 샘플 듣기**: https://cloud.google.com/text-to-speech/docs/voices

---

## 🐛 트러블슈팅

### 문제 1: "API key not valid"

**원인**: Gemini API 키가 잘못되었거나 만료됨

**해결**:
```bash
# .env 파일 확인
cat .env | grep GEMINI_API_KEY

# API 키 재발급
# https://aistudio.google.com/app/apikey
```

### 문제 2: "Permission denied" (Service Account)

**원인**: Service Account 권한 부족

**해결**:
1. Google Cloud Console → IAM
2. Service Account에 다음 역할 추가:
   - "Cloud Speech Administrator"
   - "Cloud Text-to-Speech User"

### 문제 3: "Model loading failed" (Sentence Transformers)

**원인**: 인터넷 연결 또는 디스크 공간 부족

**해결**:
```bash
# 모델 수동 다운로드
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')"

# 디스크 공간 확인 (10GB 필요)
df -h
```

### 문제 4: 응답 시간이 너무 느림 (>2초)

**원인**: 네트워크 지연 또는 설정 문제

**해결**:
```yaml
# config.yaml 최적화
ai_voicebot:
  gemini:
    max_output_tokens: 100  # 150 → 100으로 줄이기
    temperature: 0.3  # 0.5 → 0.3으로 낮추기
  
  rag:
    top_k: 2  # 3 → 2로 줄이기
```

### 문제 5: 비용이 예상보다 많이 나옴

**원인**: 무료 할당량 초과 또는 설정 오류

**해결**:
```yaml
# config.yaml에 비용 제한 설정
ai_voicebot:
  google_cloud:
    quota_management:
      daily_request_limit: 100  # 일 100통으로 제한
      cost_alert_threshold_usd: 10  # $10 초과 시 알림
      auto_throttle_enabled: true  # 자동 제한
```

---

## 📚 다음 단계

### 추가 학습

1. **아키텍처 이해**
   - [AI 보이스봇 아키텍처](../architecture/ai-voicebot-architecture.md)

2. **성능 최적화**
   - [AI 응답 시간 분석](../analysis/ai-response-time-analysis.md)

3. **비용 최적화**
   - [Gemini 모델 비교](gemini-model-comparison.md)

### 프로덕션 배포

1. **보안 강화**
   - TLS/SRTP 활성화
   - API 키 암호화
   - Webhook 서명 검증

2. **스케일링**
   - Kubernetes 배포
   - Pinecone Vector DB 전환
   - Redis 캐싱

3. **모니터링 확장**
   - Grafana 대시보드
   - Sentry 에러 추적
   - CloudWatch 알림

### 커뮤니티

- 📧 **이슈 보고**: https://github.com/hak023/sip_pbx/issues
- 💬 **토론**: https://github.com/hak023/sip_pbx/discussions
- 📖 **문서**: https://github.com/hak023/sip_pbx/wiki

---

## ✅ 체크리스트

완료 여부를 확인하세요:

- [ ] Python 3.11+ 설치
- [ ] requirements.txt 의존성 설치
- [ ] Google AI Studio에서 Gemini API 키 발급
- [ ] Google Cloud Console에서 Service Account 생성
- [ ] STT/TTS API 활성화
- [ ] .env 파일 설정 (GCP_PROJECT_ID, GEMINI_API_KEY)
- [ ] credentials/gcp-key.json 배치
- [ ] 서버 실행 (`python src/main.py`)
- [ ] 헬스체크 확인 (`curl http://localhost:8080/health`)
- [ ] 테스트 통화 (10초 대기 후 AI 응답)
- [ ] 로그에서 응답 시간 확인 (~0.9초)
- [ ] Prometheus 메트릭 확인
- [ ] CDR 기록 확인

**모두 완료했다면 축하합니다! 🎉**

당신의 AI 보이스봇이 이제 실시간 통화를 처리할 준비가 되었습니다!

---

## 🆘 도움이 필요하신가요?

**빠른 답변이 필요하면:**
1. [FAQ 문서](../architecture/ai-voicebot-architecture.md#faq) 확인
2. [트러블슈팅 가이드](DEBUGGING.md) 참조
3. [GitHub Issues](https://github.com/hak023/sip_pbx/issues) 검색

**버그 발견 시:**
- Issue 템플릿을 사용하여 보고
- 로그 파일 첨부 (`logs/app.log`)
- 재현 단계 상세히 기술

**기능 제안:**
- Discussions에 아이디어 공유
- 커뮤니티 피드백 수렴
- Pull Request 환영!

---

**Happy Coding! 🚀**

