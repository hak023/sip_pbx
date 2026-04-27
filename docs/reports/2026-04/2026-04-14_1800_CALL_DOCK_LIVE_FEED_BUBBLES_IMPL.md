# 콜도크 실시간 말풍선(화자 분류) 구현

- **작성일(로컬)**: 2026-04-14
- **상태**: 구현 완료
- **선행 설계**: CallDock 말풍선 설계 플랜

## 개요

대시보드와 동일한 **구조화 피드**(`LiveFeedLine` + 병합 규칙)를 콜도크에 도입하고, `stt_transcript`의 **화자(speaker/channel)**·**임시/확정**을 반영한다. 병합 로직은 공통 모듈로 추출해 대시보드가 재사용한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/frontend/lib/liveFeedMerge.ts` | 추가 | `LiveFeedLine`, `appendLiveFeedLines`, `pickInterimSttDisplay`, `sttSpeakerLabel`, `parseSttIsFinal`, 상수 `LIVE_FEED_*_MAX` | 대시보드·도크 공유 |
| `sip-pbx/frontend/store/useActiveCallDockStore.ts` | 수정 | `liveSttLines`/`currentTtsLine`/`pushStt`/`setTts` 제거 → `liveFeedLines` + `pushFeedLine` | `LIVE_FEED_DOCK_MAX`=100 |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | STT 화자 라벨·임시 가공 후 `pushFeedLine`; `tts_started`, `ai_greeting`, `hitl_*` 구독 | `tts_completed` 제거(피드에 TTS 누적) |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 수정 | 카드형 말풍선·색 구분·AI 쪽 우측 정렬 | 대시보드 패널과 유사 스타일 |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | `appendLiveFeed` 본문을 `appendLiveFeedLines` 호출로 대체; STT 라벨·`isFinal` 파싱을 공통 함수 사용 | 중복 제거 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1800_CALL_DOCK_LIVE_FEED_BUBBLES_IMPL.md` | 추가 | 본 리포트 | — |

## 주요 결정 사항

- TTS는 별도 `currentTtsLine` 없이 **피드에 `kind: tts` 줄로 적재**해 대시보드와 일치.
- HITL·인사 이벤트도 도크에서 구독해 **동일 스펙트럼**으로 표시.
- 단위 테스트는 생략(프로젝트 기존 tsc 이슈 다수로 검증은 수동·브라우저 권장).

## 잔여 과제 (선택)

- `LiveFeedPanel` 공통 컴포넌트로 대시보드·도크 UI 중복 제거.
