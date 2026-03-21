# ChromaDB 지식 분류 체계 및 인입 데이터 예시

**작성일**: 2026-03-16  
**배경**: [CALL_SaE6Smt5g3_RAG_DEBUG.md](../reports/2026-03/CALL_SaE6Smt5g3_RAG_DEBUG.md) — question 시 category 제한 제거 후, 데이터 증가에 대비한 **세분화 분류** 및 **인입 경로별 예시** 정리.

---

## 1. 인입 데이터 예시 (경로별)

앞으로 ChromaDB에 들어올 수 있는 데이터를 **경로(출처)** 와 **형태** 기준으로 정리했다.

### 1.1 API/대시보드 수동 입력 (현재 구현)

| 필드 예시 | 설명 | category 예시 |
|-----------|------|----------------|
| text | 지식 본문 | - |
| owner | 착신자(테넌트) ID | 1004 |
| category | 사용자 지정 1개 | greeting_phase1, weather_forecast, faq 등 |
| answer | greeting/farewell 시 캐시용 답변 | (선택) |
| source | 출처 | api |

**예시 레코드**:
```json
{
  "text": "오늘 날씨는 기상청 홈페이지에서 확인하실 수 있습니다.",
  "owner": "1004",
  "category": "weather_forecast",
  "source": "api"
}
```

### 1.2 HITL(운영자 응답) → 지식 저장 (현재 구현)

| 필드 예시 | 설명 | 저장 형태 |
|-----------|------|-----------|
| question | 발신자 질문 | Q: ... \n A: ... |
| answer | 운영자 입력 답변 | (위 텍스트에 포함) |
| category | 운영자 선택 (기본 faq) | faq, weather_forecast 등 |
| source | 고정 | hitl |
| call_id, operator_id | 추적용 | 메타데이터 |

**예시 레코드** (통화로 적재 → doc_type=knowledge, source=hitl):
```json
{
  "documents": ["Q: 내일 비 오나요?\nA: 실시간 예보는 기상청 홈페이지에서 확인해 주세요. 전화로는 구체적 지역 예보를 안내하기 어렵습니다."],
  "metadatas": [{
    "doc_type": "knowledge",
    "category": "faq",
    "source": "hitl",
    "owner": "1004",
    "call_id": "abc123",
    "operator_id": "op_01"
  }]
}
```

### 1.3 대화(통화) 추출 → 검토 후 적재 (구현됨)

**규칙: 유저 간 통화로 적재되는 경우 doc_type = knowledge.**

| 필드 예시 | 설명 | doc_type / source |
|-----------|------|-------------------|
| 대화 중 AI/상담원 발화에서 추출된 Q&A 또는 사실 | 자동 추출 후 검토 승인 | doc_type=knowledge, source=call |
| review_status | 검토 상태 (별도 플로우) | pending → approved |
| owner, category | 검토 시 지정 | - |

**예시 레코드** (검토 승인 후):
```json
{
  "documents": ["Q: 영업시간이 어떻게 되나요?\nA: 평일 09:00~18:00입니다. 긴급 시 24시간 운영합니다."],
  "metadatas": [{
    "doc_type": "knowledge",
    "source": "call",
    "review_status": "approved",
    "category": "service_info",
    "owner": "1004",
    "call_id": "xyz789"
  }]
}
```

### 1.4 메뉴얼/문서 업로드 (미구현 가정)

| 가정 필드 | 설명 | 제안 분류 |
|-----------|------|------------|
| 제목/챕터 | 메뉴얼 제목, 1장/2장 등 | doc_type=manual_chunk, sub_category 또는 chapter |
| 페이지/섹션 | 원본 위치 | section_id, page_no (메타데이터) |
| 청크 텍스트 | 자동 분할된 문단 | documents |
| 원본 파일 ID | 동일 메뉴얼 묶음 | manual_id 또는 document_id |

**예시 레코드** (미구현):
```json
{
  "documents": ["2.1 절차 안내: 고객이 문의 시 먼저 고객센터(131)로 안내하고, 상담원 연결을 원하면 전환 버튼을 누릅니다."],
  "metadatas": [{
    "doc_type": "manual_chunk",
    "category": "procedure",
    "manual_id": "manual_1004_001",
    "chapter": "2",
    "section": "2.1",
    "title": "상담 업무 절차",
    "owner": "1004",
    "source": "manual_upload"
  }]
}
```

### 1.5 시드/배치 데이터 (현재 구현)

| 출처 | 형태 | category 예시 |
|------|------|----------------|
| seed_data.py | 테넌트별 KNOWLEDGE_DATA, FAQ_DATA, CAPABILITIES | menu, hours, weather_forecast, faq, capability 등 |
| source | seed (명시 여부는 구현별 상이) | - |

---

## 2. 현재 메타데이터 필드 정리

ChromaDB에 실제로 쓰이는 필드(구현 기준):

| 필드 | 용도 | 비고 |
|------|------|------|
| owner | 테넌트 격리, RAG where 조건 | API/시드에는 있음. add_from_hitl은 owner_id 사용 → 통일 권장 |
| category | 도메인/주제 (단일 값) | 테넌트별로 상이(menu, weather_forecast, faq 등) |
| doc_type | 문서 유형 구분 | capability, tenant_config, extraction 등. 일반 지식은 비어 있을 수 있음 |
| source | 출처 | api, hitl, seed 등 |
| keywords | 검색/표시 보조 | 문자열(쉼표 구분) |
| created_at | 생성 시각 | - |
| call_id, operator_id | HITL/추출 추적 | 선택 |

**한계**:
- “지식”이 한 컬렉션에 다 들어가면, **출처(doc_type/source)** 와 **도메인(category)** 만으로는 “메뉴얼 2장만 검색” 같은 세분화가 어렵다.
- category를 너무 많이 늘리면 RAG에서 intent별 매핑이 복잡해지고, 하나로만 쓰면 “question에 다 몰림”이 되어 관리·품질 제어가 어렵다.

---

## 3. 제안: 이원화 분류 (doc_type + category)

데이터가 많아져도 **관리**와 **RAG 검색** 둘 다 만족하려면, **문서 유형**과 **도메인(주제)** 를 분리하는 구도를 추천한다.

### 3.1 doc_type (문서 유형) — “무슨 종류인가”

| doc_type | 설명 | RAG 검색 시 비고 |
|----------|------|-------------------|
| **knowledge** | 일반 지식. **API 입력, 시드, HITL 저장, 통화 추출 승인** 모두 이 유형으로 적재 (통화로 적재되는 경우 = knowledge) | question intent 시 owner만 필터해 전부 검색 |
| faq | Q&A 형태 (시드 FAQ 구분용 등) | 동일. 필요 시 where에 doc_type=faq 추가 가능 |
| capability | 서비스/기능 정의 | 별도 API로 조회. RAG 검색에서 제외할지 선택 |
| manual_chunk | 메뉴얼/문서 청크 (미구현) | 검색 포함. 필터 시 manual_id, chapter 등 활용 |
| greeting_phase1, greeting_phase2 | 인사말 | greeting intent에서만 category로 필터 (현재처럼) |
| farewell | 마무리 인사 | farewell intent에서만 |

- **정리**: “일반 질의에 답할 때”는 **owner만** 걸고, doc_type은 **관리·통계·필터 옵션**으로만 쓰면 된다.  
- greeting/farewell만 intent별로 **category**를 제한하는 현재 방식 유지.

### 3.2 category (도메인/주제) — “무슨 내용인가”

테넌트마다 다르게 정의할 수 있도록 **고정 열거보다는 “테넌트별 허용 목록”** 또는 **자유 문자열 + 대시보드에서 선택**을 권장한다.

| 용도 | 예시 (1004 기상청) | 예시 (1003 레스토랑) |
|------|---------------------|----------------------|
| 도메인 구분 | weather_forecast, weather_warning, service_info, application, weather_knowledge | menu, hours, location, reservation, policy, event |
| 공통 보조 | faq (Q&A 공통), procedure (절차) | faq, procedure |
| 인사/마무리 | greeting_phase1, greeting_phase2, farewell | 동일 |

- **세분화 예**:  
  - 메뉴얼이 들어오면: `category=procedure`, `sub_category=상담절차` 또는 `chapter=2` 처럼 **보조 필드**로 더 쪼갤 수 있다.  
  - “question일 때 category 필터 안 건다”는 현재 동작은 유지하고, **관리/목록/통계**에서만 category·doc_type으로 필터링하면 된다.

### 3.3 선택: sub_category / tags

- **sub_category**: 같은 category 안에서 더 잘게 나누고 싶을 때 (예: menu → sub_category=파스타, 피자).
- **tags**: 쉼표 구분 문자열로 “할인”, “영업시간”, “131” 등 여러 태그를 붙여서, 나중에 where나 후처리 필터로 쓸 수 있게.

둘 다 ChromaDB 메타데이터는 문자열만 허용하므로, 리스트는 `",".join(tags)` 형태로 저장하면 된다.

---

## 4. 인입 경로별 메타데이터 제안 요약

| 인입 경로 | doc_type | category | source | 기타 권장 필드 |
|-----------|----------|----------|--------|----------------|
| API/대시 입력 | knowledge | 사용자 선택(도메인) | api | owner, keywords |
| HITL 저장 (통화로 적재) | **knowledge** | 운영자 선택(기본 faq) | hitl | owner, call_id, operator_id |
| 통화 추출 승인 (통화로 적재) | **knowledge** | 검토 시 지정 | call | owner, review_status, call_id |
| 메뉴얼 업로드 (미구현) | manual_chunk | 절차/운영 등 | manual_upload | owner, manual_id, chapter, section, title |
| 시드 데이터 | knowledge 또는 capability | 기존 유지 | seed | owner |

---

## 5. RAG 검색 측에서의 활용

- **question / unknown intent**:  
  - **owner만** where에 넣고, **category/doc_type 제한 두지 않음** (현재와 동일).  
  - 데이터가 아주 많아지면: **doc_type in [knowledge, faq, manual_chunk]** 만 검색하도록 옵션을 둘 수 있고, capability는 제외하는 식으로 조정 가능.
- **greeting / farewell**:  
  - 지금처럼 **category in [greeting_phase1, greeting_phase2]** 또는 **farewell** 로만 필터.
- **관리/대시보드**:  
  - 목록·통계·삭제 시 **doc_type**, **category**, **source** 로 필터 및 세분화 표시.

---

## 6. 정리 및 다음 단계 제안

1. **인입 데이터 예시**  
   - API, HITL, 통화 추출, (미구현) 메뉴얼, 시드 등 경로별 예시를 위와 같이 정의해 두었음.
2. **세분화 분류**  
   - **doc_type**: 문서 유형. **통화로 적재되는 경우(HITL, 통화 추출 승인)는 모두 knowledge.**  
   - knowledge, faq, capability, manual_chunk 등. category는 greeting_phase1/2, farewell 등 인사용.  
   - **category**: 도메인/주제(테넌트별, 예: weather_forecast, menu, procedure).  
   - **source**: 출처(api, hitl, seed, call, manual_upload).  
   - 필요 시 **sub_category**, **tags** 로 더 쪼개서 관리.
3. **호환성**  
   - 기존 “question 시 category 안 건다” 동작은 유지.  
   - 새로 적재되는 데이터부터 **doc_type**, **source** 를 꼭 넣고, **owner_id → owner** 로 통일하면 이후 관리·확장에 유리하다.

이 문서를 기준으로 메뉴얼 업로드 스키마나 대화 추출 검토 플로우를 설계할 때, 위 인입 예시와 doc_type/category 체계를 그대로 참고하면 된다.
