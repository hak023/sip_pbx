# 세션 인계 리포트 — 음성 지연 개선(Epic 3~5) 진행 상황 + 🔴 근본 원인 확정, 다음 세션 착수 가이드

**작성일**: 2026-07-24
**목적**: 이번 세션 작업 전체 요약 + 다음 세션이 바로 이어서 진행할 수 있도록 결정 필요 사항과
착수 지점을 명시.
**관련 문서(순서대로 읽을 것)**:
1. [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md) — PRD(Epic 3~5)
2. [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md) — 아키텍처(🔴 최우선 확인 배너 포함)
3. [2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md](2026-07-24_root_cause_gemini_thinking_not_actually_disabled.md) — **가장 중요한 발견**
4. [2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md](2026-07-24_ai_pipeline_qa_endpoint_and_latency_findings.md) — 실측 데이터
5. [2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md](2026-07-24_voice_latency_epic3_story_3.1_3.2_3.4_implementation.md)
6. [2026-07-24_voice_latency_epic4_5_story_4.1_5.1_design_decisions.md](2026-07-24_voice_latency_epic4_5_story_4.1_5.1_design_decisions.md)

---

## 1. 이번 세션 완료 사항 요약

| Story                             | 상태 | 핵심 내용                                                                                                                                                                                                            |
| --------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1(지연 계측)                    | Done | `ai_response_latency_compare.py`가 이미 실전 배선되어 있었음을 확인(초기 조사 누락 정정)                                                                                                                             |
| 3.2(5초 SLA 원인 태깅)            | Done | `compute_sla_stage_breakdown_ms()`/`suspected_sla_stage()`/`check_and_tag_sla_exceeded()` 신규 구현 + 단위테스트 10건                                                                                                |
| 3.4(streaming_tts_processor 감사) | Done | 죽은 코드로 확정(파이프라인 미연결)                                                                                                                                                                                  |
| 4.1(TTFT 설계 결정)               | Done | 대안 B 채택, 안전 서브셋을 `{chitchat, out_of_scope}`로 좁힘(`greeting`은 이미 즉시 응답이라 제외)                                                                                                                   |
| 5.1(턴테이킹 실사용 감사)         | Done | `SmartTurnProcessor`/`SmartBargeInStrategy` 둘 다 죽은 코드로 확정. 실제 턴테이킹은 legacy WebRTC VAD + `MinWordsUserTurnStartStrategy` + `rag_processor.py`의 Supersede/Coalesce 메커니즘(FR7 이미 충족)만으로 동작 |

**신규 산출물**:
- `src/api/routers/ai_pipeline_test.py` — `/api/ai-pipeline/test/converse`(`AI_PIPELINE_QA_TEST_MODE` 게이트). 실서버 통화 없이 STT 직후~TTS 직전을 텍스트로 재현하는 QA 하네스(`self_service_test.py`와 동일 패턴). 단위 테스트 18건.
- `src/common/ai_response_latency_compare.py`에 SLA 태깅 함수 3개 추가.

---

## 2. 🔴 이번 세션 최대 발견 — 다음 세션 최우선 확인 필요

**신규 QA 하네스로 chitchat 응답을 실측한 결과 6.8~9.75초 지연이 재현됐고, 원인을 추적한 결과
`LLMClient`의 Gemini "thinking"(내부 추론) 비활성화 코드가 실제로는 단 한 번도 동작한 적이 없었다.**

- 설치된 SDK(`google-generativeai==0.8.6`, **이미 공식 deprecated**)에는 `ThinkingConfig` 자체가
  없음(`AttributeError`) — `except (AttributeError, TypeError): pass`가 이 실패를 완전히 침묵시킴.
- protobuf 레벨까지 확인해도 thinking 관련 필드가 전혀 없음 — 이 SDK로는 원천적으로 thinking을
  끌 방법이 없다.
- 대안으로 시도한 모델 교체(`gemini-2.0-flash`, `gemini-2.5-flash-lite`)는 각각 **404 폐지 /
  404 신규사용자 제한**으로 이 계정에서 사용 불가 — **모델 교체로는 검증도 회피도 불가능함을
  확인**.
- **유일한 해결 경로: `google-generativeai` → `google-genai` SDK 마이그레이션**(Google 공식 권고,
  이미 `google-genai==1.75.0`이 venv에 설치되어 있어 추가 설치 불필요). `types.ThinkingConfig(thinking_budget=0)`을
  정식 지원한다.
- **영향 범위**: `LLMClient`(`generate_response_streaming`/`generate_simple`/`format_for_customer`
  등)를 쓰는 **모든 경로** — chitchat뿐 아니라 `classify_intent_node`의 3차 LLM 분류, self-service
  Tool-calling, booking_agent 등 전부 영향받을 가능성. 2026-03-30 리포트의 "평균 8.69초"도 동일
  원인일 가능성이 매우 높음.

**다음 세션 시작 시 사용자에게 확인할 것**: 지난 세션 끝에 제시한 3가지 옵션 중 하나 선택
1. SDK 마이그레이션을 위한 별도 PRD/Story부터 계획(BMAD 절차)
2. `llm_client.py`만 좁게 스파이크 구현해 `thinking_budget=0`이 실제로 지연을 줄이는지 프로덕션
   반영 전에 빠르게 검증
3. (이번 세션에서 선택됨 — 아래 "다음 세션 착수 지점" 참고)

---

## 3. 다음 세션 착수 지점 (바로 시작 가능하도록)

1. **`llm_client.py` 스파이크 검증부터 시작 권장**(옵션 2) — 리스크가 가장 낮고 가설을 가장
   빠르게 확정할 수 있다. `google-genai`(이미 설치됨, v1.75.0)로 `LLMClient.generate_response_streaming`과
   동일한 프롬프트를 독립 스크립트로 호출해 `thinking_budget=0` 적용 시 TTFT가 실제로 6~9초에서
   수백 ms로 줄어드는지 먼저 확인한다(API 키는 `GEMINI_API_KEY`/`GOOGLE_API_KEY` 환경변수 —
   사용자의 서버 실행 터미널에만 설정되어 있어 이번 세션에서 직접 접근하지 못했음, 다음 세션에서
   해당 터미널 컨텍스트를 이어받거나 사용자에게 값을 직접 셸에 설정해 달라고 요청할 것 — 절대
   채팅으로 값을 요청하지 말 것).
2. 스파이크로 가설이 확정되면, `google-genai` 마이그레이션 범위를 정하기 위해 `LLMClient`의
   전체 공개 메서드 목록과 `booking_gemini_fc.py`(Gemini 네이티브 function calling, 별도 SDK
   객체 사용) 등 연동 지점을 전수 조사해야 한다 — **Tool-calling 경로가 있으므로 단순 치환이
   아니라 별도 설계가 필요**(`.github/copilot-instructions.md`의 LLM Tool-calling 3단계 폴백
   구조 원칙 참고).
3. 마이그레이션은 시스템 전반에 영향을 주는 큰 변경이므로, 스파이크 검증 후에는 정식으로
   Brief/PRD/Story를 작성(BMAD 절차, `sip-pbx-bmad-harness.instructions.md` 따름)한 뒤 착수한다.

## 4. 별건 — 서버 재기동 지연 이슈(진행 중, 효과 미확인)

`TextEmbedder` 초기화가 매 재시작마다 170~183초(평소 ~5.5초) 걸리는 현상 발견 — Windows Defender
실시간 검사가 원인으로 추정됨. 사용자가 `Add-MpPreference -ExclusionPath`로 `sip-pbx\venv`,
`~/.cache/huggingface`, `sip-pbx\data`를 제외 목록에 추가 완료. **다음 세션 재시작 시 이 구간이
실제로 빨라졌는지 반드시 확인**(로그의 `Initializing Embedder...`→`Embedder initialized` 구간
타임스탬프 비교).

## 5. 현재 코드/설정 상태 (다음 세션 시작 시 확인용)

- `config/config.yaml`의 `gemini.model`은 **`gemini-2.5-flash`로 원복 완료**(임시 테스트용
  `gemini-2.0-flash`/`gemini-2.5-flash-lite` 시도 후 정상 원복).
- `src/api/routers/ai_pipeline_test.py`, 관련 단위 테스트, `main.py` 라우터 등록, `env.example`
  안내는 그대로 유지(프로덕션에 영향 없음, `AI_PIPELINE_QA_TEST_MODE` 기본 비활성화).
- 서버가 현재 실행 중이라면 `config.yaml` 원복이 아직 반영 안 됐을 수 있음(재시작 전까지는
  이전 세션에서 테스트한 모델이 메모리에 남아있을 수 있음) — 필요 시 재확인.

*최종 업데이트: 2026-07-24*
