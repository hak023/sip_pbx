# 통화 분석: `Uf4C6cdpwY` (2026-03-21)

## 요약

| 항목 | 내용 |
|------|------|
| 발·착신 | 1003 → 1004 |
| 진행 | 10초 무응답 → AI 인수 → Pipecat 정상 기동 |
| 업무 이슈 | **오시는 길** 질문에서 **RAG 0건** → **confidence 0** → **HITL 요청** → 약 **15초 후** 타임아웃 폴백 메시지 |
| 터미널 경고 | `handle_hitl_timeout` coroutine was never awaited → **`hitl.py`에서 async 콜백을 `create_task`로 처리하도록 수정** |

## 타임라인 (call_data_record_20260321.log)

1. **03:21:01** `call_connected`, 인사 Phase1/2 TTS.
2. **03:21:19** STT `"안녕하세요."` → LLM 인사 응답 (의도 `greeting`).
3. **03:21:42** `"어떤 걸 할 수 있나요?"` → `help` 응답.
4. **03:21:56** `"찾아가려면 어떻게 가야 되나요? 기상청이요?"`  
   - `semantic_cache_miss` → **`rag_search_done` result_count: 0**, owner `1004`.  
   - LLM이 일반 답변(웹사이트 안내) 생성, **confidence 0.0**.  
   - **`hitl_requested`**: `답변 신뢰도가 매우 낮습니다 (confidence=0.00). 적절한 정보를 찾지 못했습니다.`
5. **03:22:15** 동일 질문에 대해 `llm_exchange`가 **두 번** 기록됨 (에이전트/로깅 중복 가능성 — 별도 점검 여지).
6. **03:22:30** `hitl_timeout` → `needs_llm_refinement: true`, 지연 안내 문구.
7. **03:22:32** `hitl_response_received` (타임아웃 관련 처리).
8. 이후 STT·LLM·TTS로 대화 지속, **03:23:19** `call_ended`.

## 이슈 정리

### 1. RAG/지식 (설계·데이터)

- 질문 유형: **방문·오시는 길** → Chroma에 해당 **owner(1004) 문서가 없거나 검색이 0건**이면 confidence가 낮아질 수 있음.
- **대응**: `오시는 길`, `찾아오시는`, `위치` 등 **FAQ/지식 문서 추가**, 또는 RAG 임계·폴백 문구 조정.

### 2. HITL 동작

- 낮은 신뢰도로 HITL이 뜬 뒤, 운영자 즉시 응답이 없으면 **타임아웃 폴백**이 큐에 들어가 사용자에게 안내됨 (로그상 정상 시퀀스).

### 3. 터미널 `RuntimeWarning` (코드 수정 완료)

- **원인**: `register_on_hitl_timeout`에 등록된 콜백이 **async**인데, `HITLService` 내부에서 **동기 호출**만 해 coroutine이 await되지 않음.
- **조치**: `src/services/hitl.py`에서 콜백 반환값이 coroutine이면 **`asyncio.create_task(...)`** 로 실행.

### 4. Chroma 로그 (터미널 829–830행)

- `Number of requested results ... greater than number of elements in index 5`  
  → 컬렉션에 **문서가 5건뿐**이라 요청한 top-k가 줄어든 것. **정상 동작에 가까운 정보성 메시지**이나, 지식 베이스 확충 시 완화됨.

## 관련 파일

- `logs/call_data_record_20260321.log` — 본 통화 이벤트 전체
- `src/services/hitl.py` — 타임아웃 콜백 async 처리
