# 지식베이스 연락처·호 전환 프론트엔드 불일치 수정

작성일: 2026-04-10 19:00  
상태: 완료  
관련 경로: `frontend/app/knowledge/add/page.tsx`, `frontend/types/index.ts`

---

## 개요

프론트엔드 지식 추가 페이지가 서버 API(`POST /api/knowledge`)와 정합하지 않는 부분을 점검하고 수정했다.  
특히 호 전환(transfer) 대상 번호 등록 시 실제로 ChromaDB에 저장되지 않는 치명적 불일치가 있었다.

---

## 발견된 문제

### 문제 1 — `transfer` 카테고리가 서버에서 무시됨 (치명)

| 구분 | 내용 |
|---|---|
| 프론트엔드 전송 필드 | `transfer_to`, `department_name` |
| 서버 `KnowledgeCreateBody` 모델 | 해당 필드 없음 → 수신 시 무시 |
| ChromaDB 저장 결과 | `phone_number` 메타 없음 → `contact_extractor.py`가 번호를 찾지 못함 |
| 영향 | `transfer` 카테고리로 등록해도 AI가 호 전환 번호를 인식하지 못함 |

서버는 `phone_number` / `department` 필드(contact 카테고리)만 ChromaDB 메타에 저장하도록 설계되어 있으며,  
`contact_extractor.py`도 `metadata.get("phone_number")`만 읽는다.  
`transfer` 카테고리는 설계상 존재하지 않는 카테고리였다.

### 문제 2 — `KNOWLEDGE_CATEGORIES`에 `contact` 항목 없음

`types/index.ts`의 `KNOWLEDGE_CATEGORIES` 배열에 `contact` 값이 없었다.  
카테고리 드롭다운에서 선택 자체가 불가능해 `contact` 방식으로 등록할 수 없는 상태였다.

---

## 변경 이력

| 파일 경로 | 변경 유형 | 요약 |
|---|---|---|
| `frontend/types/index.ts` | 수정 | `KNOWLEDGE_CATEGORIES`에 `{ value: "contact", label: "📞 연락처·호 전환" }` 추가, `transfer` 항목 제거 |
| `frontend/app/knowledge/add/page.tsx` | 수정 | `transfer` 카테고리 상태·분기·UI 전체 제거; `contact` UI 섹션을 호 전환 목적에 맞게 안내문·placeholder 개선 |

---

## 수정 후 데이터 흐름

```
프론트엔드 (category="contact")
  phone_number: "1003"          ← 착신번호
  department:  "상담원"          ← TTS 안내용 (선택)
  text:        "상담원 연결해줘" ← RAG 검색용 트리거 문장
        ↓
POST /api/knowledge
  KnowledgeCreateBody.phone_number → meta["phone_number"]
  KnowledgeCreateBody.department   → meta["department"]
        ↓
ChromaDB 저장 (category="contact", metadata.phone_number="1003")
        ↓
contact_extractor.py
  metadata.get("phone_number") → "1003"  ← 호 전환 착신번호
  metadata.get("department")   → "상담원" ← TTS 안내 문구
```

---

## 주요 결정 사항

- `transfer` 카테고리를 별도로 지원하지 않고 `contact`로 통합 — 서버 설계(contact_extractor)와 일치시킴
- `transfer_to` / `department_name` 필드를 서버에 추가하는 대신 `phone_number` / `department` 필드를 재사용 — 불필요한 API 변경 최소화

---

## 잔여 과제

없음. 서버 API(`knowledge_api.py`)는 이전 작업에서 이미 `phone_number`, `department`, `name` 필드를 지원하도록 수정됨.
