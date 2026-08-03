# 음성 AI 응답 지연 개선 및 스마트 턴테이킹 — Brownfield Enhancement PRD

**작성일**: 2026-07-24
**버전**: 0.1 (초안 — Epic/Story 확정 전)
**상태**: 초안
**관련 문서**:
- [voice-latency-turn-taking-brief.md](voice-latency-turn-taking-brief.md) — 본 PRD의 상위 Project Brief
- [prd.md](prd.md) — 마스터 PRD(NFR3 미디어 지연, STT<500ms, 평균 응답<2초 조항)
- [../architecture/voice-ai-conversation-engine.md](../architecture/voice-ai-conversation-engine.md)
- [../architecture/voice-latency-turn-taking-architecture.md](../architecture/voice-latency-turn-taking-architecture.md) — 본 PRD의 기술 설계(작성 예정/병행)
- [../../src/ai_voicebot/langgraph/nodes/generate_response.py](../../src/ai_voicebot/langgraph/nodes/generate_response.py)
- [../../src/ai_voicebot/pipecat/processors/rag_processor.py](../../src/ai_voicebot/pipecat/processors/rag_processor.py)
- [../../src/ai_voicebot/pipecat/processors/smart_turn_processor.py](../../src/ai_voicebot/pipecat/processors/smart_turn_processor.py)
- [../../src/ai_voicebot/pipecat/barge_in_strategy.py](../../src/ai_voicebot/pipecat/barge_in_strategy.py)

> **범위 안내**: 본 PRD는 사용자 요청(응답 지연 5초 SLA, TTFT 도입, 스마트 턴테이킹 재검토)에 대해
> 코드 직접 조사를 근거로 작성한 완성 초안(YOLO 모드)이다. Epic 3부터 번호를 부여한다 —
> `self-service-ai-assistant-prd.md`가 Epic 1·2를 이미 사용 중이므로 동일 `docs/stories/` 폴더 내
> 파일명 충돌을 피하기 위함이다.

---

## Intro: Project Analysis and Context

### Analysis Source

IDE 기반 코드베이스 직접 조사(grep/read, document-project task 미실행) + 기존 리포트
(`docs/reports/2026-03/2026-03-30_1440_AI_RESPONSE_TIME_ANALYSIS_AND_OPTIMIZATION_DESIGN.md`,
`2026-03-28_2345_RESPONSE_TIME_OPTIMIZATION_ANALYSIS.md`) 재해석.

### Current Project State

SmartPBX AI 음성 파이프라인은 Pipecat 프레임워크 위에 Silero VAD → Google STT → LangGraph
Agent(RAGLLMProcessor) → Google TTS → RTP 순으로 구성된다. 설계 문서상 평균 응답 지연은 1.3초로
추정되어 있으나, 실측 리포트는 평균 8.69초를 기록했다. 원인 조사 결과 **LLM 스트리밍 응답이
`generate_response_node`에서 전부 소진된 뒤에야 반환되고, TTS 전달도 그 이후에 이루어지는 사실상의
배치 처리 구조**임이 확인되었다(브리프 §Problem Statement 참고). 턴테이킹(Smart Turn, barge-in)은
이미 상당 부분 구현되어 있으나 임계값의 근거와 실제 동작 검증이 부족하다.

### Available Documentation Analysis

| 문서                                      | 상태                                                                           |
| ----------------------------------------- | ------------------------------------------------------------------------------ |
| 음성 파이프라인 아키텍처                  | ✅ (`voice-ai-conversation-engine.md`, 단 실측치와 괴리)                        |
| TTS→RTP 구조                              | ✅ (`TTS_RTP_STRUCTURE_REVIEW.md`, `TTS_RTP_AND_STT_QUEUE_DESIGN.md`)           |
| 응답 지연 실측 분석                       | ✅ (2026-03 리포트 다수, 단 단발성 분석 — 회귀 추적 체계 없음)                  |
| 턴테이킹 외부 레퍼런스                    | ✅ (`VOICE_AI_TURN_TAKING_REFERENCES.md`)                                       |
| 턴테이킹 내부 설계 근거(임계값 산정 이유) | ❌ 없음 — 코드 내 매직 넘버(`min_words=3`, `stop_secs=0.2` 등)의 근거 문서 부재 |
| "유의미한 발화" 판정 기준 정의            | ❌ 없음                                                                         |

### Enhancement Type

☑ Performance/Latency Improvement
☑ Existing Feature Reliability Hardening (턴테이킹)
☐ New Feature Addition (신규 사용자 기능 아님 — 내부 파이프라인 개선)

### Enhancement Description

발화 종료 후 AI 응답(TTS 첫 오디오)까지의 지연을 5초 이내로 보장하고, 원인 미상의 초과를 자동
판별하는 가드레일을 추가한다. LLM 응답을 첫 문장 단위로 즉시 TTS에 전달하는 진짜 TTFT 구조로
전환한다. 턴테이킹 임계값과 "유의미한 발화" 판정 기준을 리서치 기반으로 재정비한다.

### Goals

1. 발화 종료 → TTS 첫 오디오 지연 P95 < 5초, 평균 < 2초(마스터 PRD NFR과 정합).
2. TTFT 구조 도입으로 첫 문장 전달 지연을 LLM 첫 문장 생성 시간에 근접시킴(현재 "전체 응답 완료
   시간"과 동일한 상태에서 개선).
3. 5초 초과 시 원인(cache/RAG/LLM/TTS/RTP 큐 중 어디)이 로그·이벤트로 자동 태깅되어 사후 분석 없이도
   즉시 원인 파악 가능.
4. 턴테이킹 임계값의 근거를 리서치로 확정하고 문서화, 필요 시 조정.

### Background Context

Self-service AI 도우미 트랙(Epic 1·2)이 기능 확장에 집중했다면, 본 트랙은 **이미 존재하는 음성
파이프라인의 신뢰성·응답 속도**를 개선하는 트랙이다. 통화라는 채널 특성상 8초 이상의 침묵은
사용자가 전화가 끊긴 것으로 오인하거나 재질문("여보세요?")하게 만들어 HITL 전환율과 이탈률을
동시에 악화시킨다.

### Change Log

| Date                                                                           | Version                           | Description                                                                  | Author                            |
| ------------------------------------------------------------------------------ | --------------------------------- | ---------------------------------------------------------------------------- | --------------------------------- |
| 2026-07-24                                                                     | 0.1                               | 초안 작성(Epic 3·4·5, FR1-FR12, NFR1-NFR6)                                   | GitHub Copilot (사용자 요청 기반) |
| 2026-07-29                                                                     | 0.2                               | Epic 7(지능형 발화 종료 판단 고도화) 신설 — pipecat 기본값 Smart Turn v3.2가 |
| 암묵적으로 적용 중임을 코드 재확인으로 발견, FR13-16/NFR7-8/Story 7.1~7.4 추가 | GitHub Copilot (사용자 요청 기반) |

---

## Requirements

### Functional Requirements

- **FR1**: 발화 종료(VAD/Smart Turn이 turn complete 판정) 시점부터 TTS 첫 오디오 프레임이 RTP 큐에
  들어가는 시점까지의 지연을 밀리초 단위로 계측하고 `call_data_record` 로그에 기록한다.
- **FR2**: 위 지연이 5초를 초과하면, 초과 시점의 파이프라인 단계(캐시 조회/RAG 검색/LLM 생성/TTS
  합성/RTP 큐잉 중 어디인지)를 자동 판별해 별도 로그 이벤트(`response_latency_sla_exceeded`)로
  기록한다. 원인 판별이 모호한 경우 "unknown"으로 태깅하되, 최소 1개 이상의 단계별 소요시간을
  함께 남긴다.
- **FR3**: LLM이 첫 문장을 완성하는 즉시(전체 응답 완료를 기다리지 않고) TTS 합성이 시작되도록
  LLM→TTS 연결부를 변경한다. 이때 이후 문장이 이어서 도착하면 순서를 보장하며 스트리밍한다.
- **FR4**: 첫 문장 TTFT 전달 방식으로 변경하더라도, HITL 개입/아웃바운드 모드/템플릿 응답/폴백
  응답 등 기존 `rag_processor.py`의 분기별 동작(우선순위, override 로직)은 그대로 유지한다(회귀
  방지, Brownfield 원칙).
- **FR5**: 5초 초과가 반복되는 경우를 위한 정책(예: 짧은 대기 멘트 삽입 또는 HITL 폴백 트리거
  여부)을 결정하고, 결정된 정책을 코드로 반영한다(정책 자체는 Story 3.x에서 데이터 기반으로 확정).
- **FR6**: "유의미한 발화" 판정 기준(길이/의미/키워드 조합)을 리서치 결과에 따라 명문화하고, 코드
  전반에 흩어진 임계값(`MinWordsUserTurnStartStrategy.min_words`, VAD `stop_secs`, Smart Turn
  `max_hold_secs`, barge-in 3단어 게이트 등)을 이 기준에 맞춰 재검토·정렬한다.
- **FR7**: LLM 사고(생성) 중 사용자가 추가 발화를 하면, 진행 중인 이전 처리를 중단하고 두 발화를
  합산한 텍스트로 재판단하는 기존 로직(`barge_in_strategy.py`의 `accumulated_text` 누적, 
  `rag_processor.py`의 supersede/cancel 체크포인트)이 실제로 요구사항대로 동작하는지 실서버로
  검증하고, 괴리가 있으면 수정한다.
- **FR8**: 짧은 발화("네", "어", 잡음성 발화 등)로 불필요하게 턴이 넘어가 응답이 트리거되지 않도록
  하는 기존 필터(barge-in 3단어 게이트, Smart Turn 최소 길이 0.1초)가 실제 통화 샘플에서 오탐/누락
  없이 동작하는지 검증한다.
- **FR9**: 파이프라인 각 단계(캐시/RAG/LLM 첫 문장/LLM 전체/TTS 첫 청크/RTP 첫 패킷)의 소요시간을
  구조화 로그로 일관되게 남겨, 이후 회귀(regression) 여부를 리포트 없이도 로그 집계로 판단할 수
  있게 한다.
- **FR10**: `streaming_tts_processor.py`(현재 파이프라인에 미연결된 것으로 보이는 TTFT 게이트웨이)의
  실제 사용 여부를 확인하고, 죽은 코드라면 제거하거나 재사용 여부를 결정한다(추측 금지 — 코드
  검증 후 결정).
- **FR11**: 5초 SLA 계측·원인 태깅 결과를 운영 대시보드(또는 최소한 구조화 로그 조회)에서 확인할
  수 있게 한다(신규 대시보드 UI는 Out of Scope, 로그 기반 조회로 충분).
- **FR12**: 턴테이킹 임계값 변경 시 A/B 또는 베이스라인 대비 비교 검증 절차를 따른다(self-service
  트랙의 Story 2.6 IntelliDecision 힌트 제거 사례처럼 "베이스라인 확보 → 변경 → 재검증 → 저하 시
  롤백" 원칙 적용).
- **FR13 (현재 Smart Turn stop 전략 관측가능화, 2026-07-29 범위 추가, Epic 7)**: `pipeline_builder.py`가
  암묵적으로 적용 중인 `TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())`의 판단 결과(발화
  완료/미완료 판정, 판정 근거 점수, 판단까지 소요시간)을 `call_data_record` 로그로 관측 가능하게
  만든다(판단 로직 자체는 변경하지 않는다).
- **FR14 (일시 정지 대응 보강)**: FR13 관측 결과 미완 발화(필러, 생각하는 침묵)에서 모델이
  오판(단오 종료로 오인)하는 사례가 확인되면, Story 7.2에서 튜닝(파라미터 조정) 또는
  보조 판단 레이어(대화맥락 기반 LLM 판단, 또는 Vogent Turn식 멀티모달 모델) 중 하나를
  선택해 설계한다(추측 금지 — 관측 데이터 기반으로만 결정).
- **FR15 (설정-동작 괴리 해소)**: `config.yaml`의 `smart_turn.*` 설정이 실제 모델 동작을 제어하도록
  연결하거나, 연결하지 않기로 결정했다면 해당 설정을 명시적으로 제거하거나 "미사용"으로
  문서화해 혼란을 방지한다.
- **FR16 (Feature flag 옥트인)**: Story 7.3의 모든 변경은 `config.yaml`의 신규 플래그로 기본
  비활성 상태를 유지하며(기존 암묵적 기본값 동작과 동일), 사용자 승인 + 실통화 A/B 검증
  후에만 활성화된다(NFR5).

### Non-Functional Requirements

- **NFR1**: 발화 종료 → TTS 첫 오디오 지연 P95 < 5초(하드 리밋), 평균 < 2초(마스터 PRD 정합).
- **NFR2**: 본 개선으로 인한 회귀 위험 최소화 — `rag_processor.py`(2000줄+)의 변경 범위를 LLM→TTS
  연결부로 한정하고, HITL/아웃바운드/템플릿 분기 로직은 리팩터링하지 않는다.
- **NFR3**: 계측 오버헤드는 응답 지연에 실질적 영향(< 5ms)을 주지 않아야 한다.
- **NFR4**: 신규 인프라(벤더, DB, 큐) 도입 없이 기존 Pipecat/Silero VAD/Smart Turn/Gemini/Google TTS
  스택 내에서 해결한다.
- **NFR5**: 턴테이킹 임계값 변경은 실제 통화 샘플 기반 검증 없이 배포하지 않는다(NFR1 지연 개선이
  턴테이킹 오탐지를 늘리는 트레이드오프를 만들지 않도록).
- **NFR6**: 기존 로깅 컨벤션(structlog, `call_data_record` 포맷)을 그대로 따른다.- **NFR7 (Epic 7, 2026-07-29)**: Smart Turn stop 전략 관련 변경은 기존 발화 종료 판정 정확도를
  저하시키지 않아야 한다(예: 튜닝이 지나치게 관대해져 정상 발화 종료도 계속 대기하는 문제가
  생기지 않아야 함).
- **NFR8 (Epic 7)**: 보조 LLM 판단 레이어를 추가할 경우, 추가 지연이 NFR1(평균 2초) 예산을 실질적으로
  손상하지 않아야 한다(Epic 4/6으로 확보한 개선분을 상쇄하지 않도록).
### Compatibility Requirements

- **CR1**: 기존 대화 그래프 토폴로지(LangGraph 노드/엣지)와 상태 스키마는 하위 호환을 유지한다
  (노드 반환 시그니처 변경 시 이를 소비하는 다른 코드/테스트에 영향 없도록 함 — self-service
  트랙에서 반복 확인된 함정과 동일 원칙).
- **CR2**: `booking_agent`/`self_service_agent` 등 다른 LangGraph 노드의 동작에는 영향을 주지 않는다.
- **CR3**: 문자(SIP MESSAGE) 채널의 기존 동작(비스트리밍)에는 영향을 주지 않는다(본 트랙은 음성
  채널 우선).

---

## Epic and Story Structure

### Epic Approach

**Epic 구조 결정**: 단일 Epic이 아니라 관심사 분리를 위해 3개 Epic으로 나눈다 — (1) 계측·SLA
가드레일이 선행되어야 TTFT 개선 효과를 측정할 수 있고, (2) TTFT 파이프라인 개선과 (3) 턴테이킹
재정비는 독립적으로 검증 가능한 영역이기 때문이다. `self-service-ai-assistant-prd.md`가 Epic 1·2를
사용 중이므로 **Epic 3부터 번호를 이어간다.**

---

## Epic 3 — 응답 지연 계측 및 5초 SLA 가드레일

**목표**: 정확한 실측 없이 최적화하지 않는다는 원칙에 따라, TTFT 구조 변경(Epic 4) 이전에 먼저
"어디서 몇 초 걸리는지"를 신뢰할 수 있는 로그로 확보한다.

- **Story 3.1 — 엔드투엔드 지연 계측 포인트 정의**: 발화 종료(VAD/Smart Turn 완료 시각) ~ TTS 첫
  오디오(RTP 큐 진입 시각) 구간을 단일 지표로 계측. 기존 `agent_elapsed`, `llm_gen_elapsed_sec`,
  `llm_first_sentence_elapsed_sec` 계측 재사용 + 누락 구간(RTP 큐잉까지) 보완.
- **Story 3.2 — 5초 초과 원인 자동 태깅**: FR2 구현. 단계별 소요시간 비교로 원인 후보 판별,
  `response_latency_sla_exceeded` 이벤트 신설.
- **Story 3.3 — 5초 초과 시 정책 결정 및 구현**: FR5. 데이터 확보 후(운영 로그 1~2주 또는 QA 샘플)
  대기 멘트/HITL 폴백 정책을 결정하고 반영.
- **Story 3.4 — `streaming_tts_processor.py` 사용 여부 확정**: FR10. 죽은 코드 확인 시 제거 또는
  Epic 4에서 재활용 여부 결정.

## Epic 4 — 진짜 TTFT 파이프라인 전환

**목표**: LLM 첫 문장 완성 즉시 TTS로 전달되는 구조로 전환(FR3, FR4).

- **Story 4.1 — LLM→TTS 연결부 설계 대안 비교**: `generate_response_node`가 첫 문장만 먼저 반환하고
  나머지를 백그라운드로 스트리밍하는 방식 vs `rag_processor.py`가 LangGraph 노드 완료를 기다리지
  않고 직접 스트리밍 제너레이터를 구독하는 방식 등 대안별 장단점·회귀 위험 분석(Architecture
  문서에서 상세화).
- **Story 4.2 — 선택안 구현(회귀 최소화)**: FR3, FR4. HITL/아웃바운드/템플릿 분기 무변경 원칙 준수.
- **Story 4.3 — TTFT 실측 검증**: Epic 3 계측 지표로 개선 전/후 비교(베이스라인 필수 확보 후 비교
  — self-service 트랙의 "표본 늘리기 전까지 결론 내리지 않는다" 교훈 적용).

## Epic 5 — 스마트 턴테이킹 재정비

**목표**: 기존 Smart Turn/barge-in 로직의 실제 동작 검증 및 "유의미한 발화" 기준 정립(FR6-FR9, FR12).

> **범위 재조정(Story 5.1 완료, 2026-07-24)**: 코드 전수 조사 결과 `smart_turn_processor.py`
> (grammar/tone/pace 기반 턴 완료 판단)와 `barge_in_strategy.py`(3단계 키워드/단어수/LLM 판단)는
> **파이프라인에 연결되지 않은 죽은 코드**로 확정되었다(`voice-latency-turn-taking-architecture.md`
> §1.4 근거). 반면 FR7(LLM 사고 중 발화 합산 재판단)은 별도의 실제 동작 메커니즘
> (`rag_processor.py`의 Supersede/Coalesce)으로 **이미 충족**되어 있었다. 따라서 아래 Story
> 5.2~5.4는 원래 "이미 있는 정교한 로직을 검증"하는 전제였으나, 실제로는 (a) FR7은 검증만 남았고
> (b) FR6/FR8/FR9/FR12는 "죽은 코드(Smart Turn/barge-in LLM 판단)를 되살릴지, 현재의 단순 필터
> (VAD speech_ratio 임계값 + `MinWordsUserTurnStartStrategy` 3단어 게이트 + Google STT 엔드포인팅)로
> 충분한지 결정"하는 문제로 바뀌었다. 아래 Story는 다음 세션에서 이 전제로 재작성이 필요하다.

- **Story 5.1 — 턴테이킹 관련 임계값·로직 전수 조사**: **완료**. 코드 전반(`smart_turn_processor.py`,
  `pipeline_builder.py`의 VAD/barge-in 설정, `barge_in_strategy.py`)에 흩어진 임계값을 한 문서로
  정리(근거 불명 항목 표시) — 결과: 위 범위 재조정 참고.
- **Story 5.2 — "유의미한 발화" 판정 기준 리서치 및 확정**: (재작성 필요) 외부 레퍼런스(Smart Turn
  v3.2, Vogent Turn)를 죽은 코드 부활 검토 자료로 활용할지, 아니면 현재 활성 3개 필터(VAD 비율/
  단어수/STT 엔드포인팅)의 임계값 튜닝으로 범위를 좁힐지부터 결정 필요.
- **Story 5.3 — LLM 사고 중 추가 발화 합산 재판단 검증**: FR7. **이미 코드로 충족되어 있음이 확인됨**
  (Story 5.1) — 남은 작업은 실서버 시나리오 재현 테스트(발화 → LLM 처리 중 추가 발화 → `stt_turn_superseded`
  로그로 병합 처리 확인)로 축소되었다.
- **Story 5.4 — 임계값 조정 및 A/B 검증**: FR8, FR12. 대상이 "Smart Turn/barge-in 임계값"에서
  "VAD `trigger_threshold`/`MinWordsUserTurnStartStrategy.min_words`"로 변경됨. 베이스라인 확보 →
  조정 → 재검증 → 저하 시 롤백 절차 준수.

## Epic 7 — 지능형 발화 종료(턴 완료) 판단 고도화 (2026-07-29 신설)

**배경**: 사용자가 "현재는 묵음만으로 발화 종료를 판단하는데, 사용자가 말하다가 쉬었다가
다시 말하는 경우에도 대화가 끝난 것으로 오인하지 않고 AI가 턴을 가져가도 되는지 스마트하게
판단하기를 원함"을 요청해 신설된 Epic이다. **착수 전 코드 재확인에서 중요한 사실이 하나
발견되었다**: `pipeline_builder.py`가 `UserTurnStrategies(start=[...])`를 생성할 때 `stop=`을
명시하지 않아 pipecat의 기본값(`TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())`,
즉 Smart Turn v3.2 문법/억양/속도 기반 발화완료 모델)이 암묵적으로 적용되고 있음을 실제 파이썬
실행으로 직접 확인했다(2026-07-29). 반면 `config.yaml`의 `smart_turn.*` 설정은 이 모델을 전혀
제어하지 않는다(코드 어디서도 읽히지 않음) — 설정과 실제 동작이 완전히 괴리된 상태이다.
Story 5.1(2026-07-24)은 자체 캐스턴 코드(`smart_turn_processor.py`)만 조사해 죽은 코드로
확정했을 뿐, pipecat 자체 기본값으로 몰래 켜져 있는 이 부분은 확인하지 못했다.

따라서 본 Epic의 출발점은 "없는 기능을 새로 만든다"가 아니라 **"이미 있는데 방치된 블랙박스를
관찰·튜닝 가능한 상태로 만든다"**이다 — 실제 이 모델이 "쉬었다가 다시 말하는" 시나리오에서
정말 잘 동작하는지는 **실제 통화로만 확인 가능**하므로, 조사(Story 7.1) 없이는 개선
방향을 단정할 수 없다.

**목표**: (1) 현재 암묵적으로 동작 중인 Smart Turn v3.2 stop 전략의 실제 행동(정확도·지연)을
관측 가능하게 만든다 (2) 만약 부족이 확인되면 튜닝·보강(예: 일시적 일시 정지 감지, 대화맥락
기반 LLM 보조 판단)을 설계한다 (3) 모든 변경은 feature flag로 옵트인하고 실통화 A/B
검증 전까지 기본값을 유지한다(NFR5 원칙 그대로 적용).

- **Story 7.1 — 현재 Smart Turn stop 전략 실제 동작 조사**: 코드로 이미 확인된 "암묵적 기본값
  적용" 사실을 토대로, 실제 통화에서 이 모델이 발화 중간 일시 정지(필러, 생각하는 침묵)에서
  실제로 "아직 말하는 중"으로 판단하고 있는지 로그로 관측한다(관측용 로깅만 추가, 판단
  로직 변경 없음). 외부 대안(Smart Turn v3.2 튜닝 파라미터, Vogent Turn 멀티모달, LLM 기반
  보조 판단) 리서칭을 병행해 개선 방향을 준비한다.
- **Story 7.2 — 개선 방안 설계 결정**: Story 7.1 관측 결과를 근거로 "튜닝만으로 충분"/"보조 LLM
  판단 레이어 추가 필요"/"대체 모델(Vogent Turn) 검토 필요" 중 하나를 결정하고 상세
  설계를 작성한다(FR13~15).
- **Story 7.3 — 구현(feature flag 옵트인)**: Story 5.4와 동일한 안전 패턴(기본값 비활성, 기존
  동작과 동일 보장)을 따른다(FR16).
- **Story 7.4 — 실통화 A/B 검증**: Story 5.3/5.4와 같은 실통화 QA 세션에서 통합 진행 가능
  (모두 발화 중간·종료 시점을 다루는 시나리오를 공유).

---

## Open Questions (PRD 승인 전 확인 필요)

1. 5초 초과 시 정책(대기 멘트 vs HITL 즉시 폴백)은 제품 관점 결정이 필요하다 — Story 3.3에서 데이터
   기반으로 제안하되 최종 승인은 사용자/PO 확인 필요.
2. `streaming_tts_processor.py`가 정말 미사용 죽은 코드인지, 아니면 다른 진입 경로(레거시
   `pipeline_engine=legacy`)에서 쓰이는지 Story 3.4에서 확정 필요.
3. 턴테이킹 임계값 조정은 실제 통화 트래픽으로만 검증 가능하므로, 운영 환경에서의 A/B 테스트
   승인(사용자 트래픽에 영향)이 필요하다 — copilot-instructions.md의 "포트 충돌/재시작 사용자 승인"
   원칙과 별개로, 실통화 영향 변경이므로 별도 승인 필요.4. Epic 7의 pipecat 기본값 Smart Turn v3.2가 실제로 어느 수준의 정확도를 내는지(한국어
   필러/침묵 패턴에 대한 실측치)는 Story 7.1의 실통화 관측 전까지 알 수 없다 — 이 결과에
   따라 Story 7.2의 설계 방향(튜닝 vs 보조 LLM 판단 레이어 vs 대체 모델)이 크게 달라진다.