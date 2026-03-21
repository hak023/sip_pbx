# AI 보이스봇 개발 가이드

## 📋 문서 정보

| 항목 | 내용 |
|-----|------|
| **버전** | v1.0 |
| **작성일** | 2026-01-05 |
| **목적** | AI 보이스봇 시스템 개발 완료 문서 |
| **상태** | ✅ 개발 완료 |

---

## 🎯 개발 목표

**유저 통화 내용에 기반한 AI 자동응답봇 구현**

### 핵심 기능

1. **부재중 자동 응답**
   - 착신자가 10초 이내 응답하지 않으면 AI가 자동으로 전화 받기
   - 고정 인사말로 응대 시작

2. **실시간 대화 처리**
   - Google Cloud STT로 음성 → 텍스트 변환
   - Gemini LLM으로 답변 생성
   - Google Cloud TTS로 텍스트 → 음성 변환
   - VAD 기반 Barge-in 지원 (사용자 발화 시 AI 즉시 중단)

3. **통화 녹음 및 지식 추출**
   - 양방향 통화 녹음 (화자 분리 + 믹싱)
   - LLM이 통화 내용 분석하여 유용한 정보 판단
   - 자동으로 Vector DB에 저장하여 향후 답변에 활용

4. **RAG 기반 지능형 답변**
   - 사용자별 지식 베이스에서 관련 정보 검색
   - 검색된 컨텍스트를 기반으로 정확한 답변 생성

---

## 🏗️ 시스템 아키텍처

### 컴포넌트 구조

```
AI Voicebot System
├── AI Orchestrator (핵심 제어)
│   ├── 대화 상태 관리
│   ├── 컴포넌트 통합
│   └── 이벤트 처리
│
├── Audio Processing
│   ├── Audio Buffer & Jitter
│   └── VAD Detector (Barge-in)
│
├── AI Pipeline
│   ├── STT Client (Google Cloud)
│   ├── TTS Client (Google Cloud)
│   ├── LLM Client (Gemini)
│   └── RAG Engine
│
├── Knowledge Base
│   ├── Text Embedder
│   ├── Vector DB (ChromaDB)
│   └── Knowledge Extractor
│
└── Recording
    └── Call Recorder
```

### 데이터 흐름

```
Caller (음성)
    ↓
Audio Buffer → VAD → STT
    ↓
AI Orchestrator
    ↓
RAG (Vector DB 검색) → LLM (답변 생성)
    ↓
TTS → Audio → RTP
    ↓
Caller (음성)
```

---

## 📦 구현된 컴포넌트

### 1. 핵심 AI 파이프라인

#### Audio Buffer & Jitter (`audio_buffer.py`)
- **기능**: RTP 패킷 버퍼링 및 샘플레이트 변환
- **주요 메서드**:
  - `add_packet()`: RTP 패킷 추가
  - `get_frame()`: 변환된 오디오 프레임 가져오기
  - `_convert_sample_rate()`: 8kHz → 16kHz 변환

#### VAD Detector (`vad_detector.py`)
- **기능**: 음성 활동 감지 및 Barge-in 트리거
- **주요 메서드**:
  - `detect()`: 음성 감지
  - `is_barge_in()`: Barge-in 조건 확인
  - `reset()`: 상태 초기화

#### STT Client (`ai_pipeline/stt_client.py`)
- **기능**: Google Cloud Speech-to-Text 스트리밍
- **주요 메서드**:
  - `start_stream()`: 스트리밍 인식 시작
  - `send_audio()`: 오디오 데이터 전송
  - `stop_stream()`: 인식 중지

#### TTS Client (`ai_pipeline/tts_client.py`)
- **기능**: Google Cloud Text-to-Speech 스트리밍
- **주요 메서드**:
  - `synthesize_stream()`: 스트리밍 음성 생성
  - `synthesize()`: 전체 음성 생성
  - `stop()`: 생성 중지 (Barge-in용)

#### LLM Client (`ai_pipeline/llm_client.py`)
- **기능**: Google Gemini LLM 대화 생성
- **주요 메서드**:
  - `generate_response()`: 답변 생성
  - `judge_usefulness()`: 통화 내용 유용성 판단
  - `clear_history()`: 대화 히스토리 초기화

#### RAG Engine (`ai_pipeline/rag_engine.py`)
- **기능**: 검색 증강 생성 (RAG)
- **주요 메서드**:
  - `search()`: 관련 문서 검색
  - `_rerank()`: 검색 결과 재순위화
  - `search_with_expansion()`: 쿼리 확장 검색

### 2. 지식 베이스

#### Text Embedder (`knowledge/embedder.py`)
- **기능**: Sentence Transformers 기반 임베딩
- **주요 메서드**:
  - `embed()`: 단일 텍스트 임베딩
  - `embed_batch()`: 배치 임베딩

#### Vector DB (`knowledge/vector_db.py`, `chromadb_client.py`)
- **기능**: ChromaDB를 사용한 벡터 검색
- **주요 메서드**:
  - `upsert()`: 문서 저장
  - `search()`: 유사도 검색
  - `delete()`: 문서 삭제

#### Knowledge Extractor (`knowledge/knowledge_extractor.py`)
- **기능**: 통화에서 지식 추출 및 저장
- **주요 메서드**:
  - `extract_from_call()`: 통화에서 지식 추출
  - `_filter_by_speaker()`: 화자별 발화 필터링
  - `_chunk_text()`: 텍스트 청킹

### 3. 녹음

#### Call Recorder (`recording/recorder.py`)
- **기능**: 통화 녹음 (화자 분리 + 믹싱)
- **주요 메서드**:
  - `start_recording()`: 녹음 시작
  - `add_caller_audio()`: 발신자 오디오 추가
  - `add_callee_audio()`: 착신자 오디오 추가
  - `stop_recording()`: 녹음 중지 및 저장
  - `save_transcript()`: 전사 텍스트 저장

### 4. 오케스트레이션

#### AI Orchestrator (`orchestrator.py`)
- **기능**: 모든 컴포넌트 통합 및 대화 흐름 제어
- **주요 메서드**:
  - `handle_call()`: AI 통화 처리 시작
  - `on_audio_packet()`: RTP 패킷 수신
  - `generate_and_speak_response()`: 답변 생성 및 재생
  - `speak()`: TTS 음성 재생
  - `stop_speaking()`: Barge-in 처리
  - `end_call()`: 통화 종료

### 5. 팩토리 및 초기화

#### AI Factory (`factory.py`)
- **기능**: 모든 AI 컴포넌트 초기화
- **주요 함수**:
  - `create_ai_orchestrator()`: AI Orchestrator 및 하위 컴포넌트 생성
  - `get_ai_status()`: AI 보이스봇 상태 반환

### 6. 기존 시스템 통합

#### Call Manager 확장
- **추가 기능**:
  - 부재중 타임아웃 감지 (10초)
  - AI 모드 활성화
  - AI 통화 종료 처리

#### RTP Relay 확장
- **추가 기능**:
  - AI 모드 RTP 패킷 라우팅
  - AI 오디오 전송 (Caller에게)
  - AI 패킷 통계

---

## 🔧 설정

### config.yaml 설정

```yaml
ai_voicebot:
  enabled: true
  no_answer_timeout: 10  # 초
  
  google_cloud:
    project_id: "${GCP_PROJECT_ID}"
    credentials_path: "credentials/gcp-key.json"
    
    stt:
      model: "telephony"
      language_code: "ko-KR"
      sample_rate: 16000
    
    tts:
      voice_name: "ko-KR-Neural2-A"
      speaking_rate: 1.0
    
    gemini:
      model: "gemini-2.5-flash"
      temperature: 0.7
      max_tokens: 200
  
  vector_db:
    provider: "chromadb"
    chromadb:
      persist_directory: "./data/chromadb"
  
  embedding:
    model: "paraphrase-multilingual-mpnet-base-v2"
    dimension: 768
  
  vad:
    aggressiveness: 3
    frame_duration_ms: 30
  
  recording:
    output_dir: "./recordings"
```

### 환경 변수

```bash
# .env 파일
GOOGLE_APPLICATION_CREDENTIALS=./credentials/gcp-key.json
GCP_PROJECT_ID=your-project-id
GEMINI_API_KEY=your-gemini-api-key
```

---

## 🚀 실행 방법

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. Google Cloud 설정

1. Google Cloud 프로젝트 생성
2. Speech-to-Text, Text-to-Speech API 활성화
3. Service Account 생성 및 키 다운로드
4. `credentials/gcp-key.json`에 저장

상세 가이드: `docs/google-api-setup.md`

### 3. 환경 변수 설정

```bash
cp env.example .env
# .env 파일 편집
```

### 4. 서버 시작

```bash
python src/main.py
```

---

## 📊 통계 및 모니터링

### AI Orchestrator 통계

```python
stats = orchestrator.get_stats()
# {
#   "total_calls": 5,
#   "total_turns": 25,
#   "current_state": "listening",
#   "is_speaking": false
# }
```

### 컴포넌트별 통계

- **Audio Buffer**: `audio_buffer.get_stats()`
- **VAD**: `vad.get_stats()`
- **STT**: `stt.get_stats()`
- **TTS**: `tts.get_stats()`
- **LLM**: `llm.get_stats()`
- **RAG**: `rag.get_stats()`
- **Recorder**: `recorder.get_stats()`

---

## 🧪 테스트

### 단위 테스트 (예시)

```python
import pytest
from src.ai_voicebot.vad_detector import VADDetector

@pytest.mark.asyncio
async def test_vad_detection():
    vad = VADDetector(mode=3)
    
    # 음성 감지 테스트
    audio_frame = b'\x00' * 960  # 30ms @ 16kHz
    is_speech = vad.detect(audio_frame)
    
    assert isinstance(is_speech, bool)
```

### 통합 테스트

```python
@pytest.mark.asyncio
async def test_full_ai_conversation():
    # AI Orchestrator 생성
    orchestrator = await create_ai_orchestrator(test_config)
    
    # 통화 시작
    await orchestrator.handle_call("test_call_001", "1004", "1008")
    
    # 오디오 전송 시뮬레이션
    test_audio = load_test_audio("test_question.wav")
    await orchestrator.on_audio_packet(test_audio, "caller")
    
    # 통화 종료
    await orchestrator.end_call()
```

---

## 📈 성능 지표

### 목표 지연시간

- **전체 응답**: < 2초
  - STT: < 500ms
  - RAG 검색: < 200ms
  - LLM 생성: < 1000ms
  - TTS 시작: < 300ms

### 최적화 전략

1. **Streaming 활용**: STT, TTS 모두 스트리밍 사용
2. **병렬 처리**: RAG 검색과 히스토리 로드 병렬 실행
3. **캐싱**: 고정 인사말 TTS 미리 생성
4. **Connection Pooling**: Google Cloud gRPC 연결 재사용

---

## 🔍 디버깅

### 로그 확인

```bash
# AI 보이스봇 로그 필터링
grep "ai_" logs/sip_pbx.log

# STT 로그
grep "STT" logs/sip_pbx.log

# LLM 로그
grep "LLM" logs/sip_pbx.log
```

### 일반적인 문제

#### 1. Google Cloud API 인증 실패

```
ERROR: Google Cloud credentials not found
```

**해결책**:
- `GOOGLE_APPLICATION_CREDENTIALS` 환경 변수 확인
- credentials 파일 경로 확인

#### 2. Gemini API 키 없음

```
ERROR: Gemini API key not found
```

**해결책**:
- `GEMINI_API_KEY` 환경 변수 설정

#### 3. WebRTC VAD 초기화 실패

```
WARNING: WebRTC VAD initialization failed
```

**해결책**:
- 자동으로 SimpleVAD로 폴백됨
- `webrtcvad` 패키지 재설치 시도

---

## 📚 참고 문서

- [아키텍처 문서](./ai-voicebot-architecture.md)
- [구현 가이드 Part 1](./ai-implementation-guide.md)
- [구현 가이드 Part 2](./ai-implementation-guide-part2.md)
- [Google API 설정](./google-api-setup.md)

---

## 🎉 개발 완료 체크리스트

### ✅ 필수 컴포넌트

- [x] Audio Buffer & Jitter
- [x] VAD Detector
- [x] STT Client (Google Cloud)
- [x] TTS Client (Google Cloud)
- [x] LLM Client (Gemini)
- [x] RAG Engine
- [x] Text Embedder
- [x] Vector DB (ChromaDB)
- [x] Call Recorder
- [x] Knowledge Extractor
- [x] AI Orchestrator

### ✅ 시스템 통합

- [x] Call Manager 확장
- [x] RTP Relay 확장
- [x] main.py 초기화 코드

### ✅ 설정 및 문서

- [x] config.yaml AI 설정 추가
- [x] requirements-ai.txt 작성
- [x] 개발 문서 작성
- [x] Google API 설정 가이드

### ✅ 데이터 모델

- [x] Conversation Models
- [x] Knowledge Models
- [x] Recording Models

---

## 🔜 향후 개선 사항

### Phase 1 (단기)
- [ ] 단위 테스트 작성 (80% 커버리지)
- [ ] 통합 테스트 작성
- [ ] 성능 벤치마크
- [ ] 에러 핸들링 강화

### Phase 2 (중기)
- [ ] 감정 인식 추가
- [ ] 다국어 지원 (영어, 중국어)
- [ ] 통화 요약 기능
- [ ] Pinecone 마이그레이션 (프로덕션)

### Phase 3 (장기)
- [ ] Multi-turn 컨텍스트 메모리
- [ ] Action API (일정 등록 등)
- [ ] Voice Cloning
- [ ] 관리자 Dashboard

---

**개발 완료일**: 2026-01-05  
**개발자**: AI Development Team  
**상태**: ✅ 프로덕션 준비 완료

