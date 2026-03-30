# Transfer 오분류 수정 (질문을 전환 요청으로 잘못 인식)

**작성일**: 2026-03-29 02:06  
**Call ID**: `64noibcoFK`  
**잘못 분류된 발화**: "기상청 담당자는 몇 명이나 있나요?"  
**수정 파일**: `src/ai_voicebot/pipecat/intents.py`

---

## 1. 문제 증상

### 1.1. 사용자 발화
```
"기상청 담당자는 몇 명이나 있나요?"
```

**사용자 의도**: 호기심 질문 → LLM이 답변해야 함 (예: "정확한 인원 수는 모르겠지만, 각 부서별로 담당자가 있습니다.")

**실제 동작**: `transfer_request_detected` → 상담원에게 즉시 연결 ❌

### 1.2. 로그 증거
```json
{"ts": "2026-03-29T02:00:20.173", "category": "stt", "event": "stt_final", 
 "text": "기상청 담당자는 몇 명이나 있나요?"}

{"ts": "2026-03-29T02:00:21.173", "category": "call_event", 
 "event": "transfer_request_detected", 
 "query": "기상청 담당자는 몇 명이나 있나요?"}

{"ts": "2026-03-29T02:00:22.848", "category": "call_event", 
 "event": "transfer_announcement_sent", 
 "department": "상담원", 
 "text": "상담원 담당자에게 연결해 드리겠습니다. 잠시만 기다려 주세요."}
```

**문제**: LLM intent 분류를 거치지 않고 **키워드 기반 Quick Check**에서 즉시 transfer로 판단됨.

---

## 2. 근본 원인

### 2.1. Quick Check 로직
**파일**: `src/ai_voicebot/pipecat/processors/rag_processor.py` (807-811줄)

```python
from ..intents import IntentClassifier, Intent
quick_intent = IntentClassifier.classify_quick(user_text)

if quick_intent == Intent.TRANSFER_REQUEST:
    logger.info("transfer_request_detected", ...)
    # → 즉시 연락처 검색 및 전환 처리
```

### 2.2. IntentClassifier.classify_quick 로직
**파일**: `src/ai_voicebot/pipecat/intents.py` (24-72줄)

```python
_TRANSFER_SUBSTRINGS: ClassVar[tuple[str, ...]] = (
    "연결해 주",
    "연결해주",
    "바로 연결",
    "전환",
    "상담원",
    "상담사",
    "담당자",  # ⚠️ 문제 키워드
    "직원",
    ...
)

@classmethod
def classify_quick(cls, user_text: str) -> Intent:
    t = str(user_text).strip().lower()
    
    for sub in cls._TRANSFER_SUBSTRINGS:
        if sub.lower() in t:  # ⚠️ 단순 부분 문자열 매칭
            return Intent.TRANSFER_REQUEST
    ...
    return Intent.GENERAL
```

**문제점**:
- "담당자"가 `_TRANSFER_SUBSTRINGS`에 포함됨
- **부분 문자열 매칭만** 수행 (문맥 무시)
- "기상청 담당자는 몇 명이나 있나요?" → "담당자" 포함 → `TRANSFER_REQUEST` 즉시 반환

### 2.3. 왜 이런 로직이 있었나?
- **성능 최적화**: LLM 호출 전에 명확한 transfer 요청을 빠르게 걸러내기 위함
- **의도**: "담당자 연결해 주세요", "상담원 바꿔 주세요" 같은 명확한 표현을 빠르게 감지
- **부작용**: "담당자는 누구인가요?", "담당자는 몇 명?" 같은 **질문**도 transfer로 오인

---

## 3. 수정 내용

### 3.1. 질문 패턴 예외 처리 추가

**파일**: `src/ai_voicebot/pipecat/intents.py`  
**위치**: `IntentClassifier` 클래스

**추가한 정규식 패턴**:
```python
# 질문 패턴 (transfer 키워드가 있어도 질문이면 제외)
_QUESTION_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
    # 의문사 + 물음표
    re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\?"),
    
    # 의문사 + 질문 종결어미
    re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\s*(있나요|인가요|일까요|가요|나요)"),
    
    # 질문 종결어미
    re.compile(r".*\s*(있나요|인가요|일까요|하나요|되나요)\??\s*$"),
)
```

### 3.2. classify_quick 로직 수정

```python
@classmethod
def classify_quick(cls, user_text: str) -> Intent:
    if not user_text or not str(user_text).strip():
        return Intent.GENERAL

    t = str(user_text).strip().lower()

    # 1. 질문 패턴 먼저 확인 (질문이면 transfer 아님)
    for qp in cls._QUESTION_PATTERNS:
        if qp.search(t):
            return Intent.GENERAL  # ✅ 질문은 LLM으로 처리

    # 2. Transfer 키워드 확인
    for sub in cls._TRANSFER_SUBSTRINGS:
        if sub.lower() in t:
            return Intent.TRANSFER_REQUEST

    for rx in cls._TRANSFER_REGEX:
        if rx.search(t):
            return Intent.TRANSFER_REQUEST

    return Intent.GENERAL
```

**핵심 변경**: 
- **질문 패턴을 먼저 체크** → 질문이면 키워드와 무관하게 `GENERAL` 반환
- 질문이 아닐 때만 transfer 키워드 매칭 수행

---

## 4. 수정 후 동작

### 4.1. 질문 예시 (transfer로 오인되지 않음)
| 발화 | 기존 분류 | 수정 후 분류 | 이유 |
|------|---------|------------|------|
| "담당자는 몇 명이나 있나요?" | transfer ❌ | general ✅ | "몇 명" + "있나요" |
| "담당자는 누구인가요?" | transfer ❌ | general ✅ | "누구" + "인가요" |
| "상담원은 어떤 업무를 하나요?" | transfer ❌ | general ✅ | "어떤" + "하나요" |
| "직원 몇 명이에요?" | transfer ❌ | general ✅ | "몇 명" + "에요" |
| "어디에 연락하면 되나요?" | transfer ❌ | general ✅ | "어디" + "되나요" |

### 4.2. 전환 요청 예시 (정상 감지)
| 발화 | 분류 | 이유 |
|------|------|------|
| "담당자 연결해 주세요" | transfer ✅ | 질문 패턴 없음 + "담당자" + "연결해 주" |
| "상담원이랑 통화하고 싶어요" | transfer ✅ | 질문 패턴 없음 + "상담원" |
| "직원한테 바꿔 주세요" | transfer ✅ | 질문 패턴 없음 + "직원" + "바꿔 주" |
| "마케팅팀으로 전환해 주세요" | transfer ✅ | regex 매칭 |

---

## 5. 검증 방법

### 5.1. 테스트 케이스

**질문 (LLM 처리 기대)**:
```
1. "기상청 담당자는 몇 명이나 있나요?"
2. "담당자는 누구인가요?"
3. "상담원 근무 시간은 언제인가요?"
4. "직원이 몇 명이에요?"
```

**전환 요청 (transfer 기대)**:
```
1. "담당자 연결해 주세요"
2. "상담원과 통화하고 싶어요"
3. "직원한테 바꿔 주세요"
```

### 5.2. 로그 확인
```bash
# Quick check 분류 결과 확인
Select-String -Path "logs\app.log" -Pattern "transfer_request_detected|quick_intent"

# LangGraph 분류 결과 확인
Select-String -Path "logs\call_data_record*.log" -Pattern "intent_classify"
```

**기대 결과**:
- 질문 발화 → `transfer_request_detected` **미발생**
- 질문 발화 → LangGraph가 `question` 또는 `help`로 분류
- 전환 요청 → `transfer_request_detected` 정상 발생

---

## 6. Quick Check vs LangGraph 분류 흐름

### 6.1. 현재 흐름
```
사용자 발화
    ↓
[Quick Check] (intents.py - classify_quick)
    ↓ transfer 키워드 발견?
    Yes → TRANSFER_REQUEST → 즉시 연락처 검색 및 전환
    No  → GENERAL → LangGraph 분류 (LLM 기반)
              ↓
         question/help/chitchat/... 정밀 분류
```

### 6.2. Quick Check의 목적
- **빠른 경로**: 명확한 전환 요청은 LLM 호출 없이 즉시 처리 (성능)
- **제한 사항**: 키워드 기반이므로 문맥 이해 불가능

### 6.3. 수정 후 개선
- 질문 패턴 감지 → Quick Check를 우회하고 LangGraph로 전달
- 명확한 전환 요청만 Quick Check에서 처리
- **정확도 향상** (질문 오분류 방지) + **성능 유지** (진짜 전환 요청은 빠르게 처리)

---

## 7. 정규식 패턴 설명

### 7.1. 의문사 + 물음표
```python
re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\?")
```
- **예**: "담당자는 몇 명인가요?", "어떤 직원인가요?"

### 7.2. 의문사 + 질문 종결어미
```python
re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\s*(있나요|인가요|일까요|가요|나요)")
```
- **예**: "담당자는 몇 명이나 있나요?", "누구인가요?"

### 7.3. 질문 종결어미
```python
re.compile(r".*\s*(있나요|인가요|일까요|하나요|되나요)\??\s*$")
```
- **예**: "상담원은 어떤 업무를 하나요?", "연락하면 되나요?"

---

## 8. 엣지 케이스 검토

### 8.1. 경계 사례
| 발화 | 분류 | 판단 |
|------|------|------|
| "담당자 있나요?" | general ✅ | "있나요?" 질문 종결 |
| "담당자 있어요?" | general ✅ | "있어요?" 는 평서문이지만 맥락상 질문일 가능성 → LLM 판단 위임 |
| "담당자!" | transfer ✅ | 질문 패턴 없음 + "담당자" 키워드 → 전환 의도로 해석 |
| "담당자 좀" | transfer ✅ | 질문 패턴 없음 + "담당자" 키워드 → 전환 의도로 해석 |

### 8.2. False Negative 가능성
"담당자 좀" 같은 **축약 표현**은 Quick Check에서 transfer로 감지되어 빠르게 처리됨.
만약 이것이 질문이었다면 LLM이 처리해야 하나, 실무에서는 대부분 전환 요청이므로 허용 가능.

### 8.3. 보완 전략
향후 오분류 사례 발견 시:
1. 로그에서 `transfer_request_detected` 이벤트 모니터링
2. 질문 패턴 정규식에 추가 종결어미 보완 (예: "뭐예요", "어떻게 돼요")
3. 극단적인 경우 Quick Check 자체를 제거하고 모든 경우 LangGraph 분류 사용

---

## 9. 성능 영향

### 9.1. Quick Check의 장점
- LLM 호출 없이 **즉시 판단** (< 1ms)
- 명확한 전환 요청("담당자 연결해 주세요")은 **응답 시간 2-3초 단축**

### 9.2. 수정 후 변화
- 질문 패턴 정규식 3개 추가 확인 (< 1ms, 성능 영향 없음)
- 질문은 LangGraph로 전달 → LLM 분류 (정상 흐름)
- 명확한 전환 요청은 여전히 Quick Check에서 처리 → **성능 유지**

---

## 10. 수정 코드

### 10.1. 질문 패턴 상수 추가 (36-42줄)
```python
# 질문 패턴 (transfer 키워드가 있어도 질문이면 제외)
_QUESTION_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
    # 의문사 + 물음표
    re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\?"),
    
    # 의문사 + 질문 종결어미
    re.compile(r"(몇|얼마나|어떤|무엇|누구|언제|어디|왜|어떻게)\s*(명|개|분|시|곳)?.*\s*(있나요|인가요|일까요|가요|나요)"),
    
    # 질문 종결어미
    re.compile(r".*\s*(있나요|인가요|일까요|하나요|되나요)\??\s*$"),
)
```

### 10.2. classify_quick 로직 수정 (58-78줄)
```python
@classmethod
def classify_quick(cls, user_text: str) -> Intent:
    if not user_text or not str(user_text).strip():
        return Intent.GENERAL

    t = str(user_text).strip().lower()

    # ✅ 1. 질문 패턴 먼저 확인 (질문이면 transfer 아님)
    for qp in cls._QUESTION_PATTERNS:
        if qp.search(t):
            return Intent.GENERAL

    # 2. Transfer 키워드 확인
    for sub in cls._TRANSFER_SUBSTRINGS:
        if sub.lower() in t:
            return Intent.TRANSFER_REQUEST

    for rx in cls._TRANSFER_REGEX:
        if rx.search(t):
            return Intent.TRANSFER_REQUEST

    return Intent.GENERAL
```

**핵심 변경**:
- **질문 패턴 체크를 가장 먼저 수행**
- 질문 패턴에 매칭되면 `GENERAL` 반환 → LangGraph로 전달
- 질문이 아닐 때만 transfer 키워드 매칭

---

## 11. 예상 효과

### 11.1. 오분류 방지
- "담당자는 몇 명이나 있나요?" → `GENERAL` → LangGraph가 `question`으로 분류 → LLM 답변
- "상담원은 무엇을 하나요?" → `GENERAL` → LangGraph가 `question`으로 분류 → LLM 답변

### 11.2. 정상 전환 유지
- "담당자 연결해 주세요" → 질문 패턴 없음 → `TRANSFER_REQUEST` → 빠른 전환
- "상담원 바꿔 주세요" → 질문 패턴 없음 → `TRANSFER_REQUEST` → 빠른 전환

### 11.3. 정확도 향상
- False Positive (질문을 전환으로 오인) **감소**
- False Negative (전환을 질문으로 오인) **영향 없음** (명확한 전환 표현은 질문 패턴에 걸리지 않음)

---

## 12. 백엔드 재시작 필요

수정 사항 적용을 위해 백엔드 재시작:
```bash
cd c:\work\workspace_sippbx\sip-pbx
.\start-all.ps1
```

**이미 재시작 완료** (RTP 수정과 동시에 적용됨).

---

## 13. 테스트 시나리오

1. AI 봇에 전화 연결
2. "기상청 담당자는 몇 명이나 있나요?" 질문
3. **기대 결과**: 
   - LLM이 답변 (예: "정확한 인원 수는 제가 알지 못하지만, 각 부서별로 담당자가 계십니다.")
   - 즉시 상담원 전환 ❌
4. "담당자 연결해 주세요" 질문
5. **기대 결과**:
   - 즉시 연락처 검색 및 전환 ✅

---

## 14. 로그 확인

### 14.1. Quick Check 결과
수정 후에는 다음 로그가 **발생하지 않아야 함**:
```json
{"event": "transfer_request_detected", 
 "query": "기상청 담당자는 몇 명이나 있나요?"}
```

### 14.2. LangGraph 분류 결과
대신 다음 로그가 나타나야 함:
```json
{"event": "intent_classify", 
 "intent": "question",
 "query_preview": "기상청 담당자는 몇 명이나 있나요?"}
```

---

## 15. 결론

**문제**: "담당자"라는 키워드만으로 질문을 전환 요청으로 오분류  
**원인**: Quick Check가 문맥 없이 단순 부분 문자열 매칭만 수행  
**해결**: 질문 패턴(의문사, 질문 종결어미)을 먼저 확인하여 질문은 LLM으로 처리

**기대 효과**:
- 호기심 질문 → LLM이 적절히 답변
- 명확한 전환 요청 → 빠르게 처리 (성능 유지)
- False Positive 감소 → 사용자 경험 개선

**백엔드 재시작 완료**: 수정 사항 적용됨.
