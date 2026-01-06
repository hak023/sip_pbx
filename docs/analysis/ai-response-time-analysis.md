# AI 보이스봇 응답 시간 분석

## 📊 전체 응답 시간 예상치

사용자 발화 종료 → AI 응답 시작까지의 예상 시간을 단계별로 분석합니다.

---

## 🔄 응답 처리 파이프라인

```
[사용자 발화 종료]
    ↓
[1] STT 최종 결과 수신 (Google Cloud Speech-to-Text)
    ↓
[2] VAD 처리 및 내부 버퍼 처리
    ↓
[3] RAG 검색 (Vector DB 유사도 검색)
    ↓
[4] LLM 응답 생성 (Google Gemini)
    ↓
[5] TTS 오디오 생성 시작 (Google Cloud TTS)
    ↓
[6] 첫 번째 오디오 청크 RTP 전송
    ↓
[AI 응답 시작]
```

---

## ⏱️ 단계별 예상 시간

### 1️⃣ STT 최종 결과 수신 (100~300ms)

**Google Cloud Speech-to-Text Streaming API**

- **일반적인 경우**: 150~250ms
- **최적 조건 (짧은 발화)**: 100~150ms
- **지연 조건 (긴 발화, 네트워크 지연)**: 250~300ms

**영향 요인:**
- 사용자 발화 길이 (짧을수록 빠름)
- 네트워크 지연 (한국 → Google Cloud US/Asia 리전)
- Telephony 모델 사용 (전화 품질 오디오 최적화)
- VAD 감지 정확도 (발화 종료 인식)

**설정값 (config.yaml):**
```yaml
google_cloud:
  stt:
    model: "telephony"           # 전화 품질 최적화
    language_code: "ko-KR"
    sample_rate: 16000
    enable_automatic_punctuation: true
```

**예상 시간: 150ms (평균)**

---

### 2️⃣ VAD 및 내부 버퍼 처리 (10~30ms)

**WebRTC VAD + Audio Buffer**

- **VAD 프레임 처리**: 10ms
- **Jitter Buffer 지연**: 60ms (설정값)
- **내부 큐 처리**: 5~10ms

**설정값:**
```yaml
vad:
  aggressiveness: 3              # 0-3, 3이 가장 민감
  frame_duration_ms: 30          # 10, 20, 30
```

**최적화:**
- VAD는 STT와 병렬로 실행되므로 추가 지연 없음
- Jitter Buffer는 STT 스트리밍 중에 이미 처리됨

**예상 시간: ~0ms (병렬 처리)**

---

### 3️⃣ RAG 검색 (50~150ms)

**Vector DB 유사도 검색 + 재순위화**

- **텍스트 임베딩 생성**: 20~50ms
  - Sentence Transformers (로컬 모델)
  - 모델: `all-MiniLM-L6-v2` (384차원)
  
- **Vector DB 검색**: 20~50ms
  - ChromaDB (개발): 10~30ms (로컬 디스크)
  - Pinecone (프로덕션): 30~50ms (네트워크 API)
  
- **재순위화 (선택)**: 10~50ms
  - 키워드 매칭
  - 문서 길이 조정

**설정값:**
```yaml
vector_db:
  provider: "chromadb"           # 또는 "pinecone"
  top_k: 3                       # 검색할 문서 수
  similarity_threshold: 0.7
  reranking_enabled: false       # true일 경우 +10~50ms
```

**예상 시간:**
- ChromaDB (개발): 50~80ms
- Pinecone (프로덕션): 70~120ms
- **평균: 80ms**

---

### 4️⃣ LLM 응답 생성 (500~1500ms)

**Google Gemini Pro API**

- **짧은 응답 (1~2문장)**: 500~800ms
- **중간 응답 (3~5문장)**: 800~1200ms
- **긴 응답 (6문장 이상)**: 1200~1500ms

**영향 요인:**
- 생성할 텍스트 길이 (`max_tokens`)
- 컨텍스트 길이 (대화 히스토리 + RAG 문서)
- Gemini API 리전 및 부하
- Temperature 설정 (낮을수록 빠름)

**설정값:**
```yaml
gemini:
  model: "gemini-pro"
  temperature: 0.7               # 0.3~0.5로 낮추면 +10~20% 속도 향상
  max_tokens: 200                # 토큰 수 제한 (짧을수록 빠름)
  top_p: 1.0
  top_k: 1
```

**최적화 전략:**
1. **max_tokens 제한**: 200 토큰 (약 1~2문장)
2. **시스템 프롬프트 최적화**: "1~2문장으로 간결하게 답변"
3. **대화 히스토리 제한**: 최근 10턴만 유지
4. **컨텍스트 문서 제한**: top_k=3

**예상 시간:**
- 최적화된 짧은 응답: 500~700ms
- **평균: 800ms**

---

### 5️⃣ TTS 오디오 생성 시작 (200~400ms)

**Google Cloud Text-to-Speech API**

- **API 호출 지연**: 100~200ms
- **첫 번째 오디오 청크 생성**: 100~200ms

**영향 요인:**
- 응답 텍스트 길이
- TTS 모델 (Neural2 모델 사용)
- 네트워크 지연

**설정값:**
```yaml
tts:
  voice_name: "ko-KR-Neural2-A"  # 자연스러운 음성
  speaking_rate: 1.0             # 말하기 속도
  pitch: 0.0
  volume_gain_db: 0.0
```

**스트리밍 특성:**
- TTS는 전체 오디오 생성 완료 전에 스트리밍 시작 가능
- 첫 번째 청크(4KB)만 생성되면 재생 시작
- 사용자는 전체 생성 완료를 기다리지 않음

**예상 시간: 250ms (첫 청크 생성)**

---

### 6️⃣ RTP 전송 및 재생 시작 (~50ms)

**RTP Relay + 네트워크 전송**

- **RTP 패킷 생성**: 5~10ms
- **네트워크 전송 지연**: 20~40ms (로컬 네트워크)
- **Caller 측 지터 버퍼**: 20~60ms

**예상 시간: 50ms**

---

## 📈 전체 응답 시간 요약

### ⚡ 최적 조건 (Best Case)
```
STT 최종 결과:        100ms
VAD/버퍼:              0ms (병렬)
RAG 검색:             50ms
LLM 응답:            500ms
TTS 첫 청크:         200ms
RTP 전송:             30ms
─────────────────────────
합계:                880ms (~0.9초)
```

### 🎯 일반적인 경우 (Average Case)
```
STT 최종 결과:        150ms
VAD/버퍼:              0ms (병렬)
RAG 검색:             80ms
LLM 응답:            800ms
TTS 첫 청크:         250ms
RTP 전송:             50ms
─────────────────────────
합계:               1330ms (~1.3초)
```

### 🐌 최악 조건 (Worst Case)
```
STT 최종 결과:        300ms
VAD/버퍼:              0ms (병렬)
RAG 검색:            150ms
LLM 응답:           1500ms
TTS 첫 청크:         400ms
RTP 전송:             80ms
─────────────────────────
합계:               2430ms (~2.4초)
```

---

## 🎯 성능 목표 및 최적화

### 사용자 경험 관점

**응답 시간 기준 (심리학 연구):**
- **0.1초 이하**: 즉각 반응 (인식 불가)
- **0.1~1.0초**: 약간의 지연 (자연스러움)
- **1.0~3.0초**: 명확한 지연 (수용 가능)
- **3.0초 이상**: 시스템 느림 (불편함)

**AI 보이스봇 응답 시간:**
- ✅ **1.3초 (평균)**: 자연스러운 대화 수준
- ⚠️ **2.4초 (최악)**: 수용 가능하지만 개선 필요

### 🚀 최적화 전략

#### 1. LLM 응답 속도 개선 (500ms 단축)

**A. 모델 변경:**
```yaml
gemini:
  model: "gemini-1.5-flash"      # gemini-pro보다 2~3배 빠름
  max_tokens: 150                # 200 → 150 (짧은 응답)
  temperature: 0.5               # 0.7 → 0.5 (더 결정론적)
```

**B. 스트리밍 생성 (향후 지원 시):**
- LLM이 토큰을 생성하는 즉시 TTS로 전송
- 전체 응답 완료를 기다리지 않음
- 예상 절감: 300~500ms

**C. 프롬프트 최적화:**
```python
system_prompt = """
당신은 전화 응대 AI입니다.
규칙:
1. 1문장으로 답변 (최대 20단어)
2. 불필요한 인사말 생략
3. 핵심만 간결하게
"""
```

#### 2. RAG 검색 최적화 (30ms 단축)

**A. 캐싱:**
```python
# 자주 묻는 질문(FAQ) 캐싱
faq_cache = {
    "영업시간": "평일 9시부터 6시까지입니다.",
    "주소": "서울시 강남구 테헤란로 123입니다."
}
```

**B. Vector DB 인덱스 최적화:**
```yaml
vector_db:
  chromadb:
    persist_directory: "./data/chromadb"
    # SSD 사용 권장
```

#### 3. TTS 생성 최적화 (50ms 단축)

**A. 음성 설정:**
```yaml
tts:
  speaking_rate: 1.1             # 1.0 → 1.1 (10% 빠르게)
  # 청크 크기 조정으로 첫 청크 더 빠르게 생성
```

**B. 병렬 처리:**
```python
# LLM 생성과 TTS 요청을 병렬로
asyncio.gather(
    llm.generate_response(...),
    tts.prepare_synthesis(...)   # 음성 엔진 준비
)
```

#### 4. 네트워크 최적화 (20ms 단축)

**A. 리전 선택:**
- Google Cloud Asia 리전 사용 (서울 → 도쿄)
- 네트워크 지연 감소

**B. 연결 재사용:**
```python
# gRPC 연결 풀링
# HTTP/2 keep-alive
```

---

## 📊 최적화 후 예상 시간

### 🎯 최적화 적용 시 (Optimized Case)
```
STT 최종 결과:        120ms  (↓30ms, 네트워크 최적화)
VAD/버퍼:              0ms
RAG 검색:             50ms  (↓30ms, 캐싱)
LLM 응답:            400ms  (↓400ms, Flash 모델)
TTS 첫 청크:         180ms  (↓70ms, 병렬 처리)
RTP 전송:             30ms  (↓20ms, 네트워크)
─────────────────────────
합계:                780ms (~0.8초) ✨
```

**개선율: 41% (1330ms → 780ms)**

---

## 🔍 실제 측정 방법

### 코드 계측 (Instrumentation)

```python
# src/ai_voicebot/orchestrator.py

import time
import structlog

logger = structlog.get_logger(__name__)

class AIOrchestrator:
    async def _generate_and_speak_response(self, user_text: str):
        # 전체 시작 시간
        total_start = time.time()
        
        self.state = AIState.THINKING
        
        # 1. RAG 검색
        rag_start = time.time()
        context_docs = await self.rag.search(user_text, owner_filter=self.callee_id)
        rag_time = (time.time() - rag_start) * 1000  # ms
        
        # 2. LLM 생성
        llm_start = time.time()
        response_text = await self.llm.generate_response(
            user_text=user_text,
            context_docs=[doc.text for doc in context_docs],
            system_prompt=self.config.google_cloud.gemini.system_prompt
        )
        llm_time = (time.time() - llm_start) * 1000  # ms
        
        # 3. TTS 첫 청크
        tts_start = time.time()
        await self._speak(response_text)
        tts_first_chunk = (time.time() - tts_start) * 1000  # ms
        
        # 전체 시간
        total_time = (time.time() - total_start) * 1000  # ms
        
        # 로그 기록
        logger.info("ai_response_time_breakdown",
                   call_id=self.call_id,
                   user_text_length=len(user_text),
                   response_text_length=len(response_text),
                   rag_search_ms=round(rag_time, 1),
                   llm_generation_ms=round(llm_time, 1),
                   tts_first_chunk_ms=round(tts_first_chunk, 1),
                   total_response_ms=round(total_time, 1))
        
        # Prometheus 메트릭
        self._record_metrics(rag_time, llm_time, tts_first_chunk, total_time)
```

### Prometheus 메트릭 정의

```python
# src/monitoring/metrics.py

from prometheus_client import Histogram

ai_response_time = Histogram(
    'ai_response_time_seconds',
    'AI 전체 응답 시간',
    buckets=[0.5, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0]
)

rag_search_time = Histogram(
    'rag_search_time_seconds',
    'RAG 검색 시간',
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5]
)

llm_generation_time = Histogram(
    'llm_generation_time_seconds',
    'LLM 생성 시간',
    buckets=[0.3, 0.5, 0.8, 1.0, 1.5, 2.0]
)

tts_first_chunk_time = Histogram(
    'tts_first_chunk_time_seconds',
    'TTS 첫 청크 생성 시간',
    buckets=[0.1, 0.2, 0.3, 0.5, 1.0]
)
```

---

## 📋 성능 테스트 시나리오

### 테스트 케이스

```python
# tests/performance/test_response_time.py

import pytest
import time

class TestAIResponseTime:
    """AI 응답 시간 성능 테스트"""
    
    @pytest.mark.asyncio
    async def test_simple_question_response_time(self):
        """간단한 질문 응답 시간 테스트"""
        orchestrator = AIOrchestrator(...)
        
        start = time.time()
        await orchestrator._generate_and_speak_response("안녕하세요")
        duration = (time.time() - start) * 1000
        
        # 목표: 1.5초 이내
        assert duration < 1500, f"응답 시간 초과: {duration}ms"
    
    @pytest.mark.asyncio
    async def test_rag_search_response_time(self):
        """RAG 검색 포함 응답 시간 테스트"""
        orchestrator = AIOrchestrator(...)
        
        start = time.time()
        await orchestrator._generate_and_speak_response("영업시간이 언제인가요?")
        duration = (time.time() - start) * 1000
        
        # 목표: 2초 이내
        assert duration < 2000, f"응답 시간 초과: {duration}ms"
    
    @pytest.mark.asyncio
    async def test_p95_response_time(self):
        """P95 응답 시간 테스트 (100회 반복)"""
        orchestrator = AIOrchestrator(...)
        durations = []
        
        for _ in range(100):
            start = time.time()
            await orchestrator._generate_and_speak_response("테스트 질문")
            durations.append((time.time() - start) * 1000)
        
        p95 = sorted(durations)[94]  # 95번째 백분위수
        
        # 목표: P95 < 2.5초
        assert p95 < 2500, f"P95 응답 시간 초과: {p95}ms"
```

---

## 🎯 결론

### 현재 시스템 예상 응답 시간

| 시나리오 | 예상 시간 | 사용자 경험 |
|---------|----------|----------|
| **최적 조건** | 0.9초 | ✅ 매우 자연스러움 |
| **일반적인 경우** | **1.3초** | ✅ 자연스러움 |
| **최악 조건** | 2.4초 | ⚠️ 수용 가능 |
| **최적화 후** | 0.8초 | ✨ 거의 즉각 반응 |

### 권장 사항

1. **초기 배포**: 현재 아키텍처 (평균 1.3초)
   - 자연스러운 대화 수준
   - 추가 최적화 없이 즉시 사용 가능

2. **1차 최적화** (2주 내):
   - Gemini Flash 모델 적용
   - max_tokens 150으로 제한
   - 프롬프트 최적화
   - **목표: 1.0초**

3. **2차 최적화** (1개월 내):
   - FAQ 캐싱 구현
   - 네트워크 리전 최적화
   - LLM 스트리밍 (지원 시)
   - **목표: 0.8초**

### 경쟁 제품 비교

- **Google Assistant**: 0.8~1.2초
- **Amazon Alexa**: 1.0~1.5초
- **Apple Siri**: 0.9~1.3초
- **본 시스템 (예상)**: 1.3초 → **경쟁력 있음** ✅

---

## 📞 문의

성능 관련 추가 질문이나 최적화 지원이 필요하시면 개발팀에 문의하세요.

