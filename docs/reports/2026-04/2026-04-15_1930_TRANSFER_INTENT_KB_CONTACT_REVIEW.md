## 메타

- 작성일: 2026-04-15
- 상태: 코드 점검 (변경 없음)
- 관련: `rag_processor.py`, `intents.py`, `contact_extractor.py`, 지식 카테고리 `contact`

## 결론

- 지식베이스에는 **`transfer`라는 카테고리가 없다.** 호 전환용 연락처는 **`category == "contact"`** 로 저장·검색한다 (`ContactKnowledgeExtractor`).
- 사용자 발화가 **`IntentClassifier.classify_quick` → `TRANSFER_REQUEST`** 로 분류되면, Chroma에서 **`owner` + `category: contact`** 로 벡터 검색한 뒤 `phone_number`로 `initiate_call_transfer` 를 호출한다.
- 연락처가 없으면 **call-control `resolve_escalation_transfer_extension`** 폴백 경로가 이어진다.

## “XX 바꿔줘”가 항상 전환으로 잡히는가

- 부사격 조사 + 동사 형태(`~으로 바꿔`, `~에게 연결` 등)는 **정규식 1**에 걸릴 수 있다.
- 단순 **`바꿔줘`만**(앞에 `해` 없음)은 정규식 2의 `(?:해\s*줘|…)` 와 맞지 않을 수 있고, 부분 문자열 목록에 **`바꿔` 단독은 없음** → **전환 의도로 안 잡힐 수 있다** (일반 RAG·LLM 경로로 감).

## 리포트 범위

프론트 `KNOWLEDGE_CATEGORIES` 의 `contact` 라벨이 “연락처·호 전환”인 이유와 위 파이프라인이 일치한다.
