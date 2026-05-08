# AI 비서 “사람처럼 응대” 고도화 설계
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`INTENT_HANDLING_DESIGN.md`](INTENT_HANDLING_DESIGN.md)
>
---


## 1. 목표 및 범위

### 1.1 목표

- **현재**: 단순 질문–응답 위주. "오늘 날씨 좋은것같아", "네", "감사해요", "다시 말해줘" 등이 모두 **question**으로 처리되어 RAG·LLM에 일괄 위임됨.
- **목표**: 사람처럼 **맞장구·반응·일상 대화·제어(반복/명확화/도움)** 를 구분하고, 의도별로 적절한 짧은 응답 또는 기존 RAG/LLM 경로를 선택하도록 고도화.

### 1.2 범위

- **대상**: LangGraph 대화 에이전트(의도 분류 → 캐시 → RAG → 응답 생성 → HITL → 상태 갱신).
- **변경**: 의도 택소노미 확장, 라우팅 규칙 확장, **템플릿 기반 응답** 경로 추가, repeat/clarification/help 전용 처리. 기존 question/complaint/transfer/farewell 동작은 유지·보완.
- **비범위**: STT/TTS/RTP, 인사말 Phase1·Phase2, HITL 프로토콜 자체 변경은 본 설계 범위 밖.

---

## 2. 확장 Intent 택소노미

리서치 문서(`INTENT_TAXONOMY_RESEARCH.md`) 제안을 반영한 확장 의도 집합.

### 2.1 그룹 정의

| 그룹 | Intent | 설명 | 응답 전략 |
|------|--------|------|------------|
| **A. 시작/종료** | greeting | 인사, 처음 말걸기 | 기존: 인사/안내 (캐시 스킵 → generate_response) |
| | farewell | 끝인사, 통화 종료 | 기존: update_state → closing_template |
| **B. 반응/피드백** | affirm | 동의·확인 (네, 맞아요, 좋아요, 됐어요) | **템플릿**: 짧은 확인 + "더 필요하시면 말씀해 주세요" |
| | deny | 거절·취소 (아니요, 필요 없어요) | **템플릿**: "알겠습니다. 다른 건 도와드릴까요?" |
| | gratitude | 감사 (감사해요, 고마워요) | **템플릿**: "천만에요. 더 필요하시면 말씀해 주세요." |
| | doubt | 애매함 (글쎄요, 아마, 잘 모르겠어요) | **템플릿**: "괜찮아요. 정하시면 말씀해 주세요." |
| | positive_reaction | 긍정 반응 (좋아요, 맘에 들어요) | **템플릿**: 짧은 공감 + 서비스 안내 |
| | negative_reaction | 부정 반응 (별로예요, 안 좋아요) | **템플릿**: 공감 + 대안/담당자 연결 제안 |
| **C. 일상/제어** | chitchat | 일상 말걸기 (질문 아님) | **선택 RAG** 또는 짧은 LLM; 공감 + 안내 |
| | repeat | 다시 말해줘, 뭐라고? | **컨텍스트**: 이전 AI 발화 재안내 또는 요약 |
| | clarification | 무슨 뜻이에요? | **컨텍스트**: 이전 발화 요약 + 명확화 질문 |
| | help | 도와줘, 어떻게 해요? | **capability 안내**: 기관 제공 기능 목록 |
| **D. 업무** | question | 사실·서비스 질문·요청 | **기존**: check_cache → RAG → generate_response |
| | complaint | 불만·항의 | **기존** + HITL 조건 |
| | transfer | 담당자 연결 요청 | **기존**: 연결 플로우 |
| **E. 폴백** | out_of_scope | 업무 무관·저신뢰도 | 고정 멘트 또는 HITL |
| | nlu_fallback | 분류 confidence 낮음 | 재질문 또는 out_of_scope와 동일 |

### 2.2 Intent 값 집합 (코드 상수)

구현 시 사용할 **valid_intents**:

```text
greeting, farewell,
affirm, deny, gratitude, doubt, positive_reaction, negative_reaction,
chitchat, repeat, clarification, help,
question, complaint, transfer,
out_of_scope, nlu_fallback
```

- **unknown**은 기존과 같이 내부적으로만 사용하고, 라우팅 시에는 **question** 또는 **nlu_fallback**으로 매핑하는 것을 권장.

---

## 3. 아키텍처 개요

### 3.1 현재 흐름 (참고)

```text
classify_intent
  → farewell → update_state [response=closing] → END
  → greeting  → generate_response (RAG 없음)   → hitl_alert → update_cache → update_state → END
  → else      → check_cache → [hit] update_state / [miss] rewrite_query → adaptive_rag → generate_response → ...
```

### 3.2 변경 후 흐름 (제안)

```text
classify_intent
  → farewell           → update_state [response=closing] → END
  → greeting           → generate_response (기존)        → ...
  → affirm | deny | gratitude | doubt | positive_reaction | negative_reaction
                        → template_response (신규 노드)   → update_state → END  [캐시/RAG/LLM 스킵]
  → repeat             → repeat_response (신규 노드)    → update_state → END  [이전 발화 반환]
  → clarification       → clarification_response (신규)  → update_state → END [이전 발화 요약 + 질문]
  → help                → help_response (신규)           → update_state → END [capability 안내]
  → chitchat            → generate_response (RAG 선택적·경량) → ...
  → question | complaint | transfer
                        → check_cache → ... (기존)
  → out_of_scope | nlu_fallback
                        → fallback_response (고정 멘트 또는 HITL) → update_state → END
```

- **template_response**: 그룹 B 반응/피드백용. intent별 고정/랜덤 템플릿에서 1문장 선택.
- **repeat_response**: state.messages에서 마지막 assistant 발화를 response로 설정. 없으면 "죄송해요, 방금 말씀드린 내용을 다시 안내드릴게요." 등.
- **clarification_response**: 마지막 assistant 발화 요약 + "어느 부분이 궁금하신가요?" 또는 LLM 1문장.
- **help_response**: org_manager.get_capabilities() 또는 tenant_config 기반 안내 문장 생성.
- **fallback_response**: "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." 또는 needs_human=True로 HITL 유도.

### 3.3 그래프 변경 요약

- **노드 추가**: `template_response`, `repeat_response`, `clarification_response`, `help_response`, `fallback_response`.  
  (구현 단순화를 위해 **template_response** 하나로 B 그룹 전부 처리하고, repeat/clarification/help는 각각 별도 노드 또는 **template_response** 내에서 intent별 분기로 처리할 수 있음.)
- **라우팅**: `_route_after_intent`에서 반환하는 다음 노드 이름을 확장.  
  - 예: `template_response`, `repeat_response`, `clarification_response`, `help_response`, `fallback_response`, `generate_response`, `check_cache`, `update_state`.
- **엣지**:  
  - template/repeat/clarification/help/fallback → **update_state** → END (캐시·RAG·hitl_alert 스킵).  
  - update_state에서 이들 intent일 때는 **response**가 이미 채워진 상태이므로, update_state_node는 기존처럼 business_state·turn_count만 갱신하고 response는 그대로 전달.

---

## 4. 의도별 처리 상세

### 4.1 그룹 B — 반응/피드백 (템플릿 응답)

| Intent | 응답 템플릿 예시 (랜덤 1개) |
|--------|-----------------------------|
| affirm | "네, 알겠습니다. 더 필요하시면 말씀해 주세요.", "좋습니다. 다른 궁금한 점 있으시면 말씀해 주세요." |
| deny | "알겠습니다. 다른 건 도와드릴까요?", "네, 그럼 필요하실 때 말씀해 주세요." |
| gratitude | "천만에요. 더 필요하시면 말씀해 주세요.", "도움이 되었다니 다행이에요. 좋은 하루 되세요." |
| doubt | "괜찮아요. 정하시면 말씀해 주세요.", "네, 필요하실 때 다시 말씀해 주세요." |
| positive_reaction | "감사합니다. 더 궁금하신 점 있으시면 편하게 말씀해 주세요.", "도움이 되셨다니 좋겠어요. 다른 문의 있으시면 말씀해 주세요." |
| negative_reaction | "불편을 드려 죄송합니다. 다른 방법으로 안내해 드릴까요?", "그렇군요. 담당자 연결이 필요하시면 말씀해 주세요." |

- **데이터 소스**: 설정 파일(예: `intent_templates.yaml`) 또는 코드 내 상수 딕셔너리. 테넌트별 오버라이드는 Phase 2에서 검토.

### 4.2 그룹 C — repeat / clarification / help

- **repeat**  
  - `state["messages"]`에서 마지막 `role=="assistant"`인 항목의 `content`를 `state["response"]`에 설정.  
  - 없으면: "방금 말씀드린 내용을 다시 안내드릴게요." + (가능하면 직전 답변 요약 1문장).

- **clarification**  
  - 직전 assistant 발화가 있으면 그 요약(1문장) + "어느 부분이 궁금하신가요?" 또는 "제가 ○○ 말씀드렸는데, 더 알고 싶으신 게 있으신가요?"  
  - 없으면: "어떤 점이 궁금하신지 조금만 더 말씀해 주시면 안내해 드릴게요."

- **help**  
  - `org_manager.get_capabilities()` 결과를 문장으로 포맷 (예: "저는 ○○, △△, □□ 안내를 드릴 수 있어요. 무엇이 궁금하신가요?")  
  - 기존 Phase2 인사말(capability guide)과 유사한 문장 재사용 가능.

### 4.3 chitchat

- **라우팅**: RAG를 **선택적** 사용.  
  - 옵션 A: RAG 1회 검색, top_k=1~2, score 임계치 높게 두고 걸리면 짧게 활용; 안 걸리면 "네, 좋은 하루 되세요. 더 궁금하시면 말씀해 주세요." 수준의 짧은 문장만 생성.  
  - 옵션 B: RAG 스킵하고, system prompt에 "일상 말걸기에는 1~2문장으로 짧게 공감·안내만 하세요" 규칙을 두고 generate_response 호출.  
- **confidence**: 0.9 등 고정하여 HITL가 불필요하게 트리거되지 않도록 함.

### 4.4 out_of_scope / nlu_fallback

- **응답**: 기존 고정 멘트 "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요."  
- **옵션**: 설정 또는 confidence에 따라 `needs_human=True`로 HITL 요청을 보내도록 할 수 있음.

---

## 5. HITL 연동 (의도별 HITL 필요 시)

HITL이 필요한 intent인 경우, **generate_response → hitl_alert** 경로를 타는지, **템플릿/폴백 경로**를 타더라도 `needs_human`·`hitl_reason`을 설정해 그래프 결과에 반영해야 한다.

### 5.1 의도별 HITL 필요 여부 및 조건

| Intent | HITL 필요 | 조건 | 비고 |
|--------|-----------|------|------|
| **transfer** | **항상** | 무조건 | 고객이 담당자 연결을 요청한 경우. |
| **complaint** | 조건부 | confidence < 0.5 | 불만 + 답변 신뢰도 낮을 때. (기존 hitl_alert 로직 유지) |
| **question** 등 (RAG 경로) | 조건부 | needs_follow_up=True | AI가 "모르는 내용"으로 응답한 경우. |
| **question** 등 (RAG 경로) | 조건부 | confidence < 0.3 | 극도로 낮은 신뢰도. (기존 hitl_alert 로직 유지) |
| **out_of_scope** | 선택(설정) | 설정 또는 confidence | "확인 필요" 멘트 + 운영자 확인이 필요한 경우. |
| **nlu_fallback** | 선택(설정) | 설정 또는 confidence | 의도 분류 불명 시 HITL 유도 옵션. |
| **negative_reaction** | 선택(설정) | "담당자 연결해 줘" 등 명시적 요청 패턴 | 강한 불만 + 연결 요청 시 transfer와 동일 처리 가능. |
| 그 외 (affirm, deny, gratitude, repeat, clarification, help, chitchat 등) | 불필요 | — | 템플릿/경량 응답만으로 처리. |

- **transfer**: 현재처럼 `check_cache` → … → `generate_response` → **hitl_alert**를 타면 hitl_alert에서 `intent == "transfer"`로 `needs_human=True` 설정. 또는 **transfer 전용 노드**에서 응답 문구 + `needs_human=True`, `hitl_reason="고객이 상담원 연결을 요청했습니다."` 설정 후 **hitl_alert** 또는 **update_state**로 보내서, RAG/LLM 없이도 HITL만 확실히 태우는 구성 가능.
- **complaint / needs_follow_up / confidence < 0.3**: 기존 `hitl_alert_node` 조건 그대로 유지. (참고: `src/ai_voicebot/langgraph/nodes/hitl_alert.py`)

### 5.2 hitl_alert 노드 조건 정리 (구현 기준)

아래는 현재 `hitl_alert_node`에서 사용하는 조건이다. 확장 intent 적용 시에도 **generate_response를 거치는 경로**에서는 이 로직이 그대로 적용된다.

1. **needs_follow_up == True** → `needs_human=True` (AI가 모르는 내용으로 응답)
2. **intent == "transfer"** → `needs_human=True` (상담원 연결 요청)
3. **intent == "complaint" && confidence < 0.5** → `needs_human=True`
4. **confidence < HITL_CONFIDENCE_THRESHOLD(0.3)** → `needs_human=True`

확장 시 검토할 수 있는 항목:
- **intent == "out_of_scope"** 또는 **"nlu_fallback"** 이 RAG 경로를 타지 않고 `fallback_response`로만 갈 경우, 해당 노드에서 `needs_human`, `hitl_reason` 설정.
- **negative_reaction** 후속 발화가 "연결해 줘" 등이면 transfer로 재분류하거나, negative_reaction 전용 플래그로 HITL 설정.

### 5.3 hitl_alert를 타지 않는 경로에서의 HITL 처리

**template_response**, **repeat_response**, **clarification_response**, **help_response**, **fallback_response** (및 선택 시 **transfer_response**)는 **hitl_alert** 노드를 거치지 않고 **update_state**로 직행한다.  
이 경로들에서도 HITL이 필요한 intent인 경우 다음을 준수한다.

- **fallback_response** (out_of_scope, nlu_fallback):  
  - 고정 멘트 설정.  
  - 설정 또는 confidence에 따라 **state에 `needs_human=True`, `hitl_reason="의도 분류 불명 또는 업무 범위 외 발화. 확인이 필요합니다."`**(등) 설정 후 **update_state**로 전달.  
  - 그래프 최종 state에 `needs_human`, `hitl_reason`이 포함되므로 호출부(RAGLLMProcessor 등)에서 기존과 동일하게 HITL 프로토콜 수행 가능.
- **transfer 전용 노드**를 둔 경우:  
  - 해당 노드에서 `response`, `needs_human=True`, `hitl_reason="고객이 상담원 연결을 요청했습니다."` 설정 후 **update_state**로 보내거나, **hitl_alert**를 한 번 거친 뒤 **update_cache** → **update_state**로 연결해도 됨 (hitl_alert는 이미 설정된 needs_human을 덮어쓰지 않고 전달만 하도록 구현 가능).
- **negative_reaction**에서 “담당자 연결” 요청으로 처리하는 경우:  
  - 템플릿 노드 또는 별도 분기에서 `needs_human=True` 및 사유 설정 후 **update_state**로 전달.

이렇게 하면 **HITL이 필요한 intent**는 (1) 기존처럼 generate_response → hitl_alert를 타거나, (2) shortcut 경로에서 노드가 직접 needs_human·hitl_reason을 세팅하는 두 방식 모두 설계에 포함된다.

### 5.4 그래프·라우팅 요약

- **generate_response**를 거치는 경로: **generate_response → hitl_alert → update_cache → update_state** (기존 유지). hitl_alert에서 intent/confidence/needs_follow_up 기준으로 needs_human 설정.
- **template / repeat / clarification / help** 경로: 해당 노드 → **update_state** → END. HITL 필요 일반적 없음; 필요 시 해당 노드에서 state에 needs_human·hitl_reason 설정.
- **fallback_response** 경로: fallback_response → **update_state** → END. out_of_scope/nlu_fallback 시 설정에 따라 needs_human·hitl_reason 설정.
- **transfer** 단축 경로(선택): transfer → **transfer_response** (또는 동일 역할 노드) → **hitl_alert** 또는 **update_state** → END. transfer_response에서 response + needs_human + hitl_reason 설정.

### 5.5 HITL UX 흐름 (발신자·관리자)

**목표 흐름**

1. **AI가 HITL을 요청하는 경우**  
   - **발신자에게 먼저**: "확인해보겠습니다. 잠시만 기다려 주세요." 재생 후,  
   - **관리자에게**: HITL 요청 이벤트(`hitl_requested`) 발송.

2. **관리자가 응답하는 경우**  
   - 관리자가 제출한 내용을 **정보로 사용**해 AI가 발신자에게 응답 (예: `hitl_response_queue` → `_format_hitl_response_for_customer` → TTS).

3. **관리자가 응답하지 않는 경우**  
   - (일정 시간 경과 후) 발신자에게: "해당 내용 확인 후 별도 연락을 드릴까요?" 재생.  
   - 발신자가 **긍정(affirm)** 하면 → **frontend에 fallback 가능** 표시(예: `hitl_fallback_available` 이벤트).

**구현 상태 (점검 기준)**

| 단계 | 내용 | 구현 여부 | 비고 |
|------|------|-----------|------|
| 1 | 발신자에게 "확인해보겠습니다. 잠시만 기다려 주세요." | ✅ | `DEFAULT_FALLBACK_MESSAGE`(response_shortcuts), hitl_processor 반환문 |
| 1 | 관리자에게 HITL 요청 (`hitl_requested`) | ✅ | `rag_processor`에서 `emit_hitl_requested` 호출 |
| 2 | 관리자 응답 → 해당 내용으로 AI가 발신자에게 응답 | ✅ | `HITLService`(call_id별 queue 등록), `submit_hitl_response` 시 queue에 put → `_format_hitl_response_for_customer` → TTS. WebSocket `on_submit_hitl_response` → `get_hitl_service().submit_response()` 후 `hitl_resolved` 발송 |
| 3 | 관리자 미응답 시 "별도 연락 드릴까요?" | ✅ | HITL 요청 시 `start_fallback_timer(20초)` → 타임아웃 시 `HITL_FALLBACK_OFFER_MESSAGE`를 해당 call의 queue에 put → 기존 consumer가 TTS 재생 |
| 3 | 발신자 긍정(affirm) 시 frontend에 fallback 표시 | ✅ | `consume_fallback_affirm(call_id, intent)` 후 `emit_hitl_fallback_available(call_id)`. Frontend `hitl_fallback_available` 수신 시 `fallbackAvailableCallIds`에 추가 후 "Fallback 가능 (별도 연락 희망)" 섹션 표시 |
| — | 관리자 확인 타임아웃 | 20초 | `start_fallback_timer(call_id, timeout_sec=20.0)`. 20초 후 "별도 연락 드릴까요?" 재생 |
| — | 통화 종료 시 HITL 정리 | ✅ | **SIP BYE** 등 통화 종료 시 `emit_call_ended(call_id)`를 호출하면, 그 안에서 `get_hitl_service().unregister_call(call_id)`로 해당 통화의 queue·타임아웃 태스크 정리. BYE 처리부에서 `emit_call_ended`만 호출하면 됨 |

---

## 6. 상태 전이 확장

`update_state_node`의 **STATE_TRANSITIONS**에 새 intent를 반영한다.

- **B/C/E 그룹 intent** (affirm, deny, gratitude, doubt, positive_reaction, negative_reaction, chitchat, repeat, clarification, help, out_of_scope, nlu_fallback):  
  - **inquiry / resolution** 상태에서는 대부분 **현재 상태 유지** 또는 **inquiry 유지**.  
  - farewell만 **closing**으로 전이하는 것은 기존과 동일.
- 제안 전이표 (요지만):
  - initial: greeting→initial, question/complaint/transfer/chitchat 등→inquiry, farewell→closing, **affirm/deny/gratitude/doubt/positive_reaction/negative_reaction**→initial 또는 inquiry 유지, **repeat/clarification/help**→현재 유지, **out_of_scope/nlu_fallback**→inquiry.
  - inquiry: question 등→inquiry, farewell→closing, **B/C 그룹**→inquiry 유지.
  - resolution: question→inquiry, farewell→closing, **B 그룹**→resolution 유지.
  - closing: greeting→inquiry(재시작), 그 외→closing.

상세 전이표는 구현 시 `STATE_TRANSITIONS` 딕셔너리를 확장하여 정의.

---

## 7. 구현 단계

### Phase 1 — 의도 분류 확장 + 라우팅

1. **classify_intent_node**  
   - **INTENT_KEYWORDS** 확장: affirm, deny, gratitude, doubt, positive_reaction, negative_reaction, repeat, clarification, help용 키워드 추가(한국어 구어체).  
   - **valid_intents**를 2.2 집합으로 확장.  
   - LLM 분류 프롬프트: "가능한 의도: greeting, farewell, affirm, deny, gratitude, doubt, positive_reaction, negative_reaction, chitchat, repeat, clarification, help, question, complaint, transfer, out_of_scope" + 예시 1~2문장.  
   - 분류 confidence가 임계치 미만이면 **nlu_fallback** 반환.
2. **_route_after_intent**  
   - farewell → update_state.  
   - greeting → generate_response.  
   - affirm, deny, gratitude, doubt, positive_reaction, negative_reaction → **template_response**.  
   - repeat → **repeat_response**.  
   - clarification → **clarification_response**.  
   - help → **help_response**.  
   - chitchat → **generate_response** (또는 전용 chitchat 경로).  
   - question, complaint, transfer → check_cache.  
   - out_of_scope, nlu_fallback → **fallback_response**.

### Phase 2 — 템플릿·전용 응답 노드

1. **template_response 노드**  
   - state.intent에 따라 B 그룹 템플릿 목록에서 랜덤 1문장 선택.  
   - state.response, state.response_chunks 설정.  
   - state.confidence = 0.9 등 고정.
2. **repeat_response 노드**  
   - messages에서 마지막 assistant content → response. 없으면 기본 문장.
3. **clarification_response 노드**  
   - 직전 assistant 요약 + 명확화 문장 (또는 LLM 1문장).
4. **help_response 노드**  
   - org_manager.get_capabilities() 기반 안내 문장 생성.
5. **fallback_response 노드**  
   - 고정 멘트 설정. 필요 시 needs_human=True 설정.

6. **HITL 연동 (§5 반영)**  
   - **fallback_response**: intent가 out_of_scope 또는 nlu_fallback일 때, 설정(또는 confidence)에 따라 `state["needs_human"]=True`, `state["hitl_reason"]` 설정(예: "의도 분류 불명 또는 업무 범위 외 발화. 확인이 필요합니다.") 후 update_state로 전달.  
   - **transfer 단축 경로**를 둘 경우: transfer_response(또는 동일 역할 노드)에서 `response`, `needs_human=True`, `hitl_reason="고객이 상담원 연결을 요청했습니다."` 설정.  
   - **update_state_node**: template/fallback/transfer_response 등에서 넘어온 `needs_human`, `hitl_reason`을 state에 유지·반영하여 그래프 최종 결과에 포함되도록 함.

### Phase 3 — 그래프·상태·테넌트

1. **StateGraph**  
   - 위 노드 추가, conditional_edges에서 해당 노드로 분기, 각 노드 → update_state → END 연결.
2. **STATE_TRANSITIONS**  
   - 새 intent 모두에 대해 전이 규칙 추가.
3. **테넌트별 템플릿** (선택)  
   - tenant_config에 intent별 응답 문장 오버라이드. 상세는 §8.1 참고.
4. **HITL 경로 검증**  
   - fallback_response·transfer_response(선택) 경로에서 설정한 `needs_human`, `hitl_reason`이 최종 그래프 결과(state)에 포함되는지 확인. 호출부(RAGLLMProcessor 등)에서 HITL 프로토콜이 동작하는지 점검.

### Phase 4 — chitchat 정교화 (구현 반영)

- chitchat/greeting 시 `generate_response`에서 규칙 9 추가: "1~2문장으로 짧게 공감·안내만 하세요" (`chitchat_rule`), confidence 0.9 고정. RAG는 chitchat 경로에서 스킵(이미 `_route_after_intent`에서 chitchat → generate_response).
- CDR/로깅에 intent 기록해 실제 트래픽 기준으로 튜닝은 별도 작업.

---

## 8. 설정·데이터

### 8.1 테넌트별 템플릿 오버라이드 (미구현 · 개념·예시만)

**상태**: 테넌트별 오버라이드는 **미구현**으로 둠. 공용 템플릿(§8.2)만 사용.

**의미(참고)**: 테넌트(착신번호/조직)마다 **같은 intent**에 대해 **다른 응답 문장**을 쓰고 싶을 때, 코드 기본값 대신 **tenant_config에 넣어 둔 문장 목록**을 쓰는 기능. 추후 구현 시 아래 예시 참고.

- **기본(현재 사용)**: 코드 상수 `INTENT_RESPONSE_TEMPLATES` (§8.2).
- **오버라이드(미구현)**: VectorDB `tenant_config` 메타데이터에 **intent_templates** 필드 두고 intent별 문장 리스트 저장 → `org_manager.get_intent_templates(intent)`로 조회하는 방식으로 확장 가능.

**설정 예시 (tenant_config 메타데이터)**

VectorDB의 `tenant_config` 문서(메타데이터)에 아래처럼 넣을 수 있다.

```json
{
  "owner": "1004",
  "tenant_name": "한국 기상청",
  "doc_type": "tenant_config",
  "intent_templates": "{\"affirm\": [\"알겠습니다. 추가로 궁금하신 점 있으시면 말씀해 주세요.\", \"네, 반영했어요. 더 필요하시면 말씀해 주세요.\"], \"gratitude\": [\"천만에요. 좋은 하루 되세요.\"]}"
}
```

또는 메타데이터가 이미 dict를 허용하는 경우:

```yaml
# 개념적 구조 (실제 저장은 ChromaDB 메타데이터 스키마에 따름)
intent_templates:
  affirm:
    - "알겠습니다. 추가로 궁금하신 점 있으시면 말씀해 주세요."
    - "네, 반영했어요. 더 필요하시면 말씀해 주세요."
  gratitude:
    - "천만에요. 좋은 하루 되세요."
  negative_reaction:
    - "불편을 드려 죄송합니다. 다른 안내 방법을 원하시면 말씀해 주세요."
```

**코드 흐름**

1. `template_response_node(state)` 호출 시 `state["_org_manager"]`에서 `OrganizationInfoManager` 획득.
2. `org_manager.get_intent_templates(intent)` 호출 → `tenant_config["intent_templates"]`를 파싱해 해당 intent의 `List[str]` 반환. 없거나 키 없으면 `None`.
3. `None`이면 `INTENT_RESPONSE_TEMPLATES.get(intent)`(기본 상수) 사용.
4. 있으면 그 리스트에서 `random.choice()`로 1문장 선택해 `response`로 반환.

**적용 범위**: B 그룹 반응/피드백 intent (affirm, deny, gratitude, doubt, positive_reaction, negative_reaction). repeat/clarification/help/fallback은 별도 처리이므로 동일 메커니즘 확장 가능.

### 8.2 템플릿 저장소 — 공용 (구현됨)

- **공용 템플릿**: 코드 내 상수 `INTENT_RESPONSE_TEMPLATES` (`response_shortcuts.py`)에 B 그룹 intent별 응답 문장 목록이 정의되어 있으며, `template_response_node`에서 **공용으로** 사용 중.  
- intent별 랜덤 1문장 선택으로 응답. (테넌트별 오버라이드 §8.1은 미구현.)

### 8.3 키워드 예시 (한국어, 존댓말 기준)

- **affirm**: 네, 예, 넹, 응, 좋아요, 좋습니다, 됐어요, 됐습니다, 알겠어요, 알겠습니다, 그럴게요.  
- **deny**: 아니요, 아니에요, 아니, 필요 없어요, 취소할게요, 그만할게요.  
- **gratitude**: 감사해요, 고마워요, 감사합니다, 고맙습니다. (farewell과 겹치면 **길이·문맥**으로 구분: "감사합니다. 끊을게요" → farewell 우선.)  
- **doubt**: 글쎄요, 아마, 잘 모르겠어요, 몰라요.  
- **positive_reaction**: 좋아요, 맘에 들어요, 좋네요.  
- **negative_reaction**: 별로예요, 안 좋아요, 그냥요.  
- **repeat**: 다시, 다시 말해, 뭐라고, 한번 더, 못 들었어요.  
- **clarification**: 무슨 뜻이에요, 뭔 소리야, 이해가 안 가요, 어느 부분이요.  
- **help**: 도와줘, 도움, 어떻게 해요, 어떻게 하죠, 뭘 할 수 있어요.

- **farewell**과 **gratitude** 구분: "감사합니다"만 있으면 farewell 우선; "감사해요. 그런데 ○○는?"이면 gratitude 또는 question.

---

## 9. 기존 호환성

- **question**, **complaint**, **transfer**, **farewell**, **greeting** 동작은 유지.  
- **update_state_node**: response가 이미 설정된 경로(template/repeat/clarification/help/fallback)에서는 기존처럼 state에 response가 들어온 채로 전달되므로, farewell과 동일하게 처리 가능.  
- **generate_response_node**: intent가 greeting 또는 chitchat일 때만 RAG를 스킵하거나 경량화; question은 기존대로 RAG+LLM.  
- **hitl_alert**: template/repeat/clarification/help/fallback 경로에서는 hitl_alert 노드를 타지 않는다. HITL이 필요한 intent(out_of_scope, nlu_fallback 등)는 해당 경로 노드(예: fallback_response)에서 needs_human·hitl_reason을 state에 설정한 뒤 update_state로 보내므로, 그래프 결과에 HITL 정보가 포함되어 기존 HITL 로직과 충돌 없이 연동된다 (§5.3 참고).

---

## 10. 성공 지표 (참고)

- "오늘 날씨 좋은것같아" → **chitchat** 또는 **question**으로 분류되고, 1~2문장 짧은 응답.  
- "네", "감사해요" → **affirm**, **gratitude**로 분류되고, 템플릿 응답만 반환(RAG/LLM 미호출).  
- "다시 말해줘" → **repeat**으로 분류되고, 직전 AI 발화 재재생 또는 재안내.  
- "뭘 할 수 있어요?" → **help**로 분류되고, capability 안내 문장.

---

## 11. 참고 문서

- `docs/design/INTENT_TAXONOMY_RESEARCH.md` — 확장 intent 제안 및 타 시스템 리서치.  
- `src/ai_voicebot/langgraph/agent.py` — 현재 그래프·라우팅.  
- `src/ai_voicebot/langgraph/nodes/classify_intent.py` — 현재 의도 분류.  
- `src/ai_voicebot/langgraph/nodes/hitl_alert.py` — HITL 판단 조건(transfer, complaint, needs_follow_up, confidence).  
- `src/ai_voicebot/langgraph/nodes/update_state.py` — 비즈니스 상태 전이 및 farewell 처리(§12 통화 종료 정책 반영).  
- `src/ai_voicebot/langgraph/nodes/generate_response.py` — LLM 응답 생성, 대화 기록 history 포맷(§13).

이 설계에 따라 Phase 1부터 순차 적용하면, 단순 질문–응답에서 벗어나 사람처럼 맞장구·반응·일상 대화·제어를 구분하는 AI 응답 고도화를 달성할 수 있다.

---

## 12. 통화 종료 정책 (AI는 통화를 끊지 않음)

- **원칙**: AI가 수신한 통화에서 **AI가 먼저 BYE를 보내거나 통화를 종료하는 동작은 하지 않는다.** 통화 종료는 항상 **발신자(고객)** 또는 **착신 측 사람(전환 후)** 이 수행한다.
- **끝인사(farewell) 처리**: 고객이 "감사합니다", "끊을게요" 등 끝인사를 해도 **비즈니스 상태를 closing으로 바꾸지 않는다.**  
  - 상태 전이: `farewell` → **inquiry** (또는 resolution 유지).  
  - AI는 마무리 멘트(예: "감사합니다. 필요하시면 다시 연락 주세요.")만 TTS로 재생하고, **대화를 이어갈 수 있도록** 다음 발화를 그대로 받는다.  
  - 구현: `update_state_node`의 `STATE_TRANSITIONS`에서 `farewell` → `closing` 대신 `farewell` → `inquiry`(또는 `resolution`) 사용.

---

## 13. LLM 대화 맥락 (누적 통화 내용 전달)

사람처럼 대화하려면 **현재 발화만이 아니라 지금까지의 통화 내용**을 LLM에 함께 넘겨야 한다.

### 13.1 현재 구현 확인

| 구간 | 사용 데이터 | 위치 |
|------|-------------|------|
| **응답 생성** | `state["messages"]` → 최근 **6턴**(user+assistant 12개) 포맷 후 `{history}`로 시스템 프롬프트에 포함 | `generate_response_node`: `_format_history(messages, max_turns=6)` |
| **쿼리 리라이팅** | `state["messages"]` → 최근 **3턴** 포맷 후 프롬프트에 포함 | `rewrite_query_node`: `_format_recent(messages, max_turns=3)` |
| **의도 분류** | 현재 발화만 (`user_query`) | `classify_intent_node` (맥락 없음) |

- **generate_response**: `RESPONSE_SYSTEM_PROMPT`에 `대화 기록:\n{history}`가 들어가므로, **누적 통화 내용이 LLM 질의에 포함되어 있다.**
- **rewrite_query**: 검색용 쿼리 변환 시에도 최근 3턴 대화가 사용된다.
- **step_back_prompt**: 상위 개념 쿼리 생성 시 최근 3턴 대화(`_format_recent_history`)를 프롬프트에 포함하도록 구현함.

### 13.2 개선 여지 (구현 반영)

- **history 턴 수**: `generate_response_node`에서 `HISTORY_MAX_TURNS = 8`로 확대 적용함. 장문 대화 맥락 유지.
- **의도 분류에 맥락**: `classify_intent_node` LLM 분류 시 직전 2턴(`_format_recent_for_intent`)을 프롬프트에 포함하도록 구현함.

---

## 14. 사람처럼 대화하기 — 추가 기능 리서치

### 14.1 턴 테이킹·동시성 (정책: 겹침발화 지양, “말 모아서 기다리기” 우선)

- **겹침발화(backchannel) 지양**: 발화 중간에 “응”, “네” 등을 끼워 넣는 방식은 **난잡하고**, 응대 지연과 타이밍 이슈로 **위험**이 있다. 따라서 **잦은 응답/겹침 발화보다는**, 사용자가 말할 내용을 **한 번에 모아서 기다려 준 뒤** 한 턴으로 응답하는 쪽을 우선한다.
- **“말할 내용을 모아서 기다려주는” 기능**: 해당 동작은 **이미 구현되어 있다.** 아래 §14.1a에서 확인한 바와 같다.
- **리서치 참고**: Full-duplex / Synchronous LLM, 백채널 연구는 있으나, 본 시스템에서는 **말 모아서 기다리기 + 턴 기반 응답**을 유지하는 방향을 권장한다.

### 14.1a “말 모아서 기다리기” 기능 확인 (이미 구현됨)

사용자가 말을 더 이어갈 수 있도록 **통화 내용을 모아서 기다린 뒤**, 발화가 끝났을 때만 STT 최종 결과 → LLM으로 보내는 구조가 이미 있다.

| 계층 | 역할 | 구현 위치 | 설정 |
|------|------|-----------|------|
| **VAD** | 침묵 구간 감지. 침묵이 `stop_secs` 이상이면 “발화 종료 후보”로 본다. | `pipeline_builder.py`: Silero VAD, `VADParams(stop_secs=…)` | `config.silero_vad.stop_secs` (기본 0.7초) |
| **Smart Turn** | VAD가 “발화 종료” 후보를 보낸 뒤, **진짜 발화 완료인지** 문법/억양/속도로 판단. **미완**이면 프레임 보류 → 사용자 추가 발화 수신. | `smart_turn_processor.py`: `SmartTurnProcessor` | `config.smart_turn.enabled`, `max_hold_secs` (기본 2.0초) |
| **STT → RAG/LLM** | **최종(TranscriptionFrame)** 만 LLM으로 전달. **Interim(중간 결과)** 는 UI용으로만 쓰고 LLM에는 보내지 않음. | `rag_processor.py`: `TranscriptionFrame`만 `_process_with_agent()` 호출, `InterimTranscriptionFrame`은 downstream 미전달 | — |

**동작 요약**

1. **VAD**: `stop_secs`(예: 0.7초) 침묵이 지나면 `UserStoppedSpeakingFrame` 발생.
2. **Smart Turn**: 해당 구간 오디오를 Smart Turn 모델로 분석.
   - **발화 완료** → 프레임 통과 → STT가 최종 결과 생성 → RAG/LLM으로 한 번만 전달.
   - **발화 미완** → 프레임 **보류(hold)** → 다음 오디오를 계속 받으며 **기다림**. `max_hold_secs`(예: 2초) 초과 시에만 강제 통과(무한 대기 방지).
3. **RAG/LLM**: `TranscriptionFrame`(최종)만 받아 1회 응답. Interim은 전달하지 않음.

따라서 **“사용자가 더 말할 내용이 있으면 통화 내용을 모아서 기다려 주는”** 동작은 **VAD + Smart Turn + 최종만 LLM 전달** 조합으로 이미 구현되어 있다. 겹침발화/잦은 응답 대신 이 정책을 유지하는 것이 적합하다.

### 14.2 맥락 구조 (Local / Global) — 대화 단계·요약 구현됨

- **대화 단계(레이블)**: `business_state` + `intent`로 **현재 대화 단계**를 한 줄로 계산해 LLM 시스템 프롬프트에 넣음.  
  예: "질문 응답 중", "불만 대응 중", "안내 완료 후 대기", "반응/피드백 처리" 등.  
  구현: `generate_response_node` 내 `_get_conversation_stage()`, `CONVERSATION_STAGE_MAP`.
- **대화 요약**: 최근 고객 발화 1~2건을 한 문장으로 이어 붙여 **최근 화제(요약)** 로 프롬프트에 주입. (규칙 기반, 추가 LLM 호출 없음.)  
  구현: `_get_conversation_summary()`, `_format_stage_and_summary()`.
- **프롬프트 반영**: `RESPONSE_SYSTEM_PROMPT`에 `{stage_and_summary}` 블록 추가 — "현재 대화 단계: … / 최근 화제(요약): …".

### 14.3 대화 원칙(Conversational Maxims)

- **Grice 극대:** 양(정보량), 질(정확성), 관련성, 방식(명료성).  
- **추가 극대:** **Benevolence**(유해 내용 관리), **Transparency**(모르는 것은 모른다고 명시, HITL 안내).
- **시사점**: 현재 시스템 프롬프트에 "모르는 내용은 고정 문구만", "2~3문장 이내", "질문 반복하지 말 것" 등이 이미 반영됨. 설계 시 **투명성**(확인 필요 시 HITL)은 §5 HITL 연동으로 반영됨.

### 14.4 제안 기능 요약

| 기능 | 설명 | 우선순위 |
|------|------|----------|
| **끝인사 후 대화 이어가기** | farewell → closing 제거, inquiry/resolution 유지 | ✅ 반영됨 (§12) |
| **누적 대화 history** | generate_response에 최근 6턴 포함 | ✅ 이미 구현 (§13) |
| **말 모아서 기다리기** | VAD + Smart Turn으로 발화 미완 시 보류, 최종만 LLM 전달 | ✅ 이미 구현 (§14.1a) |
| **의도 분류에 맥락** | 직전 1~2턴을 classify_intent에 전달 | ✅ 구현됨 (§13.2) |
| **step_back에 history** | 상위 개념 쿼리 생성 시 대화 맥락 사용 | ✅ 구현됨 |
| **짧은 반응(템플릿)** | affirm/gratitude 등 템플릿 응답(겹침발화 아님, 턴 단위) | ✅ 이미 반영 |
| **대화 단계/요약** | 단계 레이블 + 최근 화제 요약을 프롬프트에 주입 | ✅ 구현됨 (§14.2) |
