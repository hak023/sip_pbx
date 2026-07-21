# 셀프서비스 AI 도우미 BMAD QA — 자동 테스트 진입점 구축 (1단계)

**작성일**: 2026-07-15
**단계**: 1/4 — 테스트 모드 진입점 구현 (2단계 항목서 작성·3단계 실행·4단계 리포팅은 후속)
**관련 문서**: [self-service-ai-assistant-architecture.md](../../architecture/self-service-ai-assistant-architecture.md), [2026-07-15_self_service_epic1_po_qa_review.md](2026-07-15_self_service_epic1_po_qa_review.md)

## 1. 목표

수동 통합 테스트 대신, **실제 STT 출력 직후 ~ TTS 변환 직전** 구간을 그대로 재현하는 자동화된 QA 테스트 진입점을 구축한다. 자연어 입력 → RAG 검색·온보딩 체크리스트·Tool-calling(실제 LLM function-calling 포함) → 응답 텍스트까지, 모의 객체 없이 실제 파이프라인 코드를 그대로 실행한다.

## 2. 진입점 설계 근거

실제 코드 조사 결과, 음성(`rag_processor.py`)과 문자(`sip_message_ai_reply.py`) 두 채널이 **공통으로 거치는 유일한 지점**이 `ConversationAgent.process_utterance(user_text, call_id, **kwargs)`임을 확인했다(`src/ai_voicebot/langgraph/agent.py`). 이 함수는:
- **입력**: STT 결과 텍스트(`user_text`) — 정확히 "STT 로직 이후"
- **출력**: `response`/`response_chunks` — 이후 TTS로 전달되는 것과 동일한 텍스트, "TTS 가기 전"

이므로 이 함수를 직접 호출하는 것이 요청하신 정확한 진입점이다.

### 발견한 프로세스 구조 (진입점 재사용을 위해 확인 필요했던 사실)

- `src/api/main.py`(FastAPI)는 별도 프로세스가 아니라 **`src/main.py`(SIP 서버) 프로세스 안에 uvicorn으로 임베드되어 같은 asyncio 이벤트 루프에서 실행됨**을 확인했다(`python -m src.main` 단일 프로세스). 따라서 API 라우터에서도 `factory.py`의 전역 싱글턴(LLM Client 등)에 접근 가능하다.
- 다만 RAG 엔진·임베더·vector_db·org_manager를 담고 있는 `AIOrchestrator` 인스턴스는 기존에 전역 접근자가 없었다(`sip_message_ai_reply.py`는 `sip_endpoint.call_manager.ai_orchestrator` 경유로만 접근 — API 라우터에서는 닿지 않음). → `factory.py`에 `get_ai_orchestrator()` 전역 접근자를 신규 추가(기존 `get_llm_client()`와 동일 패턴)해 해결했다.

## 3. 구현 내용

### 3.1 `src/ai_voicebot/factory.py` (수정)

- `_global_ai_orchestrator` 전역 변수 + `get_ai_orchestrator()` 추가
- `create_ai_orchestrator()`가 orchestrator 생성 직후 이 전역에 저장(기존 `_global_llm_client` 저장 패턴과 동일 위치·방식)

### 3.2 `src/api/routers/self_service_test.py` (신규)

- `POST /api/self-service/test/converse`: 자연어 텍스트 입력 → 실제 `ConversationAgent.process_utterance()` 호출 → 응답·intent·business_state·confidence와 **Tool 호출 트레이스**(`tool_trace`)를 반환
  - `tool_trace`는 기존 `src/api/utils/call_data_record_reader.py::read_call_data_record_for_call()`(이미 존재하는 함수, 새로 안 만듦)로 해당 `call_id`의 `call_data_record_*.log`를 읽어 `category=self_service` 이벤트만 추출 — RAG 검색·온보딩 체크리스트·Tool 호출 시작/완료·자동설정 적용/거부 이벤트가 모두 포함된다.
  - `owner`+`caller_number`(또는 `session_id`) 조합별로 `ConversationAgent` 인스턴스를 캐싱해 **멀티턴 시나리오**(확인 발화 → 긍정 응답 등)를 그대로 테스트 가능(`sip_message_ai_reply.py`의 `_agent_cache` 패턴 재사용).
- `POST /api/self-service/test/reset`: 캐시된 세션(대화 맥락) 폐기 — 테스트 케이스 간 격리용
- `GET /api/self-service/test/status`: 테스트 모드 활성화 여부·AI 시스템 준비 상태 조회(가드 없이 확인 가능)

### 3.3 보안 게이트

- `SELF_SERVICE_QA_TEST_MODE` 환경변수가 명시적으로 `1`/`true`/`yes`/`on`일 때만 `/converse`·`/reset`이 동작(기본 비활성화 — 운영 환경에서 실수로 열려 있는 것을 방지, `/status`는 가드 없이 조회만 허용).
- `env.example`에 문서화 추가.
- **주의**: 이 엔드포인트는 실제 자동설정 Tool을 실행하므로 실제 값 변경이 일어난다. QA 전용 owner/테넌트로 테스트할 것을 권장(리포트 4절 참고).

## 4. 검증 결과

```
python -m pytest tests_new/unit/test_ai_voicebot/test_self_service_qa_test_endpoint.py -v --no-cov
→ 22 passed (게이트 on/off, 세션 캐시 재사용, tool_trace 필터링, 503/403 처리 등)

python -m pytest tests_new/unit/test_ai_voicebot tests_new/unit/test_events -q --no-cov
→ 191 passed (누적 169 + 신규 22), 회귀 없음
```

단위 테스트는 실제 LLM 호출 없이 배선(라우팅·게이트·캐시·트레이스 필터링)만 검증했다 — 실제 Gemini 응답을 포함한 검증은 서버 재시작 후 2~3단계에서 수행한다.

## 5. ⚠️ 다음 단계를 위해 반드시 필요한 조치 — 서버 재시작

**이미 실행 중인 서버는 새로 추가된 라우터 코드를 알지 못합니다**(Python은 실행 중 프로세스에 새 모듈을 자동 반영하지 않음). 회사 규칙(`copilot-instructions.md` — "포트 충돌 프로세스 자동 실행 금지")에 따라 SIP/API 서버 재시작은 제가 임의로 수행하지 않았습니다. 아래 절차로 직접 재시작해 주세요:

1. 환경변수 설정: `.env`(또는 실행 셸)에 `SELF_SERVICE_QA_TEST_MODE=1` 추가
2. 서버 재시작: 기존 실행 중인 `python -m src.main` 프로세스 종료 후 재기동(`start-all.ps1` 또는 동일 명령 재사용)
3. 재시작 후 `GET /api/self-service/test/status`로 `test_mode_enabled: true`, `llm_ready: true`, `orchestrator_ready: true` 확인

## 6. 다음 단계 (계획)

- **2단계**: BMAD QA 관점의 테스트 항목서(케이스 목록) 작성 — Story 1.1~1.9의 AC/IV를 자연어 입력 시나리오로 매핑
- **3단계**: 서버 재시작 확인 후 `/api/self-service/test/converse` 호출로 각 케이스 실행
- **4단계**: 결과를 리포트로 정리(성공/실패, 실제 Tool 호출 트레이스, 발견 이슈)

---
*최종 업데이트: 2026-07-15*
