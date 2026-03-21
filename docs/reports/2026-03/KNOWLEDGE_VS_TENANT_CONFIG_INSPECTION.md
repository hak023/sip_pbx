# 지식 베이스 ↔ tenant_config 반영 여부 점검

**기준 문서**: [VECTORDB_TENANT_CONFIG_BRIEF.md](./VECTORDB_TENANT_CONFIG_BRIEF.md)  
**점검 질문**: 프론트엔드 지식 베이스에 입력한 내용이 **테넌트 config(tenant_config)** 에 반영되도록 구현되어 있는지.

---

## 1. 결론

| 구분 | 반영 여부 | 비고 |
|------|-----------|------|
| **tenant_config에 반영** | **아니오** | 지식 API는 tenant_config를 읽거나 쓰지 않음. |
| **qa_cache / knowledge에 반영** | **예** | 지식 베이스 입력 → knowledge + (greeting_phase1/2, farewell 시) qa_cache 즉시 반영. |

즉, **“지식 베이스에 입력하면 tenant_config에 반영된다”** 고 볼 수 있는 연결 코드는 **sip-pbx에 없음**.

---

## 2. 현재 구현 정리

### 2.1 지식 베이스(프론트) → 백엔드

- **API**: `POST /api/knowledge` (body: `text`, `owner`, `category`, `answer` 등)
- **처리**: `knowledge_router.py` → `knowledge_service.add_knowledge()` → **KNOWLEDGE_COLLECTION** 저장.
- **추가 동작**: `category`가 `greeting_phase1`, `greeting_phase2`, `farewell` 이고 `answer`가 있으면  
  `immediate_cache_for_knowledge()` 로 **QA_CACHE_COLLECTION(qa_cache)** 에 즉시 upsert (TTL 7일).

→ 지식 베이스 입력은 **knowledge**와 **qa_cache** 에만 반영됨. **tenant_config 컬렉션/저장소는 사용하지 않음.**

### 2.2 tenant_config 사용처 (org_manager)

- **문서(VECTORDB_TENANT_CONFIG_BRIEF)** 에 따르면, **org_manager**가 owner별로 **VectorDB(또는 연동 저장소)의 tenant_config** 를 조회함.
- **sip-pbx 내 사용처**: `src/ai_voicebot/langgraph/agent.py`
  - `generate_greeting()` → **org_manager.get_random_greeting_template()** (Phase1 인사말)
  - `generate_capability_guide()` → **org_manager.load_capabilities()**, **get_capabilities()** (Phase2 안내)
- **sip-pbx 내에는** tenant_config를 **쓰는(저장/갱신)** 코드가 없고, **읽는 쪽(org_manager)** 도 sip-pbx가 아니라 외부/파이프라인에서 주입된 **org_manager** 를 통해 사용하는 구조로 보임.

→ **통화 시작 시 AI가 먼저 말하는 Phase1/Phase2** 는 **tenant_config(org_manager)** 에서 나옴.  
→ 이 tenant_config는 **지식 API와 연결되어 있지 않음**.

### 2.3 qa_cache 사용처 (지식 베이스와 연결됨)

- **노드**: `greeting_farewell_cache.py` — intent가 `greeting` 또는 `farewell` 일 때 **qa_cache** 를 intent로 필터해 검색.
- **동작**: 사용자가 인사/종료 발화를 했을 때, 캐시 히트 시 해당 문장으로 **즉시 응답** (RAG/LLM 호출 없음).
- **캐시 적재**: 지식 베이스에서 `greeting_phase1` / `greeting_phase2` / `farewell` 로 입력하면 `immediate_cache_for_knowledge()` 로 **qa_cache에 반영**됨.

→ **사용자 인사/종료에 대한 AI 응답** 은 지식 베이스 입력이 **반영된 상태로 동작**함.  
→ 다만 이건 **“통화 시작 시 AI가 말하는 Phase1/Phase2”** 와는 다른 경로이며, **tenant_config와는 무관**함.

---

## 3. 요약 표

| 항목 | 내용 |
|------|------|
| **지식 베이스 입력 저장처** | knowledge 컬렉션 + (greeting_phase1/2, farewell 시) qa_cache |
| **tenant_config 저장/갱신** | 지식 API에서 하지 않음. sip-pbx 내에 tenant_config 쓰기 코드 없음. |
| **Phase1/Phase2 (통화 시작 인사)** | org_manager(tenant_config) → `get_random_greeting_template()`, `load_capabilities()` |
| **사용자 인사/종료에 대한 응답** | qa_cache 검색 (지식 베이스 입력 반영됨) |

---

## 4. 권장 사항

1. **의도 확인**  
   - “지식 베이스에 인사말/설정 입력 → tenant_config에도 반영”이 **요구사항**인지,  
   - 아니면 “tenant_config는 별도 시드/관리, 지식 베이스는 knowledge/qa_cache만”이 맞는지 결정.

2. **반영이 필요할 경우**  
   - **(A)** 지식 베이스에서 greeting/capability 계열 입력 시, **동일 owner에 대해 tenant_config 문서를 생성/갱신**하는 로직을 백엔드에 추가 (tenant_config 저장소가 sip-pbx에 정의되는 경우).  
   - **(B)** 또는 org_manager가 **같은 owner의 knowledge/qa_cache**(greeting_phase1/2, farewell 등)를 Phase1/Phase2 소스로도 읽도록 변경해, “지식 베이스 입력 = 테넌트 인사말/설정 반영”으로 동작하게 함.

3. **현재 상태**  
   - 지식 베이스 입력은 **qa_cache** 를 통해 “사용자 인사/종료에 대한 응답”에는 이미 반영되어 있음.  
   - “통화 연결 직후 AI가 말하는 첫 인사(Phase1/Phase2)”만 tenant_config 경로이며, 여기에 지식 베이스가 반영되도록 하려면 위 (A) 또는 (B) 중 하나의 설계·구현이 필요함.
