# "상담원 연결해줘" — capability 지식·RAG·1004 전환 점검

- **작성일**: 2026-03-23  
- **상태**: 코드 기준 점검 완료  
- **전제**: Pipecat `RAGLLMProcessor._process_with_agent` 경로(실통화 AI 파이프라인)

---

## 1. 질문 요약

대시보드에 `doc_type=capability`, `owner=1004`, 내용이 전환 안내인 시드(예: `cap_1004_transfer`)가 있을 때:

1. **RAG 검색으로 해당 지식이 매칭되는가?**  
2. **1004번으로 호 전환이 수행되는가?**

---

## 2. 결론 (한 줄)

| 항목 | 결과 |
|------|------|
| **1. RAG로 capability 매칭** | **아니오** — 전환 요청 문장은 **RAG/에이전트 일반 경로 전에** 별도 “퀵 경로”로 처리되며, 그 경로는 **`ContactKnowledgeExtractor`만** 사용한다. **`doc_type=capability`는 조회 대상이 아니다.** |
| **2. 1004 전환 실행** | **위 지식만으로는 아니오** — 실제 전환은 `search_contact`가 반환한 **`phone_number`가 있을 때만** `initiate_call_transfer`가 호출된다. 연락처 검색은 **`category == "contact"`** 만 본다. capability의 **`transfer_to` 메타는 이 경로에서 읽히지 않는다.** |

(설정 `ai_voicebot.rag.doc_type_allowlist`에 `capability`를 넣었는지와 무관하게, **해당 발화는 퀵 경로에서 RAG를 타지 않는다.**)

---

## 3. 근거: 발화 처리 순서

### 3.1 "상담원 연결해줘" → 전환 퀵 의도

`IntentClassifier.classify_quick`는 부분 문자열에 **"상담원"** 등이 있으면 `TRANSFER_REQUEST`를 반환한다.

- 파일: `src/ai_voicebot/pipecat/intents.py` (`_TRANSFER_SUBSTRINGS`에 `"상담원"` 포함)

### 3.2 퀵 경로: RAG 미사용, 연락처만 검색

`rag_processor.py`의 `_process_with_agent` 초반:

- `quick_intent == Intent.TRANSFER_REQUEST` 이면  
- `ContactKnowledgeExtractor.search_contact(query, tenant_id=owner)` 만 호출  
- 성공 시 `emit_transfer_initiated` + `initiate_call_transfer(target_number=contact['phone_number'])`  
- 실패 시 고정 멘트 후 **`return`** → **이하 RAG / LangGraph 에이전트 호출 없음**

### 3.3 연락처 검색 조건

`contact_extractor.py`:

- Chroma `where`: **`owner` + `category: "contact"`**  
- 메타에서 `department`, `phone_number`, `name` 사용 — **`phone_number` 없으면 None**

따라서 스크린샷과 같은 **`doc_type=capability`**, **`category=transfer`**(전환/연결 안내) 문서는 **이 쿼리에 절대 걸리지 않는다.**

### 3.4 capability의 `transfer_to`

`KnowledgeService.add_capability`는 `transfer_to`를 메타에 넣을 수 있으나, **전환 퀵 경로의 연락처 검색은 capability 컬렉션/메타를 보지 않는다.**

---

## 4. 가설적: 퀵 경로가 없었다면 RAG는 capability를 볼 수 있나?

- `RAGEngine`은 `doc_type_allowlist`가 **없으면** `doc_type`으로 필터하지 않으므로, 이론상 **`capability`도 후보**가 될 수 있다.  
- `intent=transfer`일 때 `category`는 `question, complaint, transfer, chitchat, contact` 등의 `$in` — 대시보드에서 capability의 **`category`가 `transfer`면** 필터는 통과 가능.  
- 다만 **실제 "상담원 연결해줘"는 퀵 경로에서 끝나므로**, 이 RAG 시나리오는 **현재 파이프라인에서 해당 발화에 적용되지 않는다.**

---

## 5. 운영 권장 (코드 변경 없이)

- **1004로 실제 전환**을 원하면: 지식에 **`category=contact`** 인 행을 추가하고, 메타에 **`phone_number`(및 필요 시 `department`)** 를 넣어 `ContactKnowledgeExtractor`가 찾게 한다.  
- 또는 (향후 개선): 퀵 경로에서 **`doc_type=capability` + `transfer_to` / `response_type`** 을 조회하도록 확장하는 설계 검토.

---

## 6. 관련 파일

| 파일 | 역할 |
|------|------|
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 전환 퀵 경로, `search_contact` → `initiate_call_transfer` |
| `src/ai_voicebot/pipecat/intents.py` | `classify_quick`, 상담원/연결 키워드 |
| `src/ai_voicebot/knowledge/contact_extractor.py` | `category=contact`만 검색 |
| `src/services/knowledge_service.py` | `add_capability`, `transfer_to` 메타 저장 |
| `src/ai_voicebot/ai_pipeline/rag_engine.py` | 일반 RAG (퀵 경로 미통과 시에만 해당 턴에서 활용) |
