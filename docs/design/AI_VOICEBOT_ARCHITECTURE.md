# AI Voicebot 아키텍처 설계서

**목적**: AI 음성봇의 전체 구조, 컴포넌트 간 데이터 흐름, 주요 설계 결정을 기술한다.
**작성일**: 2026-03-30

---

## 1. 시스템 개요

AI Voicebot은 SIP 전화 수신 시 자동으로 응대하는 음성 AI 시스템이다.
음성 인식(STT), 자연어 이해(NLU), 지식 검색(RAG), 대화 생성(LLM), 음성 합성(TTS)을
실시간 RTP 스트림 위에서 통합 운영한다.

```
┌─────────────────────────────────────────────────────────────────┐
│                        SIP/RTP Layer                            │
│  SIP Endpoint ◄──► CallManager ◄──► RTPRelayWorker              │
└──────────┬──────────────────────────────────────┬───────────────┘
           │ (수신 오디오)                        │ (송신 오디오)
           ▼                                      ▲
┌──────────────────────────────────────────────────────────────────┐
│                    Pipecat Pipeline                               │
│  Input ─► VAD ─► STT ─► RAGLLMProcessor ─► TTS ─► Output        │
│                            │                                      │
│                   ┌────────┴────────┐                             │
│                   │  LangGraph Agent │                             │
│                   │  (대화 그래프)    │                             │
│                   └────────┬────────┘                             │
│                            │                                      │
│              ┌─────────────┼─────────────┐                        │
│              ▼             ▼             ▼                        │
│         ChromaDB      LLM Client    HITL Service                  │
│         (RAG/KB)     (Gemini API)   (운영자 연계)                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 컴포넌트 아키텍처

### 2.1 Pipecat Pipeline

실시간 오디오 처리 프레임워크(Pipecat) 기반으로, 다음 순서의 프로세서 체인을 구성한다.

```
SIPPBXInputTransport
  → RecordingProcessor (입력 녹음)
    → VADWrapperProcessor (음성 활동 감지, barge-in 지원)
      → GoogleSTTService (음성→텍스트)
        → RAGLLMProcessor (대화 처리 핵심)
          → KoreanTTSNumberProcessor (한국어 숫자 정규화)
            → DebugGoogleTTSService (텍스트→음성)
              → TTSCompleteNotifier (TTS 완료 알림)
                → RecordingProcessor (출력 녹음)
                  → SIPPBXOutputTransport (RTP 송신)
```

**핵심 파라미터**:

| 파라미터 | 값 | 설명 |
|---|---|---|
| `allow_interruptions` | True | 사용자 발화로 AI 응답 중단 가능 |
| `min_words` (UserTurnStartStrategy) | 3 | 최소 3단어 발화로 턴 시작 인식 |
| `PIPELINE_SHUTDOWN_TIMEOUT_SECS` | 25.0초 | 파이프라인 종료 대기 시간 |
| 초기 인사 지연 | 0.5초 | 오디오 루프 안정화 후 인사 전송 |

### 2.2 RAGLLMProcessor (대화 처리 핵심)

Pipecat 프로세서로서 STT 텍스트를 받아 LangGraph Agent를 호출하고,
응답 텍스트를 TTS로 전달하는 중앙 제어기이다.

**주요 기능**:
- **사용자 발화 큐**: `_user_message_queue`에 STT 텍스트 적재, 백그라운드 워커가 처리
- **에이전트 턴**: LangGraph `ConversationAgent.process_utterance()` 호출
- **HITL 응답 소비**: `_hitl_response_queue`에서 운영자 답변을 수신하여 TTS 전달
- **스트리밍 응답**: 문장 단위로 수집하여 점진적 TTS 전송
- **필러 문구**: 처리 지연 시 "정보를 확인중입니다. 잠시만 기다려주세요" 자동 송출
- **Cleanup**: 파이프라인 종료 시 워커 태스크 취소 및 큐 정리

### 2.3 LangGraph Agent

`StateGraph(ConversationState)` 기반 대화 그래프로, 사용자 의도에 따라
최적 경로를 선택한다.

```
classify_intent → route_utterance
    │
    ├─ greeting/farewell ──► greeting_farewell_kb ──► update_state ──► END
    │                                │
    │                       (miss)   ▼
    │                         rewrite_query → adaptive_rag → ...
    │
    ├─ B그룹 (affirm/deny/...) ──► template_response ──► update_state ──► END
    │
    ├─ repeat ──► repeat_response ──► update_state ──► END
    ├─ clarification ──► clarification_response ──► update_state ──► END
    ├─ help ──► help_response ──► update_state ──► END
    │
    ├─ chitchat/out_of_scope ──► generate_response (RAG스킵) ──► update_state ──► END
    │
    └─ question/complaint/transfer/nlu_fallback ──► check_cache
            │
            ├─ cache hit ──► update_state ──► END
            │
            └─ cache miss ──► rewrite_query → adaptive_rag
                                    │
                                    ├─ RAG 0건 ──► step_back → generate_response
                                    └─ RAG N건 ──► generate_response
                                                       │
                                                       ▼
                                                  hitl_alert → update_cache → update_state → END
```

**그래프 컴파일 캐시**: 컴파일에 ~7초 소요되므로 전역 캐시로 재사용.

### 2.4 RAG Engine

ChromaDB 벡터 데이터베이스를 활용한 검색 증강 생성(RAG) 엔진이다.

```
사용자 쿼리
    │
    ▼
TextEmbedder.embed_text()
    │ (384차원 벡터)
    ▼
ChromaDB vector search
    │ owner + category 필터
    │ n_results = SENTENCE_TOP_K (10)
    ▼
Score 계산: 1/(1+distance)
    │ similarity_threshold 기반 필터
    ▼
Reranking (키워드 오버랩 + 길이)
    │
    ▼
Top-K 결과 → LLM 컨텍스트
```

**Adaptive RAG 노드** 추가 처리:
- **2-pass 검색**: STT 원문 + rewrite 쿼리가 다르면 양쪽 결과 병합
- **Small-to-Big Expansion**: 문장 단위 검색 결과를 상위 문서 문맥으로 확장
- **Contextual Compression**: 키워드 매칭으로 관련 문장만 추출 (최대 1200자)
- **Confidence 산출**: `(top_score × 0.7 + avg_score × 0.3) × 1.1`

### 2.5 LLM Client (Google Gemini)

Google Generative AI (Gemini) API를 사용하는 LLM 클라이언트이다.

**주요 메서드**:

| 메서드 | 용도 | 특징 |
|---|---|---|
| `generate_response` | 일반 응답 생성 | RAG 컨텍스트 + 대화 기록 기반 |
| `generate_response_streaming` | 스트리밍 응답 | 문장 부호(`.?!。`) 기준 문장 단위 yield |
| `format_for_customer` | HITL 답변 정제 | 운영자 텍스트 → 고객용 자연어 변환 |
| `judge_usefulness` | 지식 추출 판단 | 통화 후 새 지식 자동 추출 |
| `judge_barge_in` | 맞장구 판단 | "맞장구" vs "진정한 끼어들기" 분류 |

**모델**: `gemini-2.5-flash` (기본)
**시스템 프롬프트**: RAG 컨텍스트 활용 극대화, 서비스 안내 기반 가이드 응답 허용

### 2.6 HITL (Human-In-The-Loop) 서비스

AI가 자신 없는 질문에 대해 운영자에게 도움을 요청하는 에스컬레이션 시스템이다.

```
LangGraph hitl_alert 노드
    │ (confidence < 0.3 또는 needs_follow_up)
    ▼
RAGLLMProcessor._hitl_manager.handle_hitl_result()
    │
    ├─ WebSocket emit_hitl_requested → 운영자 대시보드
    │
    ├─ hitl_service.note_hitl_request() → HITL 큐 등록
    │
    └─ 고객에게 대기 멘트 TTS 송출
           │
           │ (운영자 응답 대기)
           ▼
_hitl_response_queue ◄── 운영자 API 응답
           │
           ▼
LLM format_hitl_reply_for_customer() (선택)
           │
           ▼
TTS 송출 → 고객에게 전달
```

**HITL 면제 의도**: `greeting`, `chitchat`, `out_of_scope`

### 2.7 Persona 서비스

조직별 AI 봇 성격을 정의하고, 발화의 업무 관련성을 판단하는 서비스이다.

- **저장소**: ChromaDB `persona` 컬렉션 (owner별 1건)
- **속성**: 이름, 설명, scope_keywords, chitchat_response_template, enabled
- **query relevance**: 발화 임베딩 vs 페르소나 임베딩 유사도 → 0.6 미만이면 `chitchat`
- **API**: `GET/POST/PUT/DELETE /api/persona/{owner}`

### 2.8 Knowledge 서비스

ChromaDB 기반 지식 관리 서비스로, FAQ·인사말·전문 지식을 저장/조회한다.

**컬렉션 구조**:

| 컬렉션 | 용도 | 비고 |
|---|---|---|
| `knowledge` | FAQ, 매뉴얼, 인사말 등 지식 문서 | owner·category·doc_type 메타데이터 |
| `qa_cache` | 시맨틱 캐시 (질문-답변 쌍) | TTL: FAQ 24h, 기타 1h |
| `persona` | 조직별 페르소나 정의 | owner당 1건 |

**카테고리**: `weather`, `disaster`, `observation`, `earthquake`, `special_report`, `greeting`, `farewell`, `help`, `faq` 등

---

## 3. 호(Call) 처리 흐름

### 3.1 전체 시퀀스

```
1. SIP INVITE 수신 → CallManager 세션 생성
2. RTPRelayWorker 할당 → RTP 채널 개설
3. run_ai_voice_pipeline() 호출
   a. WebSocket emit_call_started
   b. register_active_call
   c. PipelineBuilder.build_and_run()
      - Pipecat 파이프라인 조립
      - 초기 인사 전송 (0.5초 후)
      - 오디오 루프 시작 (StartFrame + 2초 폴백)
4. 대화 루프
   a. Caller RTP → STT → 텍스트
   b. RAGLLMProcessor → LangGraph Agent → 응답 텍스트
   c. 응답 텍스트 → TTS → PCM → RTP → Caller
5. SIP BYE 수신
   a. Pipecat 파이프라인 shutdown
   b. RTPRelayWorker.stop_pipecat_mode() (잔여 오디오 드레인)
   c. WebSocket emit_call_ended
   d. 통화 녹음 저장 + 지식 추출 (선택)
```

### 3.2 응답 시간 최적화

| 최적화 | 설명 | 효과 |
|---|---|---|
| classify_intent + rewrite_query 병합 | 단일 LLM 호출로 의도+쿼리 동시 생성 | LLM 1회 절감 (~0.5초) |
| greeting/farewell KB 직접 조회 | ChromaDB에서 직접 인사말 조회, LLM 스킵 | ~0.01초 응답 |
| 시맨틱 캐시 (qa_cache) | 유사 질문 재사용 (유사도 ≥ 0.85) | LLM+RAG 전체 스킵 |
| 빈 컬렉션 스킵 (check_cache) | qa_cache 비어있으면 벡터 검색 생략 | ~0.2초 절감 |
| step_back 최소화 | RAG 0건일 때만 재검색 | 불필요한 재검색 제거 |
| 스트리밍 LLM+TTS | 문장 단위 수집 → 점진적 TTS | TTFB 단축 |
| 필러 문구 자동 송출 | 처리 지연 시 대기 멘트 | 사용자 체감 대기 감소 |

---

## 4. 설정 구조 (config.yaml)

```yaml
ai_voicebot:
  enabled: true
  no_answer_timeout: 30
  greeting_message: "안녕하세요..."
  
  google_cloud:
    project: ...
    credentials_path: ...
    gemini:
      model: "gemini-2.5-flash"
      api_key: ...
      temperature: 0.3
      max_output_tokens: 256
    stt: { language_code: "ko-KR", model: "latest_long" }
    tts: { language_code: "ko-KR", voice_name: "ko-KR-Neural2-A" }
  
  rag:
    top_k: 10
    similarity_threshold: 0.15
    reranking_enabled: true
  
  hitl:
    timeout_seconds: 60
    timeout_message: "..."
    away_message: "..."
  
  vector_db:
    chromadb:
      persist_directory: "./data/chromadb"
  
  embedding:
    model: "all-MiniLM-L6-v2"
    dimension: 384
```

---

## 5. 관련 코드 위치

| 컴포넌트 | 파일 |
|---|---|
| 호 진입점 | `src/ai_voicebot/run_ai_call.py` |
| 파이프라인 빌드 | `src/ai_voicebot/pipecat/pipeline_builder.py` |
| RAGLLMProcessor | `src/ai_voicebot/pipecat/processors/rag_processor.py` |
| Input/Output Transport | `src/ai_voicebot/pipecat/rtp_transport.py` |
| TTS 서비스 | `src/ai_voicebot/pipecat/services/debug_google_tts.py` |
| LangGraph Agent | `src/ai_voicebot/langgraph/agent.py` |
| 의도 분류 | `src/ai_voicebot/langgraph/nodes/classify_intent.py` |
| RAG 검색 | `src/ai_voicebot/langgraph/nodes/adaptive_rag.py` |
| LLM 응답 생성 | `src/ai_voicebot/langgraph/nodes/generate_response.py` |
| HITL 판단 | `src/ai_voicebot/langgraph/nodes/hitl_alert.py` |
| RAG 엔진 | `src/ai_voicebot/ai_pipeline/rag_engine.py` |
| LLM 클라이언트 | `src/ai_voicebot/ai_pipeline/llm_client.py` |
| ChromaDB 클라이언트 | `src/ai_voicebot/knowledge/chromadb_client.py` |
| 지식 서비스 | `src/ai_voicebot/knowledge/knowledge_service.py` |
| 페르소나 서비스 | `src/ai_voicebot/knowledge/persona_service.py` |
| RTP 릴레이 | `src/media/rtp_relay.py` |
| 호 관리 | `src/sip_core/call_manager.py` |
| 팩토리 | `src/ai_voicebot/ai_pipeline/factory.py` |

---

## 6. 관련 설계서

| 문서 | 설명 |
|---|---|
| [TTS_RTP_AND_STT_QUEUE_DESIGN.md](TTS_RTP_AND_STT_QUEUE_DESIGN.md) | TTS→RTP 큐 및 STT 입력 큐 설계 |
| [INTENT_HANDLING_DESIGN.md](INTENT_HANDLING_DESIGN.md) | Intent별 처리 로직 상세 |
| [CHROMADB_CATEGORY_DESIGN.md](CHROMADB_CATEGORY_DESIGN.md) | ChromaDB 카테고리 설계 |
| [HITL_OPERATOR_RESPONSE_FLOW.md](HITL_OPERATOR_RESPONSE_FLOW.md) | HITL 운영자 응답 흐름 |
| [AI_RESPONSE_HUMANLIKE_DESIGN.md](AI_RESPONSE_HUMANLIKE_DESIGN.md) | 자연스러운 AI 응답 설계 |
