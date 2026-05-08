# AI 비서 의도(Intent) 분류 확장 리서치
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`INTENT_HANDLING_DESIGN.md`](INTENT_HANDLING_DESIGN.md)
>
---


## 1. 목적

현재 intent는 **greeting, question, complaint, transfer, farewell** 5종 + 기본값 question으로만 처리된다.  
"사람처럼 응대"하려면 **일상 대화·동의/거절·감사·반복 요청·피드백** 등 다양한 반응을 구분할 수 있는 확장된 분류가 필요하다.

---

## 2. 현재 시스템 (sip-pbx)

| Intent | 용도 | 라우팅 |
|--------|------|--------|
| greeting | 인사 | 캐시 스킵 → generate_response |
| farewell | 끝인사 | update_state (종료) |
| question | 질문/요청 | check_cache → RAG → generate_response |
| complaint | 불만 | check_cache 등, HITL 조건 시 개입 |
| transfer | 담당자 연결 | HITL/연결 플로우 |
| (기본) | 키워드/LLM 미매칭 | question |

- **한계**: "오늘 날씨 좋은것같아" 같은 **일상 말걸기**, "네/아니요", "감사해요", "다시 말해줘" 등이 **question**으로만 떨어져 RAG·LLM에 일괄 위임됨.

---

## 3. 타 시스템 리서치 요약

### 3.1 Google Dialogflow

- **의도 구성**: 사용자 정의 intent + **시스템 intent**(호출, no-match 등).
- **Small Talk**:  
  - **Built-in small talk**: 에이전트 설정으로 켜면, **질문 아닌 일상 대화**를 별도 처리(캐주얼 대화 응답).  
  - **Prebuilt small talk**: import 가능한 에이전트로, 일상 질문/대화용 intent 묶음 제공.
- **시사점**: "질문"과 "일상 대화(small talk)"를 **분리**하고, small talk는 고정/짧은 응답 또는 전용 응답 세트로 처리.

참고: [Small talk | Dialogflow ES](https://cloud.google.com/dialogflow/es/docs/agents-small-talk)

### 3.2 Amazon Alexa (Dialog Acts)

- **User input dialog acts**:  
  **Invoke APIs**, **Inform Args**, **Deny**, **Affirm**
- **Alexa response dialog acts**:  
  Request Args, Request Alt, Offer Next API, Confirm Args, Confirm API, API Success, API Failure
- **표준 Built-in Intents**:  
  `AMAZON.YesIntent`, `AMAZON.NoIntent`, `AMAZON.HelpIntent`, `AMAZON.CancelIntent`, `AMAZON.StopIntent`, `AMAZON.RepeatIntent`, `AMAZON.ResumeIntent` 등.
- **시사점**:  
  - **Affirm/Deny**(네/아니요)를 별도 의도로 두어 확인·제안 플로우에 사용.  
  - **Repeat**(다시 말해줘), **Help**(도움 요청) 등 **제어/유틸** 의도를 명시적으로 분리.

참고: [Dialog Act Reference for Alexa Conversations](https://developer.amazon.com/en-US/docs/alexa/conversations/dialog-act-reference.html), [Standard Built-in Intents](https://developer.amazon.com/en-US/docs/alexa/custom-skills/standard-built-in-intents.html)

### 3.3 Rasa

- **Chitchat**: 질문이 아닌 **캐주얼 대화**를 별도 intent로 두고, retrieval 기반 고정 응답 또는 짧은 생성.
- **Fallback**: confidence 임계치 미달 시 **nlu_fallback** intent로 처리(재질문·안내·human handoff).
- **Conversation repair**:  
  - **Clarification**(애매함 해소), **Repeat**(이전 말 다시), **Correction**(정보 수정), **Interruption**(화제 전환) 등 **대화 수리** 패턴을 별도로 다룸.
- **시사점**:  
  - **chitchat** + **fallback** + **repair(반복/정정/명확화)** 를 의도 체계에 포함하면 사람처럼 응대하기 좋음.

참고: [Chitchat and FAQs](https://rasa.com/docs/rasa/chitchat-faqs), [Conversation Patterns](https://rasa.com/docs/rasa-pro/concepts/conversation-repair/)

### 3.4 Just AI (Aimylogic) Built-in Intents

- **주요 메뉴**: **Agreement**(예/좋아/됐어), **Disagreement**(아니요/취소/필요 없어), **Date&Time**(날짜·시간 추출).
- **추가 메뉴**:  
  **Greeting**, **Parting**, **Gratitude**(감사해요), **Doubt**(아마/글쎄).
- **감정/반응**:  
  **Explicit language**(비속어), **Positive reaction**(좋아/맘에 들어), **Negative reaction**(별로/안 좋아).
- **시사점**:  
  - **동의/거절/감사/의심**을 기본 의도로 두고,  
  - **긍정·부정 반응**까지 구분하면 톤과 다음 응답(추가 안내 vs 사과·대안)을 나누기 좋음.

참고: [Built-in intents | Just AI Aimylogic](https://help.cloud.just-ai.com/en/aimylogic/how-to-create-a-script/user-says/premade_intents)

### 3.5 콜센터·Livevox

- **상호작용 의도**: Complaints, Billing and Payments, Customer Support, Inquiries 등 **접촉 목적** 기준.
- **Intent type**: self-serviceable vs non-self-serviceable 등 **해결 방식**으로도 구분.
- **시사점**:  
  - 업무용 AI 비서는 "질문"을 **inquiry**로 두고,  
  - **불만(complaint)·결제·지원·일반 문의** 등으로 세분화하는 방식은 도메인 확장 시 참고 가능.

### 3.6 ISO 24617-2 (대화 행위 표준)

- **9개 차원**: General, Social Obligations Management, Auto-Feedback, Allo-Feedback, Time Management, Turn Management, Discourse Structuring, Own Speech Management, Partner Speech Management.
- **시사점**:  
  - **Auto-Feedback**(자기 발화에 대한 반응), **Allo-Feedback**(상대 발화에 대한 반응), **Turn Management**(말하기 권한·반복 요청 등) 등이 **감사/동의/거절/다시 말해줘** 같은 의도와 대응됨.  
  - 표준은 복잡하지만, "피드백·턴 관리·사회적 의무"를 의도 설계 시 축으로 삼을 수 있음.

---

## 4. 제안: 확장 Intent 택소노미

"사람처럼 응대"를 위해, 아래처럼 **계층/그룹**을 두고 확장하는 구성을 제안한다.

### 4.1 그룹 A — 대화 시작/종료

| Intent | 설명 | 처리 방향 |
|--------|------|------------|
| **greeting** | 인사, 처음 말걸기 | 기존: 캐시 스킵 → 짧은 인사/안내 |
| **farewell** | 끝인사, 통화 종료 | 기존: update_state → closing_template |

### 4.2 그룹 B — 반응/피드백 (사람처럼 맞장구)

| Intent | 설명 | 처리 방향 |
|--------|------|------------|
| **affirm** | 동의·확인 (네, 맞아요, 좋아요, 됐어요) | 짧은 확인 + "더 필요하시면 말씀해 주세요" |
| **deny** | 거절·취소 (아니요, 아니에요, 필요 없어요) | "알겠습니다. 다른 건 도와드릴까요?" |
| **gratitude** | 감사 (감사해요, 고마워요) | "천만에요. 더 필요하시면 말씀해 주세요." |
| **doubt** | 애매함 (글쎄요, 아마, 잘 모르겠어요) | "괜찮아요. 정하시면 말씀해 주세요." |
| **positive_reaction** | 긍정 반응 (좋아요, 맘에 들어요) | 짧은 공감 + 서비스 안내 |
| **negative_reaction** | 부정 반응 (별로예요, 안 좋아요) | 공감 + 대안/담당자 연결 제안 |

### 4.3 그룹 C — 일상 대화 / 제어

| Intent | 설명 | 처리 방향 |
|--------|------|------------|
| **chitchat** | 일상 말걸기·날씨/기분 등 (질문 아님) | RAG 스킵 또는 짧은 RAG; 짧은 공감 + 안내 |
| **repeat** | 다시 말해줘, 뭐라고? | 이전 AI 발화 요약/재안내 또는 TTS 재생 |
| **clarification** | 뭔 소리야, 무슨 뜻이에요? | "제가 ○○ 말씀드렸는데, △△가 궁금하신가요?" 등 |
| **help** | 도와줘, 어떻게 해요? | 기능 안내(capability) 또는 짧은 사용법 |

### 4.4 그룹 D — 업무/에스컬레이션

| Intent | 설명 | 처리 방향 |
|--------|------|------------|
| **question** | 사실·서비스 질문·요청 | 기존: RAG + LLM (또는 캐시) |
| **complaint** | 불만·항의 | 기존 + HITL/연결 조건 |
| **transfer** | 담당자/상담원 연결 요청 | 기존: 연결 플로우 |

### 4.5 그룹 E — 기타/폴백

| Intent | 설명 | 처리 방향 |
|--------|------|------------|
| **out_of_scope** | 업무 무관·인식 실패·저신뢰도 | "해당 내용은 확인이 필요합니다. 잠시만 기다려 주세요." 또는 HITL |
| **nlu_fallback** | 의도 분류 confidence 낮음 | 재질문 또는 out_of_scope와 동일 |

---

## 5. 구현 시 고려사항

1. **키워드 확장**  
   - 현재 `INTENT_KEYWORDS`에 **affirm**(네, 예, 좋아, 됐어), **deny**(아니요, 아니, 취소), **gratitude**(감사, 고마워), **repeat**(다시, 뭐라고, 한번 더) 등 추가.
2. **LLM 분류 프롬프트 확장**  
   - "가능한 의도" 목록을 위 확장 택소노미로 늘리고, 예시 문장 1~2개씩 넣어서 분류 품질 확보.
3. **라우팅 규칙**  
   - **affirm / deny / gratitude / doubt / positive_reaction / negative_reaction** → RAG 스킵, 짧은 템플릿 또는 1~2문장 생성.  
   - **chitchat** → RAG 선택적 사용(예: confidence 높은 1건만) 또는 템플릿.  
   - **repeat / clarification / help** → 각각 전용 처리(이전 발화 재안내, 명확화 질문, capability 안내).  
   - **out_of_scope / nlu_fallback** → 고정 멘트 또는 HITL.
4. **템플릿 vs LLM**  
   - 반응/피드백(affirm, deny, gratitude 등)은 **고정/랜덤 템플릿**으로 빠르게 응답하고,  
   - chitchat·question만 LLM(및 RAG)을 쓰면 지연·비용을 줄이면서도 사람처럼 반응할 수 있음.
5. **다국어/한국어**  
   - 키워드·예시는 한국어 구어체 위주로 확장(반말/존댓말 중 하나로 통일 권장).

---

## 6. 참고 자료

- Google Dialogflow: [Small talk](https://cloud.google.com/dialogflow/es/docs/agents-small-talk), [Intents (CX)](https://cloud.google.com/dialogflow/cx/docs/concept/intent)
- Amazon: [Dialog Act Reference (Alexa Conversations)](https://developer.amazon.com/en-US/docs/alexa/conversations/dialog-act-reference.html), [Standard Built-in Intents](https://developer.amazon.com/en-US/docs/alexa/custom-skills/standard-built-in-intents.html)
- Rasa: [Chitchat and FAQs](https://rasa.com/docs/rasa/chitchat-faqs), [Conversation repair](https://rasa.com/docs/rasa-pro/concepts/conversation-repair/), Fallback / nlu_fallback
- Just AI: [Built-in intents (Aimylogic)](https://help.cloud.just-ai.com/en/aimylogic/how-to-create-a-script/user-says/premade_intents)
- Livevox: Interaction Intent, Interaction Intent Types
- ISO 24617-2:2020 (Dialogue acts), DAMSL/SWBD-DAMSL

이 택소노미를 기준으로 `classify_intent` 확장과 라우팅/템플릿 설계를 진행하면, "질문 아닌 평범한 얘기"와 반응류 발화를 구분해 사람처럼 응대할 수 있다.

→ **고도화 설계·구현 단계**는 **`docs/design/AI_RESPONSE_HUMANLIKE_DESIGN.md`** 를 참고한다.
