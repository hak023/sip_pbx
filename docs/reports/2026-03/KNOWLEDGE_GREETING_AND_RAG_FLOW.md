# 지식베이스 인사(greeting_phase) 및 RAG 활용 흐름 (2026-03)

## 문제

- Chroma `knowledge` 컬렉션에 `category=greeting_phase1` / `greeting_phase2` 문서가 있어도, 초기 인사·역량 안내가 **테넌트 `greeting_templates`·고정 휴리스틱**만 사용되어 KB가 반영되지 않음.

## 수정 요약

1. **`knowledge_service.get_knowledge_greeting_text(vector_db, owner, category)`**
   - `list_knowledge(..., category=greeting_phase1|greeting_phase2)`로 조회 후 `metadata.created_at` 최신 1건, 본문 2자 이상만 채택.

2. **`ConversationAgent` (`langgraph/agent.py`)**
   - **`generate_greeting`**: KB `greeting_phase1` → `tenant_config` 랜덤 템플릿 → 기본 문구.
   - **`generate_capability_guide`**: KB `greeting_phase2` → capabilities 기반 문장.

3. **`RAGLLMProcessor` (`pipecat/processors/rag_processor.py`)**
   - 레거시 인사 경로 `_generate_greeting_legacy` / `_generate_capability_guide_legacy`에서도 동일 우선순위(KB → 폴백).
   - 동작 조건: `self._vector_db` 및 `self._owner` 설정됨.

## 지식베이스를 AI가 쓰는 경로 (전체)

| 구분 | 경로 |
|------|------|
| **대화 중 RAG** | RAG 엔진이 `owner` 기준으로 Chroma 검색 → LLM 컨텍스트 (기존 설계 유지). |
| **통화 시작 인사** | 위 `get_knowledge_greeting_text` + LangGraph/Pipecat 레거시 인사 모두 동일 우선순위. |
| **역량 안내(phase2)** | `greeting_phase2` KB → 없으면 capabilities 문장 생성. |

## 운영 체크리스트

- Chroma에 해당 **테넌트 `owner`**와 일치하는 메타로 문서가 들어가 있는지.
- Pipecat 통화 시 `call_manager`가 `build_and_run(..., vector_db=getattr(_rag, 'vector_db', None), ...)`로 전달 — **`_rag`가 없거나 `vector_db` 미초기화면 KB 인사는 스킵**되고 폴백만 사용됨.
- 인사 문구가 비어 있거나 2자 미만이면 다음 후보로 넘어감.

## 관련 파일

- `src/ai_voicebot/knowledge/knowledge_service.py`
- `src/ai_voicebot/langgraph/agent.py`
- `src/ai_voicebot/pipecat/processors/rag_processor.py`
- `src/sip_core/call_manager.py` (Pipecat 인자 전달)
