# Project Brief: 음성 AI 응답 지연 개선 및 스마트 턴테이킹 (Voice Latency & Smart Turn-Taking)

**작성일**: 2026-07-24
**버전**: 0.1 (초안)
**상태**: 초안 (Draft) — PRD 작성 전 단계
**관련 문서**:
- [prd.md](prd.md) — 마스터 PRD (NFR3 미디어 지연 <5ms, STT<500ms, 평균 응답 <2초 조항 보유)
- [../architecture/voice-ai-conversation-engine.md](../architecture/voice-ai-conversation-engine.md) — VAD/STT/LLM/TTS 파이프라인 설계(예상치 vs 실측 괴리 확인 필요)
- [../design/TTS_RTP_STRUCTURE_REVIEW.md](../design/TTS_RTP_STRUCTURE_REVIEW.md), [../design/TTS_RTP_AND_STT_QUEUE_DESIGN.md](../design/TTS_RTP_AND_STT_QUEUE_DESIGN.md) — TTS→RTP 큐/패킹 구조
- [../VOICE_AI_TURN_TAKING_REFERENCES.md](../VOICE_AI_TURN_TAKING_REFERENCES.md) — Smart Turn v3.2 등 외부 레퍼런스
- [../analysis/ai-response-time-analysis.md](../analysis/ai-response-time-analysis.md) — 이론적 지연 추정(0.88~2.4초)
- [../reports/2026-03/2026-03-30_1440_AI_RESPONSE_TIME_ANALYSIS_AND_OPTIMIZATION_DESIGN.md](../reports/2026-03/2026-03-30_1440_AI_RESPONSE_TIME_ANALYSIS_AND_OPTIMIZATION_DESIGN.md) — 실측 평균 8.69초(허용 불가) 분석
- [../../src/ai_voicebot/pipecat/processors/rag_processor.py](../../src/ai_voicebot/pipecat/processors/rag_processor.py) — 현재 LLM→TTS 연결부(실측 병목 지점)

> **생성 방식 안내**: 사용자 요청("AI 응대가 너무 늦다, 5초 SLA, TTFT 도입, 스마트 턴테이킹 재검토")에 따라
> 코드베이스 직접 조사(grep/read) 결과를 근거로 작성한 완성 초안(YOLO 모드)이다. 대화형 elicitation 없이
> 일괄 작성했으므로 각 섹션의 가정은 팀 검토 후 확정한다.

---

## Executive Summary

**핵심 문제**: 설계 문서(`voice-ai-conversation-engine.md`)는 평균 응답 지연을 1.3초로 추정하지만, 실제
운영 리포트(`2026-03-30_1440_...md`)는 **평균 8.69초, 최악 16초**를 기록했다. 코드 조사 결과 **원인은
설계 결함이 아니라 "스트리밍처럼 보이지만 실제로는 배치인" 구현**에 있다: `generate_response_node`가
LLM 스트리밍 제너레이터(`generate_response_streaming`)를 문장 단위로 **전부 소진해 리스트로 모은 뒤**
반환하고, `rag_processor.py`는 이 리스트가 준비된 **이후에야** TTS로 문장을 밀어넣는다(코드 내부
변수명 `_tts_mode_planned = "chunked_after_llm_complete"`가 이 사실을 스스로 증언한다). 즉 **TTFT(Time
To First Token→TTS)가 사실상 "LLM 전체 완료 시간"과 같다.**

**목표**: (1) 사용자 발화 종료 후 AI 응답 시작(TTS 첫 오디오 송출)까지 **5초 이내 하드 리밋** 확보,
초과 시 원인 판별 로직 도입. (2) 진짜 TTFT 구조로 전환 — 첫 문장이 완성되는 즉시 TTS로 전달. (3)
스마트 턴테이킹을 리서치 기반으로 재정비 — 잡음/짧은 발화 무시, LLM 사고 중 추가 발화 누적·재판단,
"유의미한 발화" 판정 기준 명문화.

**핵심 가치 제안**: "전화 상대가 사람과 대화하는 것처럼 AI가 즉각 반응하고, 말이 끊기거나 겹쳐도 자연스럽게
따라간다."

---

## Problem Statement

### 1) 응답 지연(5초 SLA)

- 실측 평균 8.69초(2026-03-30 리포트), 최악 16초. 병목 Top3: `generate_response`(LLM, RAG 컨텍스트 포함)
  4.6초, `step_back`(불필요 실행 80%) 2.19초, `check_cache`(콜드스타트) 1.62초 — 이는 **LLM 호출 자체가
  아니라 그 앞뒤의 orchestration 오버헤드**가 크다는 뜻이다.
- 현재 "5초 초과 시 무조건 실패"로 보지 않고, **초과 원인이 (a) 정상적 긴 RAG/LLM 처리인지 (b) 불필요한
  중복 호출/로직 결함인지 구분**할 진단 로직이 없다. HITL 폴백은 confidence 기준으로만 발동하고 latency
  기준 폴백은 없다.

### 2) TTFT 미도입(실제로는 배치 처리)

- `llm_client.generate_response_streaming()`은 Gemini로부터 스트리밍을 받아 문장 단위 `yield`를 지원하지만,
  `generate_response_node`(`src/ai_voicebot/langgraph/nodes/generate_response.py`)가 `_collect_streaming()`
  내부에서 `async for` 전체를 리스트로 소진한 뒤에야 함수가 반환된다.
- `rag_processor.py`(`_handle_langgraph_response` 계열, L1650~2100)는 이 반환값(`result`)이 도착한 **이후**
  `response_chunks`를 순회하며 `push_frame(TextFrame(...))`을 연속 호출한다 — 각 청크 사이에 실제 지연은
  없으므로 "체감 지연 감소"라는 주석과 달리 **최초 오디오까지의 시간(TTFT)은 개선되지 않는다.**
- `streaming_tts_processor.py`(진짜 TTFT용으로 설계된 게이트웨이 프로세서)가 저장소에 존재하지만
  `pipeline_builder.py`의 실제 파이프라인 조립에는 **연결되어 있지 않다**(죽은 코드 가능성 — 검증 필요).

### 3) 턴테이킹 로직의 불확실성

- `smart_turn_processor.py`가 Smart Turn 모델로 발화 완료를 판단하고(`max_hold_secs=2.0`), VAD
  `stop_secs=0.2`로 묵음을 감지하는 구조는 이미 존재한다.
- `barge_in_strategy.py`의 3단계 필터(키워드 즉시 판단 → 3단어 게이트 → LLM 판단)와 `accumulated_text`
  누적 로직도 이미 존재하여, "LLM 사고 중 추가 발화를 합산해 재판단"하는 요구사항의 **상당 부분은 이미
  구현되어 있을 가능성**이 있다 — 그러나 이것이 (a) 실제로 만족스럽게 동작하는지, (b) 사용자가 요청한
  "묵음 판단 + 발화 합산" 시나리오와 정확히 일치하는지는 **실서버 검증 데이터가 없어 확인되지 않았다.**
- "유의미한 발화"의 판정 기준(길이? 의미? 키워드?)이 코드 여러 곳(`MinWordsUserTurnStartStrategy(min_words=3)`,
  Smart Turn의 grammar/tone/pace 분석, barge-in의 3단어 게이트)에 **파편화**되어 있어 일관된 기준이 없다.

### 파급 효과

- 8초 이상의 응답 지연은 통화 중 침묵으로 체감되어 상대방이 전화를 끊거나 재질문("여보세요?")하게 만들고,
  이는 HITL 전환율과 통화 이탈률을 동시에 악화시킨다.

---

## Proposed Solution

### 핵심 개념

1. **진짜 TTFT 파이프라인**: `generate_response_node`가 전체 응답을 다 모을 때까지 반환을 지연하지 않고,
   **첫 문장이 완성되는 즉시** 하류(TTS)로 전달할 수 있는 구조로 전환한다. LangGraph 노드 반환 모델(단일
   dict 반환)과 Pipecat 프레임 기반 스트리밍(연속 push_frame) 사이의 경계를 어디에 둘지가 핵심 설계
   포인트이며, 기존 `streaming_tts_processor.py`를 재활용할지 `rag_processor.py`의 청크 전송 지점을
   "첫 청크 도착 즉시"로 당길지 결정이 필요하다(Architecture 문서에서 대안 비교).
2. **5초 SLA 가드레일**: 노드별 소요시간 로깅(이미 일부 존재, `agent_elapsed` 등)을 활용해 "발화 종료 →
   TTS 첫 오디오" 총 지연을 실시간 계측하고, 5초 초과 시 (a) 원인 태깅(cache/RAG/LLM/TTS 중 어디서
   초과했는지) (b) 짧은 대기 멘트("잠시만요" 류) 또는 즉시 HITL 폴백 중 정책 결정.
3. **스마트 턴테이킹 재정비**: 기존 Smart Turn/barge-in 로직을 유지하되, (a) "유의미한 발화" 판정 기준을
   리서치 기반으로 명문화하고 코드 전반에 흩어진 임계값을 한 곳(설정/문서)으로 정리, (b) LLM 사고 중
   추가 발화 발생 시 "이전 발화 처리 중단 + 합산 재판단"이 실제로 요구사항대로 동작하는지 실서버로
   검증, (c) 필요 시 임계값(`min_words`, `stop_secs`, `max_hold_secs`) 조정.

### 기존 시스템과의 정합성

Pipecat/Silero VAD/Smart Turn/Gemini/Google TTS 스택은 그대로 유지하며, **신규 인프라 도입 없이** 기존
프로세서 체인의 연결 방식과 LangGraph 노드의 반환 시점만 재설계하는 것을 원칙으로 한다(Brownfield
Enhancement, self-service-ai-assistant 트랙과 동일 원칙).

---

## Target Users

- **1차**: 전화·문자로 SmartPBX AI와 대화하는 모든 발신자(고객) — 체감 응답 속도가 개선 대상.
- **2차**: 테넌트 운영자 — HITL 전환율·통화 이탈률 감소로 간접 수혜.

## Goals & Success Metrics

| 목표                    | 측정 방법                                                             | 목표치                                                |
| ----------------------- | --------------------------------------------------------------------- | ----------------------------------------------------- |
| 응답 지연 SLA           | 발화 종료 → TTS 첫 오디오 송출 시각 차 (`call_data_record` 로그 기반) | P95 < 5초                                             |
| TTFT 실측 개선          | 첫 문장 TTS 전달 시각(신규 계측 포인트)                               | 평균 < 1.5초 (LLM 첫 문장 생성 시점과 근접)           |
| 5초 초과 시 원인 분류율 | 초과 케이스 중 원인 태그(cache/RAG/LLM/TTS)가 자동 기록된 비율        | 100% (수동 로그 분석 불필요)                          |
| 턴테이킹 오탐지율       | 잡음/짧은 발화로 불필요하게 turn이 넘어간 비율(실통화 샘플링)         | 리서치 기준값 확정 후 목표 설정(Epic 3 내 세부 Story) |

## MVP Scope

### In Scope
- `generate_response_node` + `rag_processor.py` LLM→TTS 연결부의 실제 TTFT화(첫 문장 즉시 전달).
- 발화 종료~TTS 첫 오디오 총 지연 실시간 계측 + 5초 초과 원인 태깅 로그/이벤트.
- 턴테이킹 관련 기존 로직(Smart Turn, barge-in, VAD 임계값) 실측 검증 및 "유의미한 발화" 판정 기준
  리서치·문서화.
- 위 조사 결과에 따른 임계값 조정(필요 시).

### Out of Scope (이번 트랙)
- STT/TTS 벤더 교체(Google STT/TTS 유지).
- LLM 모델 교체(Gemini 계열 유지).
- SIP/RTP 프로토콜 레벨 변경.
- 텍스트(SIP MESSAGE) 채널의 지연 개선(본 트랙은 음성 채널 우선, 문자는 실시간성 요구가 낮음).

## Technical Considerations

- **핵심 리스크**: LangGraph 노드는 "state dict 1회 반환" 모델이라 스트리밍과 근본적으로 상성이 안 맞는다.
  첫 문장만 먼저 반환하고 나머지를 백그라운드 태스크로 이어붙이는 방식은 `update_state`/체크포인터 저장
  시점과 충돌할 수 있어 Architecture 단계에서 대안을 구체적으로 비교해야 한다.
- **회귀 위험**: `rag_processor.py`의 LLM→TTS 연결부는 HITL/아웃바운드/템플릿 응답 등 다수 분기가 얽혀
  있는 매우 복잡한 함수(2000줄+)이므로, 변경 범위를 최소화하고 회귀 테스트를 촘촘히 설계해야 한다.
- **계측 우선**: 코드를 먼저 고치기보다, 정확한 "어디서 몇 초 걸리는지"를 실서버 로그로 재확인하는 것이
  선행되어야 한다(이미 존재하는 `agent_elapsed`, `llm_gen_elapsed_sec`, `llm_first_sentence_elapsed_sec`
  계측을 우선 활용).

## Next Steps

1. 본 브리프를 상위 문서로 PRD(`voice-latency-turn-taking-prd.md`) 작성 — Epic 3(TTFT 파이프라인),
   Epic 4(5초 SLA 가드레일), Epic 5(스마트 턴테이킹 재정비)로 분해(마스터 PRD/Epic 1·2는 self-service
   트랙이 이미 사용 중이므로 Epic 3부터 이어서 번호 부여).
2. Architecture 문서(`docs/architecture/voice-latency-turn-taking-architecture.md`) 작성 — TTFT 연결부
   설계 대안 비교, 계측 포인트, 턴테이킹 임계값 정리.
3. Story 파일 작성(Draft) 후 실서버 계측 데이터 확보 → 근본 원인 재검증 → 구현 착수.
