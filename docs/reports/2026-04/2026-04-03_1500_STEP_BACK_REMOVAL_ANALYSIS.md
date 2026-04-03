# Step-back Prompting 제거 분석 및 결정

**작성일**: 2026-04-03 15:00  
**상태**: 결정 완료 → 코드 적용  
**관련 파일**: `agent.py`, `step_back_prompt.py`, `adaptive_rag.py`

---

## 1. Step-back 현재 동작 방식

### 진입 조건 (`_route_after_rag`)
```python
def _route_after_rag(state):
    rag_results = state.get("rag_results") or []
    if not rag_results:      # ← RAG 결과 0건일 때만 실행
        return "step_back"
    return "generate_response"
```

`adaptive_rag` 에서 결과가 0건이 되는 경우:
- 검색 자체가 0건인 경우
- **`RAG_MIN_USEFUL_SCORE = 0.12` 필터에 의해 저품질 결과 전체 폐기된 경우** ← 주요 진입 경로

### Step-back 처리 순서 (진입 시)
1. LLM 호출: 쿼리를 "상위 개념 질문"으로 변환 (~1.5~2.5s)
2. 변환된 쿼리로 RAG 재검색 (~0.5~1.0s)
3. 기존 결과(0건)와 병합 → confidence +0.15

**총 소요: 2.0 ~ 3.5초** (bsn9Yr4gSC seq 4: `step_back` = **2.644초** 관측)

---

## 2. 문제점 분석

### 2-1. 이중 필터 모순 (설계 충돌)

```
adaptive_rag → RAG_MIN_USEFUL_SCORE(0.12) 필터 → 0건 → step_back 진입
step_back    → 상위 개념 쿼리로 재검색      → 검색 결과가 또 나옴
```

`RAG_MIN_USEFUL_SCORE` 필터는 **"score < 0.12인 문서는 LLM 컨텍스트 노이즈"** 라는 판단 하에 추가된 필터다.  
그런데 step_back이 재검색하는 "상위 개념 쿼리"도 **같은 Vector DB에서 같은 도메인 문서를 검색**한다.  
원본 쿼리가 도메인과 무관해서 0건이 된 것이라면 → 상위 개념화해도 의미 있는 문서가 나올 가능성이 낮다.

### 2-2. 비용 대비 효과

| 시나리오 | step_back 효과 | 소요 시간 |
|---|---|---|
| 도메인 질문인데 RAG miss | 상위 개념 재검색으로 관련 문서 발견 가능 | 2~3s 추가 |
| 완전 무관 잡담·chitchat | 재검색해도 0건 → return {} (낭비) | 2~3s 낭비 |
| 계절 감상 ("꽃이 폈더라") | 도메인 무관 → score 낮음 → 필터 → step_back → 또 0건 | 2~3s 낭비 |

**bsn9Yr4gSC seq 4 관측값**:
- step_back 진입: "꽃이 많이 폈더라고요" (계절 감상 → chitchat 경계)
- step_back 결과: **0건** (재검색 의미 없음)
- 소요: **2.644초** (전체 agent_graph_total 11.176s의 23.7%)

### 2-3. chitchat 분류 개선 후 step_back 진입 빈도 예측

이번 패치로 LLM 프롬프트에서 계절 감상 발화를 `chitchat`으로 명시했다.  
`chitchat` → `route_utterance` → `rag_mode=skip` → RAG 자체 미실행 → step_back 진입 불가.

**남은 step_back 진입 경로**: 진짜 도메인 질문인데 지식 베이스에 없는 경우 (예: 매우 구체적인 수치, 미래 예보 등)

### 2-4. 이 경우의 step_back 효과

원본: "내일 오전 9시 서울 강남구 기온은 정확히 몇 도예요?"  
→ 상위 개념: "서울 강남구 기온 정보" → 여전히 없으면 0건  

**step_back이 실질적으로 도움이 되는 케이스**: Vector DB에 상위 개념 문서는 있지만 구체 수치 문서는 없는 구조 → 현재 기상청 지식 베이스 구조상 이런 계층 구분이 체계적으로 구성되어 있지 않으면 효과 미미.

---

## 3. 결론: step_back 제거

| 항목 | 판단 |
|---|---|
| 기상청 도메인 질문 KB 구조 | 계층적 상위/하위 개념 분리 미흡 → step_back 이점 낮음 |
| RAG_MIN_USEFUL_SCORE 이중 필터 | 필터 통과 못한 것을 또 검색 → 모순 |
| chitchat 미분류 발화의 step_back | 2~3s 낭비, 0건 결과 |
| 실제 로그 효과 | 관측된 모든 step_back 실행이 0건 결과 후 return {} |
| 대안 | generate_response가 rag_results=[] 상태에서 LLM fallback 응답을 생성 → 충분 |

**→ step_back 노드를 그래프에서 제거. `adaptive_rag` 이후 항상 `generate_response` 진행.**

---

## 4. 개선 효과 예측

| 구간 | 이전 | 이후 |
|---|---|---|
| step_back (0건 케이스) | 2.6s | 0s (제거) |
| agent_graph_total (bsn9Yr4gSC seq4 기준) | 11.176s | ~8.5s 예상 |

---

## 5. 코드 변경 사항

- `agent.py`: `step_back` 노드 제거, `_route_after_rag` → 항상 `generate_response`로 단순화
- `step_back_prompt.py`: 파일 유지 (나중에 재활성화 필요 시 대비), 임포트만 제거
- `agent.py` `_LANGGRAPH_NODE_NAMES`: `"step_back"` 제거
- `_LANGGRAPH_SCHEMA_VERSION`: 4 → 5 (그래프 토폴로지 변경)
