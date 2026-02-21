# Knowledge Extraction 고도화 기획안

> **문서 버전**: v1.0  
> **작성일**: 2026-01-29  
> **목적**: 유저 간 통화에서 LLM이 중요 정보를 판단하여 knowledge_base에 저장하는 기존 로직을 업계 최신 기술로 고도화

---

## 1. 현재 구현 분석

### 1.1 현행 파이프라인 흐름

```
통화 종료
  → SIPCallRecorder: RTP → WAV 녹음 저장
    → Google STT: WAV → transcript.txt (화자 분리)
      → 5초 대기 후 KnowledgeExtractor.extract_from_call() 호출
        → LLM judge_usefulness(): 유용성 판단 (0.0~1.0)
          → confidence ≥ 0.7 → 텍스트 청킹 → 임베딩 → VectorDB upsert
```

### 1.2 현행 구성 요소

| 구성 요소 | 현재 구현 | 위치 |
|-----------|----------|------|
| STT | Google Cloud STT (telephony 모델) | `sip_call_recorder.py` |
| 화자 분리 | `enable_diarization: true` | config.yaml |
| 유용성 판단 | 단일 LLM 호출 (judge_usefulness) | `llm_client.py` |
| 추출 카테고리 | 약속, 정보, 지시, 선호도, 기타 (5종) | LLM 프롬프트 하드코딩 |
| 청킹 | 고정 크기 500자 / 오버랩 50자 | `knowledge_extractor.py` |
| 중복 제거 | 없음 (doc_id 기반 덮어쓰기만) | - |
| 품질 검증 | confidence 임계값 (0.7) 1단계만 | - |
| 피드백 루프 | 없음 | - |

### 1.3 현행 한계점

1. **단일 LLM 판단**: 한 번의 프롬프트로 유용성 + 카테고리 + 키워드를 모두 결정 → 정확도 한계
2. **중복 저장 문제**: 같은 내용이 다른 통화에서 나오면 매번 별도 문서로 저장
3. **정형 정보 미추출**: 전화번호, 날짜, 주소 등 구조화된 엔티티 추출 없음
4. **피드백 없음**: 추출된 지식의 품질을 검증하거나 개선하는 루프 부재
5. **QA 쌍 미생성**: 대화를 질문-답변 쌍으로 변환하지 않아 RAG 검색 품질 저하
6. **환각 검증 없음**: LLM이 원문에 없는 내용을 추출 결과에 포함할 수 있음

---

## 2. 업계 벤치마크 분석

### 2.1 학술 연구 벤치마크

| 논문/기술 | 핵심 기법 | 성과 | 적용 포인트 |
|-----------|----------|------|------------|
| **AI Knowledge Assist** (EMNLP 2025 Industry) | 대화 → QA 쌍 추출 → 클러스터링 → 대표 QA 선정 | Fine-tuned LLaMA-3.1-8B로 90%+ 정확도 | QA 쌍 추출 파이프라인 도입 |
| **AUTOSUMM** (ACL 2025 Industry) | LLM 요약 + 환각 검증 (구문/의미/함의 3중 검증) | 94% 사실 일관성, 89% 무편집 통과 | 환각 검증 모듈 도입 |
| **Chain-of-Interactions** (EMNLP 2025) | 다단계 추출 → 자기 교정 → 평가 체인 | 엔티티 보존 6배, 품질 49% 향상 | 멀티스텝 추출 도입 |
| **Zero-shot Slot Filling** (COLING 2025) | Teacher LLM → 경량 모델 증류 + 슬롯 유도 | F1 +26% (vs 바닐라 LLM) | 구조화 엔티티 추출 |
| **LingVarBench** (2025) | 전화 대화 특화 엔티티 추출 (끊김, 중복 발화 대응) | 94~95% F1 (우편번호, 생년월일, 이름) | 전화 대화 특수성 대응 |

### 2.2 상용 플랫폼 벤치마크

| 플랫폼 | 아키텍처 특징 | 시사점 |
|--------|-------------|--------|
| **Cresta** (Forrester Leader) | 대화별 개별 분석 → 분류 체계 구성 → 결정론적 집계 + 인용 감사 추적 | 대화 단위 분석 + 메타 분류 체계 |
| **Observe.AI** (Gartner Vendor) | 멀티-LLM 아키텍처 (작업별 최적 모델 배정) | 판단/요약/추출에 서로 다른 모델 사용 |
| **Gong** (Gartner Leader) | 수십억 건 상호작용 학습, 99% 자동 캡처 | 대규모 피드백 루프 |

### 2.3 Agent-in-the-Loop 프레임워크 (AITL, 2025)

```
대화 수집 → 추출 → 운영자 피드백 → 모델 개선 → 반복
```

| 피드백 채널 | 설명 | 개선 효과 |
|------------|------|----------|
| 쌍대 응답 선호도 | 운영자가 두 응답 중 더 좋은 것 선택 | 생성 품질 +8.4% |
| 채택 및 근거 | 운영자가 추천을 채택했는지 + 이유 | 채택률 +4.5% |
| 지식 관련성 체크 | 검색된 지식이 실제 관련있는지 평가 | 검색 정밀도 +14.8% |
| 누락 지식 식별 | "이 질문에 답할 지식이 없었다" 표시 | 검색 재현율 +11.7% |

---

## 3. 고도화 설계

### 3.1 신규 파이프라인 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Knowledge Extraction Pipeline v2                  │
│                                                                     │
│  ┌─── Stage 1: 전처리 ───┐                                          │
│  │ STT + 화자 분리        │                                          │
│  │ 대화 세그먼트 분할      │                                          │
│  └──────────┬────────────┘                                          │
│             ▼                                                       │
│  ┌─── Stage 2: 멀티스텝 추출 ───────────────────────────────┐       │
│  │                                                          │       │
│  │  Step 1: 요약 (Summarizer)                               │       │
│  │    └→ 대화 전체를 3~5문장으로 요약                         │       │
│  │                                                          │       │
│  │  Step 2: QA 쌍 추출 (QA Extractor)                       │       │
│  │    └→ 대화에서 질문-답변 쌍 추출                            │       │
│  │                                                          │       │
│  │  Step 3: 엔티티 추출 (Entity Extractor)                   │       │
│  │    └→ 전화번호, 날짜, 주소, 이름, 금액 등 정형 데이터        │       │
│  │                                                          │       │
│  │  Step 4: 유용성 판단 (Usefulness Judge)                   │       │
│  │    └→ 각 추출물의 유용성 + 신뢰도 + 카테고리 판단            │       │
│  │                                                          │       │
│  └───────────────────────┬──────────────────────────────────┘       │
│                          ▼                                          │
│  ┌─── Stage 3: 품질 검증 ─────────────────────────┐                 │
│  │                                                 │                │
│  │  ✅ 환각 검증 (Hallucination Check)              │                │
│  │    └→ 추출 결과가 원문에 근거하는지 교차 검증       │                │
│  │                                                 │                │
│  │  ✅ 중복 검증 (Deduplication)                     │                │
│  │    └→ VectorDB 유사도 검색 (cosine ≥ 0.92 → 병합) │                │
│  │                                                 │                │
│  │  ✅ 최소 품질 필터 (Quality Gate)                  │                │
│  │    └→ confidence < 0.7 → 폐기                     │                │
│  │    └→ 텍스트 길이 < 10자 → 폐기                    │                │
│  │                                                 │                │
│  └─────────────────┬───────────────────────────────┘                │
│                    ▼                                                │
│  ┌─── Stage 4: 저장 + 메타데이터 ──┐                                │
│  │                                 │                                │
│  │  VectorDB upsert               │                                │
│  │  • doc_type: knowledge / qa    │                                │
│  │  • extraction_source: call     │                                │
│  │  • extraction_call_id          │                                │
│  │  • confidence_score            │                                │
│  │  • review_status: pending      │                                │
│  │                                │                                │
│  └────────────────┬────────────────┘                                │
│                   ▼                                                 │
│  ┌─── Stage 5: 피드백 루프 ────────┐                                │
│  │                                 │                                │
│  │  운영자 대시보드에서:            │                                │
│  │  • 승인 / 수정 / 거절            │                                │
│  │  • 카테고리 교정                 │                                │
│  │  • 누락 지식 보고                │                                │
│  │                                 │                                │
│  └─────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Stage별 상세 설계

#### Stage 1: 전처리 (기존 유지 + 세그먼트 분할 추가)

현행 STT + 화자 분리를 유지하되, **대화 세그먼트(topic shift)** 분할을 추가합니다.

```python
class ConversationSegmenter:
    """대화를 토픽 단위 세그먼트로 분할"""
    
    async def segment(self, transcript: str) -> List[Segment]:
        """
        LLM으로 대화를 의미 단위로 분할
        
        Returns:
            [
                Segment(topic="약속 잡기", lines=[...], start_idx=0, end_idx=5),
                Segment(topic="메뉴 문의", lines=[...], start_idx=6, end_idx=12),
            ]
        """
```

**근거**: Cresta는 대화를 토픽 단위로 분할 후 각 세그먼트를 개별 분석하여 정확도 향상.

#### Stage 2: 멀티스텝 추출 (신규 - Chain-of-Interactions 참조)

현행 단일 `judge_usefulness()` 호출을 **4단계 체인**으로 분리합니다.

```python
class ExtractionPipeline:
    """멀티스텝 지식 추출 파이프라인"""
    
    async def extract(self, transcript: str, call_id: str) -> ExtractionResult:
        # Step 1: 요약
        summary = await self.summarizer.summarize(transcript)
        
        # Step 2: QA 쌍 추출
        qa_pairs = await self.qa_extractor.extract(transcript)
        
        # Step 3: 엔티티 추출
        entities = await self.entity_extractor.extract(transcript)
        
        # Step 4: 유용성 판단 (요약/QA/엔티티 각각에 대해)
        results = await self.judge.evaluate_all(summary, qa_pairs, entities)
        
        return results
```

| Step | LLM 호출 | 입력 | 출력 |
|------|---------|------|------|
| Summarizer | 1회 | transcript 전문 | 3~5문장 요약 |
| QA Extractor | 1회 | transcript 전문 | QA 쌍 리스트 `[{q, a, context}]` |
| Entity Extractor | 1회 | transcript 전문 | 엔티티 리스트 `[{type, value, context}]` |
| Usefulness Judge | 1회 | 위 3개 결과 | 각 항목별 `{is_useful, confidence, category}` |

**총 LLM 호출**: 4회 (현행 1회 → 4회로 증가하지만, 각 호출이 단일 역할에 집중하여 정확도 대폭 향상)

**근거**: Chain-of-Interactions (EMNLP 2025)에서 다단계 추출이 엔티티 보존 6배, 품질 49% 향상 입증.

#### Stage 2-1: QA 쌍 추출 프롬프트 (AI Knowledge Assist 참조)

```
다음 통화 대화에서 질문-답변(QA) 쌍을 추출하세요.

규칙:
1. 정보를 요청하는 발화 → 질문(Q)
2. 해당 정보를 제공하는 발화 → 답변(A)
3. 암묵적 질문도 포함 (예: "거기 주차장 있어?" → Q, "네 지하에 있어요" → A)
4. 동일 토픽의 여러 교환은 하나의 QA로 합산

통화 내용:
{transcript}

출력 형식 (JSON 배열):
[
  {
    "question": "자연어 질문",
    "answer": "자연어 답변",
    "context": "질문이 나온 맥락 (1문장)",
    "source_speaker": "caller|callee"
  }
]
```

**근거**: AI Knowledge Assist (EMNLP 2025 Industry)에서 대화 → QA 쌍 변환이 RAG 검색 품질을 크게 개선함을 입증.

#### Stage 2-2: 엔티티 추출 스키마

```python
class ExtractedEntity(BaseModel):
    """추출된 정형 엔티티"""
    entity_type: Literal[
        "phone_number",     # 전화번호
        "date",             # 날짜/시간
        "address",          # 주소
        "person_name",      # 인명
        "amount",           # 금액
        "organization",     # 기관/회사명
        "appointment",      # 약속 (날짜+장소+참석자)
        "instruction",      # 업무 지시
        "preference",       # 개인 선호도
    ]
    value: str              # 추출된 값
    normalized: Optional[str]  # 정규화된 값 (예: "내일 오후 3시" → "2026-01-30T15:00")
    context: str            # 원문 맥락 (전후 1문장)
    confidence: float       # 0.0 ~ 1.0
    speaker: str            # caller / callee
```

**근거**: LingVarBench (2025)에서 전화 대화 특화 엔티티 추출이 94~95% F1 달성.

#### Stage 3: 품질 검증

##### 3-1. 환각 검증 (Hallucination Check)

```python
class HallucinationChecker:
    """추출 결과가 원문에 근거하는지 검증 (AUTOSUMM 참조)"""
    
    async def check(self, extracted: str, original: str) -> HallucinationResult:
        """
        3중 검증:
        1. 구문 검증: 추출 텍스트의 핵심 명사/동사가 원문에 존재하는지
        2. 의미 검증: 추출 텍스트 임베딩과 원문 임베딩의 코사인 유사도
        3. 함의 검증: LLM에게 "원문이 추출 결과를 함의하는지" 판단 요청
        """
```

| 검증 단계 | 방법 | 임계값 | 비용 |
|----------|------|--------|------|
| 구문 검증 | 키워드 매칭 (TF-IDF) | 핵심 키워드 60%+ 매칭 | 0원 |
| 의미 검증 | 임베딩 코사인 유사도 | cosine ≥ 0.75 | 임베딩 비용만 |
| 함의 검증 | LLM 호출 | "yes" 판정 | LLM 1회 호출 |

**비용 최적화**: 구문 → 의미 → 함의 순서로 실행하며, 앞 단계에서 탈락하면 이후 단계 스킵.

**근거**: AUTOSUMM (ACL 2025)에서 3중 검증으로 94% 사실 일관성 달성, 89% 무편집 통과.

##### 3-2. 중복 검증 (Semantic Deduplication)

```python
class SemanticDeduplicator:
    """VectorDB 기반 의미적 중복 검사"""
    
    DUPLICATE_THRESHOLD = 0.92     # cosine similarity ≥ 0.92 → 중복
    NEAR_DUPLICATE_THRESHOLD = 0.85  # 0.85 ≤ sim < 0.92 → 유사 (병합 후보)
    
    async def check(self, text: str, embedding: List[float]) -> DeduplicationResult:
        """
        1. VectorDB에서 유사 문서 top-3 검색
        2. 유사도 ≥ 0.92 → 중복으로 판정, 기존 문서에 usage_count 증가
        3. 유사도 0.85~0.92 → 병합 후보로 표시 (운영자 리뷰)
        4. 유사도 < 0.85 → 새 문서로 저장
        """
```

**임계값 선정 근거**:
- 0.92: 업계 일반적인 near-duplicate 기준 (paraphrase-multilingual-mpnet-base-v2 기준)
- 0.85: "관련성 높지만 새 정보 포함" 경계값

##### 3-3. 품질 필터 (Quality Gate)

```python
class QualityGate:
    """추출물 최종 품질 필터"""
    
    rules = [
        Rule("min_confidence", lambda x: x.confidence >= 0.7),
        Rule("min_text_length", lambda x: len(x.text) >= 10),
        Rule("max_text_length", lambda x: len(x.text) <= 2000),
        Rule("not_greeting", lambda x: not is_greeting_only(x.text)),
        Rule("has_information", lambda x: x.category != "기타" or x.confidence >= 0.85),
        Rule("hallucination_pass", lambda x: x.hallucination_check.passed),
    ]
```

#### Stage 4: 저장 메타데이터 확장

현재 메타데이터를 확장하여 추적 가능성과 검색 품질을 향상합니다.

```python
# 현행 메타데이터
{
    "category": "약속",
    "keywords": "키워드1,키워드2",
    "source": "call"
}

# 신규 메타데이터 (확장)
{
    # 기본
    "doc_type": "knowledge" | "qa_pair" | "entity",
    "category": "약속|정보|지시|선호도|FAQ|...",
    "keywords": "키워드1,키워드2",
    
    # 추출 출처
    "extraction_source": "call",
    "extraction_call_id": "call_abc123",
    "extraction_timestamp": "2026-01-29T14:30:00",
    "extraction_pipeline_version": "v2",
    
    # 품질 지표
    "confidence_score": 0.87,
    "hallucination_check": "passed",  # passed | flagged | failed
    "dedup_status": "unique",          # unique | merged | duplicate
    "merged_with": null,               # 병합 대상 doc_id (있을 경우)
    
    # 리뷰 상태
    "review_status": "pending",        # pending | approved | rejected | edited
    "reviewed_by": null,
    "reviewed_at": null,
    
    # 활용 추적
    "usage_count": 0,
    "last_used_at": null,
    "useful_feedback_count": 0,        # 운영자/사용자 "유용" 피드백 수
    
    # QA 쌍 전용 (doc_type == "qa_pair")
    "question": "자연어 질문",
    "source_speaker": "caller|callee",
    
    # 엔티티 전용 (doc_type == "entity")
    "entity_type": "phone_number|date|...",
    "normalized_value": "정규화 값",
    "entity_speaker": "caller|callee",
}
```

#### Stage 5: 피드백 루프 (AITL 프레임워크 참조)

```
┌───────────────────────────────────────────────────────────────┐
│                    Feedback Loop (AITL)                       │
│                                                              │
│  ① 추출 결과 리뷰 대시보드                                    │
│     • review_status: pending 항목 목록                        │
│     • 원문 대화 보기 + 추출 결과 비교                          │
│     • [승인] [수정] [거절] 버튼                               │
│                                                              │
│  ② 자동 승인 규칙                                             │
│     • confidence ≥ 0.9 + hallucination_pass → 자동 승인       │
│     • 동일 패턴이 3회 이상 승인됨 → 이후 자동 승인             │
│                                                              │
│  ③ 누락 지식 보고                                             │
│     • AI가 답변 못한 질문 자동 수집                            │
│     • 운영자가 "이 지식이 필요합니다" 표시                     │
│     • 다음 추출 시 해당 토픽 가중치 증가                       │
│                                                              │
│  ④ 주기적 품질 리포트                                         │
│     • 주간: 추출 건수, 승인률, 거절 사유 통계                  │
│     • 자동 임계값 조정 제안                                    │
│                                                              │
└───────────────────────────────────────────────────────────────┘
```

**근거**: AITL (2025)에서 4채널 피드백 루프가 검색 재현율 +11.7%, 정밀도 +14.8%, 생성 품질 +8.4% 달성.

---

## 4. VectorDB 스키마 변경

### 4.1 doc_type 확장

| doc_type | 설명 | 현행 | 신규 |
|----------|------|------|------|
| `capability` | AI 서비스 항목 | ✅ (이전 기획) | 유지 |
| `knowledge` | 일반 지식 | ✅ | 유지 |
| `qa_pair` | QA 쌍 (질문+답변) | - | ✅ 신규 |
| `entity` | 정형 엔티티 | - | ✅ 신규 |
| `faq` | FAQ | ✅ | 유지 |

### 4.2 extraction_source 필드

| 값 | 설명 |
|----|------|
| `call` | 유저 간 통화에서 자동 추출 |
| `ai_call` | AI 통화에서 자동 추출 |
| `manual` | 운영자 수동 입력 |
| `seed` | 초기 시딩 데이터 |
| `hitl` | HITL 저장 |
| `import` | 외부 데이터 임포트 |

---

## 5. Backend 변경 사항

### 5.1 신규 클래스/모듈

```
src/ai_voicebot/knowledge/
├── knowledge_extractor.py        # 기존 → 리팩토링 (Pipeline v2 진입점)
├── extraction_pipeline.py        # ✅ 신규: ExtractionPipeline (4-step 오케스트레이터)
├── summarizer.py                 # ✅ 신규: ConversationSummarizer
├── qa_extractor.py               # ✅ 신규: QAPairExtractor
├── entity_extractor.py           # ✅ 신규: EntityExtractor
├── hallucination_checker.py      # ✅ 신규: HallucinationChecker
├── semantic_deduplicator.py      # ✅ 신규: SemanticDeduplicator
├── quality_gate.py               # ✅ 신규: QualityGate
└── conversation_segmenter.py     # ✅ 신규: ConversationSegmenter
```

### 5.2 API 변경/추가

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/extractions` | GET | 추출 이력 조회 (review_status 필터) |
| `/api/extractions/{id}/review` | PATCH | 리뷰 상태 변경 (approve/reject/edit) |
| `/api/extractions/stats` | GET | 추출 통계 (건수, 승인률, 카테고리별) |
| `/api/extractions/settings` | GET/PUT | 추출 설정 조회/변경 |
| `/api/knowledge?doc_type=qa_pair` | GET | doc_type 필터 추가 |

### 5.3 config.yaml 변경

```yaml
ai_voicebot:
  # 기존 설정 유지...
  
  # Knowledge Extraction v2 (신규)
  knowledge_extraction:
    enabled: true
    version: "v2"                    # v1 (기존) | v2 (멀티스텝)
    
    # 추출 스텝 설정
    steps:
      summarize: true                # Step 1: 요약
      qa_extract: true               # Step 2: QA 쌍 추출
      entity_extract: true           # Step 3: 엔티티 추출
    
    # 품질 검증
    quality:
      min_confidence: 0.7            # 최소 신뢰도
      hallucination_check: true      # 환각 검증 활성화
      deduplication: true            # 중복 검증 활성화
      dedup_threshold: 0.92          # 중복 판정 코사인 유사도
      near_dedup_threshold: 0.85     # 병합 후보 코사인 유사도
    
    # 자동 승인
    auto_approve:
      enabled: true
      min_confidence: 0.9            # 자동 승인 최소 신뢰도
      require_hallucination_pass: true
    
    # 청킹
    chunk_size: 500
    chunk_overlap: 50
    min_text_length: 10
    
    # 비용 제어
    max_llm_calls_per_extraction: 6  # 추출당 최대 LLM 호출 수
    skip_short_calls_seconds: 30     # 30초 미만 통화 스킵
```

---

## 6. Frontend 변경 사항

### 6.1 추출 리뷰 대시보드 (`/extractions`)

```
┌──────────────────────────────────────────────────────────────────┐
│  📋 지식 추출 리뷰                                    [설정] [통계] │
│──────────────────────────────────────────────────────────────────│
│  필터: [대기중 ▼]  [전체 유형 ▼]  [전체 기간 ▼]     검색: [____]  │
│──────────────────────────────────────────────────────────────────│
│                                                                  │
│  ┌─ 대기중 리뷰 (12건) ─────────────────────────────────────────┐ │
│  │                                                              │ │
│  │  🟡 QA 쌍 · 통화 #A3F2 · 신뢰도 0.87 · 1시간 전            │ │
│  │  Q: "거기 주차장 있어요?"                                    │ │
│  │  A: "네, 지하 1~3층에 있고 2시간 무료입니다."                 │ │
│  │  📎 원문 보기                                                │ │
│  │                         [✅ 승인] [✏️ 수정] [❌ 거절]         │ │
│  │──────────────────────────────────────────────────────────────│ │
│  │                                                              │ │
│  │  🟡 엔티티 · 통화 #B7D1 · 신뢰도 0.92 · 2시간 전            │ │
│  │  📞 전화번호: 02-1234-5678 (홍길동 부장)                      │ │
│  │  📎 원문 보기                                                │ │
│  │                         [✅ 승인] [✏️ 수정] [❌ 거절]         │ │
│  │──────────────────────────────────────────────────────────────│ │
│  │                                                              │ │
│  │  🟢 지식 · 통화 #C9E3 · 신뢰도 0.94 · 자동 승인됨            │ │
│  │  "매주 금요일 오후 3시에 팀 회의가 있습니다."                   │ │
│  │  카테고리: 약속 · 키워드: 회의, 금요일                        │ │
│  │                                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ── 통계 위젯 ──                                                 │
│  [전체 847건] [자동승인 612건] [수동승인 189건] [거절 46건]       │
│  [승인률 94.6%] [평균 신뢰도 0.86]                               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 원문 대화 비교 뷰 (다이얼로그)

```
┌────────────────────────────────────────────────────────────────┐
│  📞 통화 #A3F2 원문                              [닫기]        │
│────────────────────────────────────────────────────────────────│
│                                                                │
│  발신자: 안녕하세요, 거기 주차장 있어요?                        │
│  착신자: 네 안녕하세요. 지하 1층부터 3층까지 고객 전용           │
│          주차장이 있습니다.                                     │
│  발신자: 무료인가요?                                            │
│  착신자: 2시간까지 무료이고 그 이후는 30분에 천원입니다.         │
│  발신자: 아 그렇군요 감사합니다.                                │
│                                                                │
│  ── 추출 결과 (하이라이트) ──                                   │
│  🟡 [Q] "거기 주차장 있어요?" + "무료인가요?"                    │
│  🟢 [A] "지하 1~3층... 2시간 무료... 30분에 천원"               │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 6.3 추출 설정 페이지 (`/extractions/settings`)

- 추출 스텝 on/off 토글 (요약, QA, 엔티티)
- 품질 임계값 슬라이더 (신뢰도, 중복 유사도)
- 자동 승인 규칙 설정
- 짧은 통화 스킵 설정

### 6.4 네비게이션 추가

대시보드 상단 내비게이션에 "지식 추출" 링크 추가:

```
대시보드 | AI 서비스 | 지식 베이스 | 지식 추출 | 통화 이력
```

---

## 7. 비용 분석

### 7.1 LLM 호출 비용 (Gemini 2.5 Flash 기준)

| 파이프라인 | LLM 호출 수/통화 | 입력 토큰 | 출력 토큰 | 비용/통화 |
|-----------|-----------------|----------|----------|----------|
| v1 (현행) | 1회 | ~1,000 | ~300 | ~₩0.15 |
| v2 (신규) | 4~6회 | ~4,000 | ~1,500 | ~₩0.60 |

| 월 통화량 | v1 월 비용 | v2 월 비용 | 차이 |
|----------|-----------|-----------|------|
| 100통 | ₩15 | ₩60 | +₩45 |
| 1,000통 | ₩150 | ₩600 | +₩450 |
| 10,000통 | ₩1,500 | ₩6,000 | +₩4,500 |

**결론**: Gemini Flash 기준 비용 증가는 미미 (만 통화/월에도 ₩6,000 수준). 품질 향상 대비 합리적.

### 7.2 비용 최적화 전략

1. **짧은 통화 스킵**: 30초 미만 통화는 추출 스킵 (부재중, 오다이얼 등)
2. **환각 검증 계단식**: 구문 → 의미 → 함의 순서, 앞 단계 실패 시 뒷 단계 스킵
3. **자동 승인**: confidence ≥ 0.9 건은 LLM 추가 검증 없이 바로 저장
4. **캐시**: 동일 transcript에 대한 중복 추출 방지

---

## 8. 구현 우선순위

### Phase 1: 핵심 파이프라인 (1주)
- [ ] `ExtractionPipeline` 클래스 (4-step 오케스트레이터)
- [ ] `QAPairExtractor` (QA 쌍 추출)
- [ ] `SemanticDeduplicator` (중복 검증)
- [ ] 메타데이터 확장 (doc_type, review_status 등)
- [ ] `config.yaml` v2 설정 추가

### Phase 2: 품질 검증 (1주)
- [ ] `HallucinationChecker` (3중 환각 검증)
- [ ] `EntityExtractor` (정형 엔티티 추출)
- [ ] `QualityGate` (품질 필터 규칙 엔진)
- [ ] `ConversationSummarizer` (대화 요약)

### Phase 3: Frontend 리뷰 (1주)
- [ ] `/extractions` 리뷰 대시보드 페이지
- [ ] 원문 대화 비교 뷰
- [ ] 리뷰 API (approve/reject/edit)
- [ ] 네비게이션 업데이트

### Phase 4: 피드백 루프 (1주)
- [ ] 자동 승인 규칙 엔진
- [ ] 추출 통계 대시보드
- [ ] 누락 지식 보고 기능
- [ ] 설정 페이지 (`/extractions/settings`)

---

## 9. 기대 효과

| 지표 | 현행 (v1) | 목표 (v2) | 근거 |
|------|----------|----------|------|
| 추출 정확도 | ~70% (추정) | 90%+ | AI Knowledge Assist 벤치마크 |
| 엔티티 보존율 | 단일 텍스트만 | 6배 향상 | Chain-of-Interactions |
| 환각 발생률 | 미측정 | <6% | AUTOSUMM 94% 사실 일관성 |
| 중복 저장률 | 높음 (제어 없음) | <5% | 의미적 중복 검증 도입 |
| 운영자 편집률 | 미측정 | <11% | AUTOSUMM 89% 무편집 |
| RAG 검색 품질 | 텍스트 청크 기반 | QA 쌍 기반 향상 | QA 구조가 검색에 유리 |

---

## 10. 참고 문헌

1. **AI Knowledge Assist** - EMNLP 2025 Industry Track: 대화 → QA 쌍 추출 파이프라인
2. **AUTOSUMM** - ACL 2025 Industry Track: LLM 요약 + 3중 환각 검증 프레임워크
3. **Chain-of-Interactions** - EMNLP 2025 Findings: 다단계 대화 요약 및 추출
4. **Zero-shot Slot Filling** - COLING 2025: 대화 슬롯 추출 + 지식 증류
5. **LingVarBench** - 2025: 전화 대화 엔티티 추출 벤치마크
6. **Agent-in-the-Loop (AITL)** - 2025: 4채널 피드백 루프 프레임워크
7. **Cresta AI Analyst** - 2025: 대화별 분석 + 분류 체계 + 결정론적 집계
8. **Observe.AI** - 2025: 멀티-LLM 아키텍처 (작업별 최적 모델)
