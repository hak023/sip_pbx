# Epic 7 신설 — 지능형 발화 종료(턴 완료) 판단 고도화, BMAD 계획 수립

**작성일**: 2026-07-29
**작성자**: Copilot (BMAD PM/Architect/Dev 역할)
**상태**: 기획 완료(PRD/Architecture/Story 7.1~7.4), Story 7.1 조사 착수·핵심 발견
**관련 문서**:
- [voice-latency-turn-taking-prd.md](../../product/voice-latency-turn-taking-prd.md) Epic 7
- [voice-latency-turn-taking-architecture.md](../../architecture/voice-latency-turn-taking-architecture.md) §1.4(정정), §2.4
- [7.1.smart-turn-stop-strategy-investigation.story.md](../../stories/7.1.smart-turn-stop-strategy-investigation.story.md)

## 요청 배경

사용자가 "현재는 유저가 말하면 묵음만 가지고 말이 끝나는지 감지하는데, 사용자가 말하다가 쉬었다가
다시 말하는 경우에도 대화가 끝난 것으로 오인하지 않고 AI가 턴을 가져가도 되는지 스마트하게
판단하기를 원함"을 요청 — 리서칭 후 PRD→아키텍처→스토리→개발→QA 전 과정을 BMAD로 계획해달라고
요청했다.

## 🔴 착수 전 발견한 핵심 사실

계획 수립에 앞서 코드를 직접 실행해 확인한 결과, 사용자의 전제("현재는 묵음만으로 판단")가
**부정확할 가능성이 높다**:

```python
>>> from pipecat.turns.user_turn_strategies import UserTurnStrategies
>>> from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
>>> uts = UserTurnStrategies(start=[MinWordsUserTurnStartStrategy(min_words=3)])
# 로그: Loading Local Smart Turn v3.x model from .../smart-turn-v3.2-cpu.onnx...
# 로그: Loaded Local Smart Turn v3.x
>>> uts.stop
[<...TurnAnalyzerUserTurnStopStrategy object at ...>]
```

`pipeline_builder.py`가 `UserTurnStrategies(start=[...])`를 만들 때 `stop=`을 지정하지 않는데,
pipecat의 dataclass 기본값이 `stop=[TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3())]`
로 자동 채워진다 — 즉 **Smart Turn v3.2(문법/억양/속도 기반 발화완료 판단 모델)가 이미 암묵적으로
동작 중**이다. 반면 `config.yaml`의 `smart_turn.enabled`/`max_hold_secs`는 코드 어디에서도 읽히지
않는 완전한 orphan 설정이다.

Story 5.1(2026-07-24)이 "죽은 코드"로 확정한 것은 이 저장소 자체의 커스텀 래퍼
(`smart_turn_processor.py`)였을 뿐, pipecat 패키지가 내장한 동일 이름의 모델은 조사 범위 밖이었다
— "저장소 코드만 grep했고 의존성 프레임워크의 기본값은 확인하지 않은" 조사 공백이 있었다.

이 발견을 사용자에게 계획 작성 전에 먼저 보고했고, Epic 7의 전제를 "신규 기능 개발"에서 "이미
있는 모델의 관측성 확보 → 필요 시 튜닝/보강"으로 재정의했다.

## BMAD 계획 산출물

| 단계         | 문서                                                              | 내용                                                                               |
| ------------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| PRD          | `voice-latency-turn-taking-prd.md` Epic 7                         | FR13~16(관측가능화/보강/설정정합/feature flag), NFR7~8(정확도·지연 회귀 방지) 추가 |
| Architecture | `voice-latency-turn-taking-architecture.md` §1.4 정정 + §2.4 신설 | "턴 완료=STT 엔드포인팅만" 서술 정정, Epic 7 조사/설계 원칙 정리                   |
| Story 7.1    | 조사(진행 중)                                                     | 핵심 사실 확인·문서 정정 완료, 관측 로깅 설계는 다음 세션                          |
| Story 7.2    | 설계 결정(Draft)                                                  | 7.1 데이터 기반으로 튜닝/보조 LLM/대체 모델 중 결정                                |
| Story 7.3    | 구현(Draft)                                                       | Story 5.4와 동일 안전 패턴(feature flag 기본 비활성)                               |
| Story 7.4    | 실통화 A/B(Draft)                                                 | Story 4.2/5.3/5.4와 동일 세션으로 통합 진행 가능                                   |

## 권고 순서

1. **Story 7.1 마무리**(다음 세션): 관측 로깅 설계 확정(Task 4) — 판단 로직은 건드리지 않고
   로그만 추가하는 방식(Story 5.4의 섀도우 로깅과 동일 원칙).
2. 관측 로깅을 실제 통화 몇 건에 반영해 데이터 축적.
3. Story 7.2에서 데이터 기반 설계 결정.
4. Story 7.3 구현(feature flag 기본 비활성) → 단위테스트.
5. Story 7.4: Story 4.2 Task 5 / Story 5.3 Task 3 / Story 5.4 Task 5와 **동일 실통화 세션**에서
   통합 검증(모두 발화 중간·종료 시점을 다루는 시나리오를 공유하므로 통화 리소스 절약).

---
*최종 업데이트: 2026-07-29*
