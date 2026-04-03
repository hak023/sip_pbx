# Call Tu48lwdl6s — 이슈 점검 리포트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-04-03 11:20 |
| 대상 call_id | `Tu48lwdl6s` |
| 로그 파일 | `sip-pbx/logs/call_data_record_20260403.log` (line 32–100) |
| 상태 | 이슈 1 수정 완료 / 이슈 2·3 개선 방안 문서화 |

---

## 1. JSON 응답이 TTS로 송출된 이슈

### 로그 근거 (line 63–64)

```
seq 3 발화: "바다에 금박 통제에 대해서 문의하려면 어디로 연락을 해야 될까요?"
llm_exchange.response:
  "```json\n{\"intent\": \"question\", \"search_query\": \"바다 금박 통제 문의 연락처\"}\n```\n바다의 통제 사항에 대해 문의하시려면 해양경찰청으로 연락하시면 됩니다."

tts_text_pushed:
  "```json\n{\"intent\": \"question\", \"search_query\": \"바다 금박 통제 문의 연락처\"}\n```\n바다의 통제 사항에 대해 문의하시려면 해양경찰청으로 연락하시면 됩니다."
```

### 원인 분석

LLM(Gemini)이 **인바운드 응답 프롬프트**임에도 불구하고 JSON 형식 블록을 응답 앞에 붙여 반환했다. 원인은 두 가지가 복합적으로 작용했을 가능성이 있다:

1. **컨텍스트 오염**: 대화 기록(messages)에 이전 턴의 LLM 응답(JSON 형식 아웃바운드 응답 등)이 포함되어 있으면 LLM이 해당 형식을 모방한다.
2. **시스템 프롬프트 vs 파인튜닝 편향**: Gemini 계열 모델이 JSON 출력으로 훈련된 경우, 특정 쿼리 패턴에서 JSON prefix를 자동 삽입하는 경향이 있다.

아웃바운드 경로에서는 `_parse_outbound_llm_json()`이 JSON을 분리·정제하지만, **인바운드 경로에는 동등한 필터가 없어** JSON 원문이 TTS로 그대로 전달됐다.

### 수정 내용 (`generate_response.py`)

`_strip_json_and_markdown_for_tts()` 함수 추가 후 인바운드 응답 처리 경로에 적용:

```python
# 인바운드: LLM이 JSON/마크다운 블록을 섞어 응답한 경우 정제
if not _is_outbound and response:
    response = _strip_json_and_markdown_for_tts(response)
```

처리 로직:

| 케이스 | 처리 |
|--------|------|
| ` ```json{...}``` ` 코드블록 전체 | 마크다운 펜스 제거 후 `response` 필드 추출 |
| JSON 블록 + 뒤에 일반 텍스트 | JSON 블록 제거, 뒤 텍스트만 TTS 사용 |
| 전체가 JSON `{...}` | `response` 키 추출, 없으면 raw 반환 |
| 마크다운만 있는 경우 | 펜스 제거 후 텍스트 사용 |

> **수정 파일**: `sip-pbx/src/ai_voicebot/langgraph/nodes/generate_response.py`

---

## 2. seq 5 — 의도 오분류 문제 (키워드 매칭의 한계)

### 현상

```
seq 5 발화: "네임에 서울의 날씨를 알려 주세요."
→ intent_classify: path="keyword", intent="affirm"  ← 오분류
→ template_response: "네, 알겠습니다. 더 필요하시면 말씀해 주세요."
→ (날씨 질문 RAG 처리 안 됨)
```

### 원인 분석

`_keyword_matches_intent()`의 **"네" affirm 제외 규칙**이 불완전하다:

```python
# 현재 코드
if kw == "네":
    for m in re.finditer("네", query_lower):
        if m.end() < len(query_lower) and query_lower[m.end()] in ("가", "는", "도"):
            continue  # 네가, 네는, 네도만 제외
        return True   # 그 외는 affirm으로 처리
    return False
```

"**네임**"의 경우:
- "임" 이 뒤에 붙지만 제외 목록 `("가", "는", "도")`에 없음 → affirm 통과
- 실제로는 "이름"(name)의 의미로 사용된 단어

### 근본적 문제: 키워드 매칭의 구조적 한계

단순 자소/부분 문자열 매칭은 다음과 같은 케이스에서 반드시 오류가 발생한다:

| 발화 패턴 | 오인식 원인 | 실제 의도 |
|-----------|-------------|-----------|
| "**네임**에 서울 날씨" | "네" → affirm | question |
| "**네**이버에서 확인하면" | "네" → affirm | question |
| "**네**일 계획이 있어서" | "네" → affirm | question / chitchat |
| "**비**가 와요" | "비" → question (날씨) | chitchat |
| "**감사합**니다" vs "**감사합**니까" | "감사합" 공통 | farewell vs question |

**키워드 매칭은 속도(< 1ms) 측면에서 탁월하나, 문맥/형태소를 고려하지 않아 오분류율이 높아질 수 있다.**

### 개선 방안 (우선순위 순)

#### 방안 A. "네" affirm 제외 규칙 강화 (즉시 적용 권장)

현재 `("가", "는", "도")`만 제외하는 것에서 **뒤에 한글 자음/모음이 연결되면 제외**하는 방식으로 변경:

```python
if kw == "네":
    for m in re.finditer("네", query_lower):
        pos = m.start()
        end = m.end()
        # 앞에 한글 음절이 있으면 단어 내부 → 제외 (이름→"임네", 네임→"네임")
        if pos > 0 and _is_hangul_syllable(query_lower[pos - 1]):
            continue
        # 뒤에 한글 음절이 있으면 합성어 → 제외 (네임, 네이버, 네가 모두 포함)
        if end < len(query_lower) and _is_hangul_syllable(query_lower[end]):
            continue
        return True  # 독립 "네" (문장 끝, 공백 뒤)
    return False
```

이 규칙으로 "네임", "네이버", "네가", "네는" 등 모두 affirm에서 제외되고,
"네.", "네!", "네 " (공백), 문장 끝 "네" 만 affirm으로 인식된다.

#### 방안 B. 키워드 매칭 전 question 키워드 선행 확인 (중기)

`affirm` 키워드 확인 전에 **명확한 question 지시어**가 있으면 question으로 먼저 처리:

```python
STRONG_QUESTION_INDICATORS = [
    "알려주세요", "알려줘", "알려 주세요", "알려 줘",
    "가르쳐주세요", "설명해주세요", "어떻게 해요", "어떻게 되나요",
    "어디예요", "어디인가요", "언제예요", "언제인가요",
]

# classify_intent_node 최상단에서 먼저 체크
if any(ind in query_lower for ind in STRONG_QUESTION_INDICATORS):
    return {"intent": "question", "slots": {}, "confidence": 1.0}
```

`"알려 주세요"`가 이미 `INTENT_KEYWORDS["question"]`에 있지만, question은 `INTENT_KEYWORDS` 순서상 **마지막**에 체크된다. affirm보다 먼저 처리되어야 하는 strong indicator를 별도로 분리한다.

#### 방안 C. LLM fallback에 대화 컨텍스트 포함 (중기)

키워드 매칭 실패 시 LLM 분류를 수행하는데, 현재는 현재 발화만 LLM에 전달한다. 최근 1턴의 AI 응답을 함께 전달하면 "서울의 날씨를 알려 주세요" 맥락에서 affirm이 아니라 question임을 더 정확히 분류할 수 있다.

#### 방안 D. 형태소 분석 도입 (장기)

`kiwi`(한국어 형태소 분석기, C 기반 Python 바인딩)를 사용하면 "네임"을 `NNP(고유명사)` 또는 `NNG(일반명사)`로 분류하여 `MAJ(감탄사)`인 "네"와 정확히 구분 가능. 단, 추가 의존성 및 latency 비용 발생.

### 권장: 방안 A + B를 즉시 적용

---

## 3. 처리 속도 분석 및 seq 1 개선 포인트

### 전체 발화별 소요 시간

| seq | 발화 (요약) | agent_graph 소요 | 주요 병목 | 비고 |
|-----|------------|-----------------|-----------|------|
| 1 | 정보나 규모를 알 수 있을까요? | **12.335s** | check_cache(3.94s) + llm_generate(6.21s) + classify_intent(2.07s) | ⚠ 극히 느림 |
| 2 | 지진 대피 신고 어디로? | 2.393s | llm_generate(2.36s) | ✅ 정상 |
| 3 | 바다 금박 통제 문의 | 2.794s | llm_generate(2.69s) | ✅ 정상 (JSON 오염 있음) |
| 4 | 기상 감정서 발급 | 2.822s | llm_generate(2.78s) | ✅ 정상 |
| 5 | 네임에 서울 날씨 | 0.011s | — | ⚠ 오분류로 template 응답 |
| 6 | 내일 서울 날씨 | 2.937s | llm_generate(2.79s) + adaptive_rag(0.13s) | ✅ 정상 |
| 7 | 네 감사합니다 | 0.007s | — | ✅ farewell 정상 |

### seq 1 상세 분석 (12.335s)

```
check_cache:     3.939s  ← 심각 (timeout 1.5s 적용됐어야 함)
classify_intent: 2.073s  ← LLM 분류 (llm_merged 경로)
adaptive_rag:    0.110s  ← 양호
rewrite_query:   0.002s  ← skip_merged (정상)
generate_response: 6.208s ← LLM 응답 생성
```

#### check_cache 3.939s 문제

`CACHE_SEARCH_TIMEOUT_SEC = 1.5`가 설정되어 있음에도 3.94s가 소요됐다.

**원인**: `miss_reason: "no_search_results"` — 컬렉션은 존재하지만 벡터 검색 결과가 0건. 이 경우 ChromaDB `query()` 자체가 3.9s를 소비한 것으로, timeout이 적용되지 않았거나 ChromaDB 내부 인덱스 초기화 비용(cold start)이 발생한 것으로 추정된다.

로그 seq 2~4에서는 `miss_reason: "empty_qa_cache_collection"` (0.002~0.004s)인 것과 대조적으로, seq 1은 컬렉션에 데이터가 있어 벡터 검색이 실제로 수행됐다.

**확인 포인트**: `asyncio.wait_for()`가 실제로 timeout을 트리거했는지 로그에서 `cache_search_timeout` 이벤트를 확인 필요. timeout 로그가 없다면 `CACHE_SEARCH_TIMEOUT_SEC` 적용 코드 경로 점검 필요.

#### classify_intent 2.073s 문제 (path: llm_merged)

`"정보나 규모를 알 수 있을까요?"` — 이 발화는:
- "정보", "규모": INTENT_KEYWORDS에 없음
- "알 수 있을까요?": "알" 자체가 없고 "알려줘/알려주세요"도 없음

→ 키워드 매칭 실패 → LLM 분류 (2.07s)

seq 2~7에서는 keyword 경로(0.0s)로 처리됐는데, seq 1은 유일하게 LLM 분류를 탔다.

**개선**: `INTENT_KEYWORDS["question"]`에 추가:
```python
"알 수 있", "알 수 있을까", "알 수 있나요", "알 수 있어요",
"어디서", "어디에서",
```

#### generate_response 6.208s 문제

- rag_hit_count: 5건 (soft fallback 적용, 모두 낮은 score: 최고 0.1729)
- response_len: 66자 (짧음)

LLM이 6.2s를 소비했다는 것은 Gemini API의 cold start 또는 응답 품질 결정 지연으로 추정. 정상 턴(seq 2~4)의 generate_response가 2.3~2.8s인 것과 비교하면 약 2.5~3배 지연.

**가능한 원인**:
1. **컨텍스트 길이**: seq 1은 첫 번째 발화이므로 대화 기록이 없어 오히려 짧아야 하나, RAG 컨텍스트(5건 × full text)가 긴 경우 프롬프트 토큰이 증가했을 수 있음
2. **Gemini API 서버 부하**: 해당 시각(09:50:36)에 API 지연 발생
3. **소프트 폴백 적용**: 엄격 임계치 초과 문서가 없어 soft floor로 5건 모두 낮은 품질 문서 → LLM이 답변 생성에 더 많은 추론을 수행

### 개선 포인트 요약

| 번호 | 항목 | 기대 효과 |
|------|------|-----------|
| 3-1 | `"알 수 있"` 계열 키워드 question에 추가 | classify_intent 2.07s → 0ms |
| 3-2 | check_cache timeout 실제 동작 여부 검증 | 3.94s → 최대 1.5s |
| 3-3 | soft fallback 문서 품질 필터 강화 (score < 0.12 제외) | generate_response 컨텍스트 노이즈 감소 |
| 3-4 | RAG 컨텍스트 최대 문서 수 인바운드 3건 유지 확인 | 프롬프트 토큰 절감 |

---

## 조치 이력

| 이슈 | 상태 | 수정 파일 |
|------|------|-----------|
| 1. JSON TTS 송출 | ✅ 수정 완료 | `generate_response.py` |
| 2. seq 5 affirm 오분류 (방안 A) | 📋 리포트 작성, 코드 적용 대기 | `classify_intent.py` |
| 2. seq 5 affirm 오분류 (방안 B) | 📋 리포트 작성, 코드 적용 대기 | `classify_intent.py` |
| 3. seq 1 classify_intent 키워드 보완 | 📋 리포트 작성, 코드 적용 대기 | `classify_intent.py` |
| 3. seq 1 check_cache timeout 검증 | 🔍 로그 추가 모니터링 필요 | `semantic_cache.py` |
