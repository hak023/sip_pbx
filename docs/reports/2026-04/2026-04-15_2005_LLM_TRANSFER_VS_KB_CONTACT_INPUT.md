## 메타

- 작성일: 2026-04-15
- 상태: 코드 점검 (동작 설명·UI 공백 정리)
- 관련: `rag_processor.py`, `hitl_alert.py`, `contact_extractor.py`, `knowledge_api.py`, `frontend/app/knowledge/page.tsx`

## 개요

LLM(LangGraph) 의도 `transfer`와 퀵 분류 `TRANSFER_REQUEST`가 호전환 시 KB `contact`를 쓰는지, 그리고 연락처 메타를 어디에 넣는지 정리한다.

## 결론 요약

1. **KB `contact` 벡터 검색 + `phone_number`로 `initiate_call_transfer`** 는 **`IntentClassifier.classify_quick` → `TRANSFER_REQUEST`** 일 때만 `rag_processor` 초반에서 수행된다.
2. **LangGraph가 `intent == "transfer"` 등으로 분류**해 `needs_human` / `needs_transfer` / `transfer_extension` 이 오는 경로는 **`hitl_alert_node`** 에서 **`escalation_mode`(페르소나) + 착신 규칙 `resolve_escalation_transfer_extension` + (폴백) 페르소나 `transfer_extension`** 으로 내선을 정한다. **Chroma `category == "contact"` 문서 내용을 읽어 전환 번호를 고르는 로직은 없다.**

## 연락처(contact) 저장 위치

- **API**: `POST /api/knowledge` 본문 `KnowledgeCreateBody` — `text`, `owner`, **`category: "contact"`**, 선택 **`phone_number`**, **`department`**, **`name`** (`knowledge_api.py`). Chroma 메타에 들어가며 `ContactKnowledgeExtractor`는 **`phone_number` 필수**다.
- **현재 메인 지식 UI** (`frontend/app/knowledge/page.tsx`): 일반 지식 POST 시 `text`, `owner`, `category`, `source`만 전송 → **`phone_number` 등을 보내지 않음**. `category=contact`만 고르면 검색 문서는 생기나 **전환용 번호 메타가 비어 호전환 퀵 경로가 실패할 수 있다.** 연락처 번호는 **동일 API에 `phone_number`(및 선택 필드)를 포함해 호출**하거나, UI에 필드를 추가해야 한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| (없음) | - | 코드 변경 없음 | 문서만 추가 |

## 잔여 과제

- `contact` 등록용 프론트 폼에 `phone_number` / `department` / `name` 필드 추가 검토.
