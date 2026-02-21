# AI 통화 응대 시스템 설계 문서

## 📋 목차
1. [현재 상태 분석](#1-현재-상태-분석)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [구현 계획](#3-구현-계획)
4. [VectorDB 스키마 설계](#4-vectordb-스키마-설계)
5. [통화 흐름 (Call Flow)](#5-통화-흐름-call-flow)
6. [LLM 프롬프트 전략](#6-llm-프롬프트-전략)
7. [예외 처리](#7-예외-처리)
8. [성능 최적화](#8-성능-최적화)

---

## 1. 현재 상태 분석

### ✅ 정상 작동하는 기능
- SIP 신호 처리 (INVITE, 200 OK, ACK)
- AI 모드 활성화 및 전환
- STUN 바인딩 (NAT traversal)
- 통화 수립 (`call_established`)
- Barge-in 감지 기능
- TTS 중지 기능

### ❌ 해결 필요한 이슈
1. **STT Audio Timeout (Line 207)**
   ```
   "400 Audio Timeout Error: Long duration elapsed without audio"
   ```
   - **원인**: AI가 먼저 말하지 않고 STT만 시작되어 오디오가 없음
   - **해결**: AI의 첫 인사말 구현으로 자연스럽게 해결

2. **RTP Relay Error (Line 259, 262-287)**
   ```
   "[WinError 1214] 지정된 네트워크 이름의 형식이 틀립니다"
   ```
   - **원인**: Windows 환경에서 UDP 소켓 전송 시 주소 형식 문제
   - **해결**: `rtp_relay.py`의 주소 처리 로직 수정 필요

---

## 2. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────┐
│                      AI 통화 응대 시스템                           │
└─────────────────────────────────────────────────────────────────┘

┌──────────┐         ┌──────────────┐         ┌──────────────┐
│   UAC    │◄───────►│  SIP B2BUA   │◄───────►│     UAS      │
│  (발신자) │   SIP    │  (PBX 서버)   │   SIP    │  (수신자)    │
└──────────┘         └──────────────┘         └──────────────┘
     │                      │
     │ RTP/RTCP             │ No Answer (10초)
     │                      ▼
     │              ┌──────────────┐
     │              │  AI 모드     │
     │              │  활성화      │
     │              └──────────────┘
     │                      │
     │                      ▼
     ▼              ┌──────────────────────────────────┐
┌──────────┐       │     AI Orchestrator              │
│   RTP    │◄─────►│  ┌────────────────────────────┐  │
│  Media   │       │  │  1. VectorDB (나의 정보)    │  │
│  Stream  │       │  │  2. RAG Engine             │  │
└──────────┘       │  │  3. LLM (Gemini)           │  │
                   │  │  4. TTS Engine             │  │
                   │  │  5. STT Engine             │  │
                   │  │  6. Barge-in Controller    │  │
                   │  └────────────────────────────┘  │
                   └──────────────────────────────────┘
```

---

## 3. 구현 계획

### Phase 1: VectorDB - "나의 정보" 관리

#### 3.1. Knowledge Base 구조
```python
# VectorDB Collection: "organization_info"
{
    "id": "org_001",
    "organization_name": "기상청",
    "organization_type": "government_agency",
    "service_description": "날씨 예보 및 기상 정보 안내",
    "greeting_templates": [
        "안녕하세요. 저는 {organization_name}의 AI 통화 비서입니다.",
        "안녕하세요. {organization_name} AI 상담원입니다.",
        "{organization_name}에 전화해 주셔서 감사합니다. AI 비서가 도와드리겠습니다."
    ],
    "capabilities": [
        "날씨 예보 조회",
        "기상 특보 안내",
        "과거 기상 데이터 제공",
        "기상청 문의 연결"
    ],
    "contact_info": {
        "main_number": "131",
        "website": "www.kma.go.kr",
        "business_hours": "평일 09:00-18:00"
    },
    "knowledge_documents": [
        "날씨 예보 안내 절차",
        "기상 특보 설명",
        "태풍 정보 안내 가이드"
    ],
    "metadata": {
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-02-11T00:00:00Z",
        "version": "1.0"
    }
}
```

#### 3.2. VectorDB 초기화 스크립트
**파일**: `src/ai_voicebot/knowledge/init_organization_info.py`

```python
"""
기관 정보를 VectorDB에 초기 로딩하는 스크립트
"""

async def initialize_organization_info():
    """기상청 정보를 VectorDB에 저장"""
    
    # 1. Collection 생성
    collection = chroma_client.get_or_create_collection("organization_info")
    
    # 2. 기관 정보 저장
    org_data = {
        "organization_name": "기상청",
        "greeting_template": "안녕하세요. 저는 기상청의 AI 통화 비서입니다.",
        "capabilities": "날씨 예보, 기상 특보, 과거 기상 데이터 제공",
        ...
    }
    
    # 3. Embedding 및 저장
    collection.add(
        documents=[json.dumps(org_data, ensure_ascii=False)],
        metadatas=[{"type": "organization", "org_id": "kma"}],
        ids=["org_kma"]
    )
```

---

### Phase 2: AI 인사말 생성 및 TTS

#### 3.3. 통화 시작 시퀀스
**파일**: `src/ai_voicebot/orchestrator/ai_orchestrator.py`

```python
async def start_ai_call(self, call_id: str, caller_info: dict):
    """AI 통화 시작 (첫 인사말 생성 및 발화)"""
    
    # 1. VectorDB에서 기관 정보 조회 (RAG)
    org_info = await self._retrieve_organization_info()
    
    # 2. LLM으로 맞춤형 인사말 생성
    greeting = await self._generate_greeting(org_info, caller_info)
    # 예: "안녕하세요. 저는 기상청의 AI 통화 비서입니다. 
    #      무엇을 도와드릴까요?"
    
    # 3. Barge-in 일시 비활성화 (TTS 중에는 무시)
    self.barge_in_enabled = False
    
    # 4. TTS 발화
    await self._play_greeting(greeting)
    
    # 5. TTS 완료 후 Barge-in 활성화
    self.barge_in_enabled = True
    
    # 6. STT 청취 모드로 전환
    await self._start_listening()
```

#### 3.4. RAG 기반 인사말 생성
```python
async def _generate_greeting(self, org_info: dict, caller_info: dict) -> str:
    """RAG로 인사말 생성"""
    
    # LLM 프롬프트 구성
    prompt = f"""
당신은 {org_info['organization_name']}의 친절한 AI 통화 비서입니다.

기관 정보:
- 이름: {org_info['organization_name']}
- 서비스: {org_info['service_description']}
- 제공 가능한 기능: {', '.join(org_info['capabilities'])}

발신자 정보:
- 전화번호: {caller_info.get('caller_number', '알 수 없음')}

위 정보를 바탕으로 자연스럽고 친근한 인사말을 1-2문장으로 생성하세요.
예시 형식을 참고하되, 획일적이지 않게 다양하게 표현하세요.

인사말:
"""
    
    # LLM 호출
    response = await self.llm_client.generate(prompt)
    return response.strip()
```

---

### Phase 3: Barge-in 제어

#### 3.5. Barge-in 상태 관리
**파일**: `src/ai_voicebot/orchestrator/barge_in_controller.py`

```python
class BargeInController:
    """TTS 발화 중 Barge-in 제어"""
    
    def __init__(self):
        self.tts_speaking = False
        self.barge_in_enabled = True
        self.silence_threshold = 2.0  # 2초 침묵 감지
        
    async def on_tts_start(self):
        """TTS 시작 시 호출"""
        self.tts_speaking = True
        # TTS 중에는 barge-in 무시
        
    async def on_tts_end(self):
        """TTS 종료 시 호출"""
        self.tts_speaking = False
        # TTS 종료 후 barge-in 활성화
        
    def should_process_speech(self, speech_detected: bool) -> bool:
        """사용자 발화를 처리할지 결정"""
        if self.tts_speaking:
            # TTS 중에는 무시
            return False
        
        if not self.barge_in_enabled:
            return False
            
        return speech_detected
```

#### 3.6. STT 통합
```python
async def on_stt_result(self, transcript: str, is_final: bool):
    """STT 결과 처리"""
    
    # 1. TTS 중이면 무시
    if not self.barge_in_controller.should_process_speech(is_final):
        logger.debug("Speech ignored during TTS", transcript=transcript)
        return
    
    # 2. 중간 결과 처리
    if not is_final:
        self.current_utterance += transcript
        self.last_speech_time = time.time()
        return
    
    # 3. 최종 결과 처리
    if is_final:
        self.current_utterance += transcript
        
        # 4. 2초 침묵 감지
        await asyncio.sleep(2.0)
        if time.time() - self.last_speech_time >= 2.0:
            # 발화 완료로 간주
            await self._process_user_utterance(self.current_utterance)
            self.current_utterance = ""
```

---

## 4. VectorDB 스키마 설계

### 4.1. Collection 구조

#### Collection 1: `organization_info` (기관 정보)
```yaml
collection_name: organization_info
embedding_model: multilingual-e5-base
documents:
  - id: org_kma
    content: "기상청 정보 전체 텍스트"
    metadata:
      type: organization
      org_id: kma
      org_name: 기상청
```

#### Collection 2: `faq_knowledge` (FAQ 지식)
```yaml
collection_name: faq_knowledge
documents:
  - id: faq_001
    content: "Q: 내일 날씨가 어떤가요? A: 날씨 예보는..."
    metadata:
      type: faq
      category: weather_forecast
      
  - id: faq_002
    content: "Q: 기상 특보는 어디서 확인하나요? A: ..."
    metadata:
      type: faq
      category: weather_warning
```

#### Collection 3: `call_history` (통화 이력)
```yaml
collection_name: call_history
documents:
  - id: call_001
    content: "2026-02-11 발신자: 1004, 내용: 내일 날씨 문의..."
    metadata:
      call_id: YOM~WwlNc-
      caller: "1004"
      timestamp: "2026-02-11T16:11:19Z"
      duration: 120
      topics: ["weather_forecast"]
```

---

## 5. 통화 흐름 (Call Flow)

### 5.1. 전체 시퀀스

```
┌──────────┐                                    ┌──────────────┐
│   UAC    │                                    │  AI System   │
└──────────┘                                    └──────────────┘
     │                                                  │
     │  1. INVITE (no callee answer)                   │
     ├─────────────────────────────────────────────────>│
     │                                                  │
     │  2. 200 OK (AI mode)                            │
     │<─────────────────────────────────────────────────┤
     │                                                  │
     │  3. ACK                                          │
     ├─────────────────────────────────────────────────>│
     │                                                  │
     │                    [통화 수립]                    │
     │                                                  │
     │                                          4. RAG: VectorDB 조회
     │                                             "기상청 정보"
     │                                                  │
     │                                          5. LLM: 인사말 생성
     │                                             "안녕하세요..."
     │                                                  │
     │  6. RTP: TTS 오디오                             │
     │  "안녕하세요. 기상청 AI 비서입니다."              │
     │<═════════════════════════════════════════════════┤
     │                                                  │
     │                    [Barge-in OFF]                │
     │                                                  │
     │  7. TTS 완료                                     │
     │                                                  │
     │                    [Barge-in ON]                 │
     │                                                  │
     │  8. RTP: 사용자 음성                             │
     │  "내일 날씨 알려주세요"                           │
     ├═════════════════════════════════════════════════>│
     │                                                  │
     │                                          9. STT: 텍스트 변환
     │                                                  │
     │                                          10. 2초 침묵 감지
     │                                                  │
     │                                          11. RAG: 관련 정보 검색
     │                                              VectorDB (FAQ)
     │                                                  │
     │                                          12. LLM: 응답 생성
     │                                              "내일은 맑고..."
     │                                                  │
     │  13. RTP: TTS 오디오                            │
     │  "내일은 맑고 최고 기온은..."                     │
     │<═════════════════════════════════════════════════┤
     │                                                  │
     │  [대화 반복: 8~13]                               │
     │                                                  │
     │  14. BYE                                         │
     ├─────────────────────────────────────────────────>│
     │                                                  │
     │  15. 200 OK (BYE)                               │
     │<─────────────────────────────────────────────────┤
     │                                                  │
```

### 5.2. 상태 전이도

```
[Call Established]
       │
       ▼
[Greeting Phase]
  - Barge-in OFF
  - TTS: 인사말
       │
       ▼
[Listening Phase]
  - Barge-in ON
  - STT: 사용자 발화
  - 2초 침묵 감지
       │
       ▼
[Processing Phase]
  - RAG: 정보 검색
  - LLM: 응답 생성
       │
       ▼
[Response Phase]
  - Barge-in OFF
  - TTS: AI 응답
       │
       ▼
   [대화 루프]
   (Listening → Processing → Response)
       │
       ▼
[Call End]
  - BYE 처리
  - 통화 이력 저장
```

---

## 6. LLM 프롬프트 전략

### 6.1. 시스템 프롬프트 (고정)

```python
SYSTEM_PROMPT = """
당신은 {organization_name}의 친절하고 전문적인 AI 통화 비서입니다.

## 역할과 책임
- 발신자의 질문에 정확하고 친절하게 답변
- {organization_name}의 서비스와 정보를 명확하게 안내
- 필요시 적절한 부서나 담당자에게 연결 제안
- 통화 중 자연스럽고 인간적인 대화 유지

## 제공 가능한 서비스
{capabilities}

## 대화 원칙
1. 간결하고 명확하게 답변 (1-2문장)
2. 전문 용어는 쉽게 풀어서 설명
3. 질문 의도를 정확히 파악
4. 모르는 것은 솔직히 인정하고 대안 제시
5. 공손하고 존중하는 어투 유지

## 제약 사항
- {organization_name}과 관련 없는 주제는 정중히 거절
- 개인 정보는 절대 요구하지 않음
- 법률/의료 조언은 제공하지 않음
"""
```

### 6.2. 대화 프롬프트 (동적)

```python
def build_conversation_prompt(
    conversation_history: List[dict],
    user_utterance: str,
    rag_context: str
) -> str:
    """대화 컨텍스트를 포함한 프롬프트 생성"""
    
    # 1. 통화 이력 요약
    history_text = "\n".join([
        f"{'사용자' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
        for msg in conversation_history[-5:]  # 최근 5턴만
    ])
    
    # 2. RAG 컨텍스트
    context_text = f"""
관련 정보 (VectorDB 검색 결과):
{rag_context}
"""
    
    # 3. 전체 프롬프트 조합
    prompt = f"""
## 통화 이력
{history_text}

{context_text}

## 현재 사용자 발화
사용자: {user_utterance}

## 지시사항
위 통화 이력과 관련 정보를 참고하여, 사용자의 현재 발화에 대해
자연스럽고 정확한 응답을 1-2문장으로 생성하세요.

AI:
"""
    
    return prompt
```

### 6.3. RAG 검색 쿼리 전략

```python
async def retrieve_context(self, user_utterance: str, conversation_history: List[dict]) -> str:
    """VectorDB에서 관련 정보 검색"""
    
    # 1. 쿼리 확장 (대화 이력 포함)
    expanded_query = self._expand_query(user_utterance, conversation_history)
    
    # 2. VectorDB 검색 (Multi-query)
    results = await asyncio.gather(
        self.vector_db.search("faq_knowledge", expanded_query, top_k=3),
        self.vector_db.search("organization_info", expanded_query, top_k=2),
        self.vector_db.search("call_history", expanded_query, top_k=2),
    )
    
    # 3. 결과 통합 및 Re-ranking
    context = self._merge_and_rank(results)
    
    return context
```

---

## 7. 예외 처리

### 7.1. STT 오류

| 오류 | 원인 | 처리 방안 |
|------|------|-----------|
| Audio Timeout | 장시간 침묵 | "죄송합니다. 들리지 않습니다. 다시 말씀해 주시겠어요?" (TTS) |
| Recognition Error | STT 실패 | "죄송합니다. 잘 못 알아들었습니다. 다시 한 번 말씀해 주시겠어요?" |
| Network Error | 연결 끊김 | 재시도 (3회), 실패 시 통화 종료 |

### 7.2. LLM 오류

| 오류 | 처리 방안 |
|------|-----------|
| Rate Limit | 백오프 재시도, 실패 시 "잠시 후 다시 시도해주세요" |
| Timeout | "죄송합니다. 처리 중 문제가 발생했습니다" |
| Invalid Response | 기본 응답 사용 (Fallback) |

### 7.3. TTS 오류

| 오류 | 처리 방안 |
|------|-----------|
| Synthesis Error | 재시도 (1회), 실패 시 텍스트만 로깅 |
| Audio Buffer Full | 버퍼 비우기, 우선순위 높은 메시지만 발화 |

---

## 8. 성능 최적화

### 8.1. Latency 목표

| 단계 | 목표 시간 |
|------|-----------|
| RAG 검색 | < 200ms |
| LLM 응답 생성 | < 1500ms |
| TTS 합성 시작 | < 300ms |
| **총 응답 시간** | **< 2000ms** |

### 8.2. 최적화 전략

#### 캐싱
```python
# 자주 사용되는 응답 캐싱
@cache(ttl=3600)
async def get_common_response(query_type: str) -> str:
    """자주 묻는 질문 캐싱"""
    pass

# 인사말 사전 생성
PREGENERATED_GREETINGS = [
    "안녕하세요. 기상청 AI 비서입니다. 무엇을 도와드릴까요?",
    "안녕하세요. 기상청입니다. 어떤 도움이 필요하신가요?",
]
```

#### 병렬 처리
```python
# RAG + LLM 병렬 실행
async def process_utterance(self, text: str):
    # RAG와 이전 응답 TTS를 병렬로
    rag_task = self.retrieve_context(text)
    tts_task = self.play_previous_response()  # 이전 응답 발화
    
    context, _ = await asyncio.gather(rag_task, tts_task)
    
    # LLM 생성
    response = await self.generate_response(text, context)
    return response
```

#### 스트리밍 TTS
```python
# LLM 생성과 TTS를 스트리밍으로 연결
async def stream_response(self, text: str):
    """LLM 출력을 실시간으로 TTS로 변환"""
    
    async for chunk in self.llm_client.stream(prompt):
        # 문장 단위로 끊어서 TTS
        if chunk.endswith('.') or chunk.endswith('?'):
            await self.tts_client.synthesize_and_play(chunk)
```

---

## 9. 파일 구조

```
sip-pbx/
├── src/
│   ├── ai_voicebot/
│   │   ├── orchestrator/
│   │   │   ├── ai_orchestrator.py         # 메인 AI 로직
│   │   │   ├── barge_in_controller.py     # Barge-in 제어
│   │   │   └── conversation_manager.py    # 대화 흐름 관리
│   │   │
│   │   ├── knowledge/
│   │   │   ├── organization_info.py       # 기관 정보 관리
│   │   │   ├── init_organization_info.py  # 초기화 스크립트
│   │   │   └── rag_engine.py              # RAG 검색 엔진
│   │   │
│   │   ├── ai_pipeline/
│   │   │   ├── stt_client.py              # ✅ 수정 완료
│   │   │   ├── tts_client.py              # TTS 클라이언트
│   │   │   └── llm_client.py              # LLM 클라이언트
│   │   │
│   │   └── prompts/
│   │       ├── system_prompts.py          # 시스템 프롬프트
│   │       └── prompt_templates.py        # 프롬프트 템플릿
│   │
│   └── sip_core/
│       └── sip_endpoint.py                # ✅ SDP 수정 완료
│
├── data/
│   ├── organization_info.json             # 기관 정보 데이터
│   ├── faq_knowledge.json                 # FAQ 데이터
│   └── prompts/                           # 프롬프트 템플릿
│
└── docs/
    └── AI_CALL_HANDLING_DESIGN.md         # 본 문서
```

---

## 10. 구현 우선순위

### Phase 1: 기본 인사말 (1-2일)
- [ ] VectorDB에 기관 정보 저장
- [ ] RAG 기반 인사말 생성
- [ ] TTS 발화
- [ ] Barge-in 제어 (TTS 중 무시)

### Phase 2: 대화 관리 (2-3일)
- [ ] STT 2초 침묵 감지
- [ ] 대화 이력 관리
- [ ] LLM 프롬프트 구성
- [ ] 응답 생성 및 TTS

### Phase 3: RAG 고도화 (2-3일)
- [ ] FAQ 지식베이스 구축
- [ ] Multi-query RAG
- [ ] Re-ranking 로직
- [ ] 컨텍스트 압축

### Phase 4: 성능 최적화 (1-2일)
- [ ] 응답 캐싱
- [ ] 병렬 처리
- [ ] 스트리밍 TTS
- [ ] 레이턴시 모니터링

---

## 11. 테스트 시나리오

### 시나리오 1: 기본 날씨 문의
```
User: [전화 연결]
AI: "안녕하세요. 저는 기상청의 AI 통화 비서입니다. 무엇을 도와드릴까요?"
User: "내일 날씨 알려주세요"
AI: "내일은 전국적으로 맑은 날씨가 예상됩니다. 최고 기온은 15도입니다."
User: "감사합니다" [통화 종료]
```

### 시나리오 2: Barge-in 테스트
```
User: [전화 연결]
AI: "안녕하세요. 저는 기상청의..." [TTS 중]
User: "내일 날씨!" [발화 - 무시됨]
AI: "...AI 통화 비서입니다. 무엇을 도와드릴까요?" [TTS 완료]
User: "내일 날씨 알려주세요" [발화 - 처리됨]
AI: [정상 응답]
```

### 시나리오 3: 복합 문의
```
User: "주말 날씨는요?"
AI: "이번 주말은 토요일은 맑고, 일요일은 오후부터 비가 예상됩니다."
User: "우산 필요한가요?"
AI: [대화 이력 참고] "네, 일요일 외출 시 우산을 준비하시는 것이 좋겠습니다."
```

---

## 12. 모니터링 지표

### 12.1. 통화 품질
- 평균 응답 시간 (RAG + LLM + TTS)
- STT 정확도
- TTS 음질 평가
- Barge-in 오탐지율

### 12.2. 사용자 경험
- 평균 통화 시간
- 대화 턴 수
- 사용자 만족도 (통화 후 설문)
- 통화 완료율

### 12.3. 시스템 성능
- API 호출 횟수 (LLM, STT, TTS)
- VectorDB 쿼리 성능
- 메모리 사용량
- 동시 통화 처리 수

---

## 부록 A: 현재 에러 해결 방안

### A.1. RTP Relay Error 수정
**파일**: `src/media/rtp_relay.py`

```python
# 문제: Windows 환경에서 UDP 소켓 주소 형식 오류
# 해결: 주소 튜플을 문자열로 변환하지 않고 직접 사용

# Before (추정)
self.transport.sendto(data, f"{addr[0]}:{addr[1]}")  # ❌

# After
self.transport.sendto(data, (addr[0], addr[1]))      # ✅
```

### A.2. STT Audio Timeout 해결
- AI 첫 인사말 구현으로 자연스럽게 해결됨
- STT 시작 전에 TTS 발화가 이루어지면 오디오 스트림이 활성화됨

---

**문서 작성일**: 2026-02-11  
**작성자**: AI Assistant  
**버전**: 1.0
