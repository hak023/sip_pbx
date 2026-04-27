---
작성일: 2026-04-23
상태: 완료
---

## 개요

인입 시 탭 제목 깜빡임(`incomingCallAttention`)이 통화 종료 후에도 멈추지 않던 문제를 수정했다. 원인은 `useActiveCallDockStore.endCall`이 `phase`만 `ended`로 바꾸고 `activeCallId`를 유지하는데, 타이틀 effect가 **`phase === "idle"`일 때만** 정지 조건에 들어가던 점이다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 수정 | 타이틀 알림: `phase !== "active"`이면 `stopIncomingCallTitleAlert(true)` |

## 주요 결정 사항

- 진행 중(`active`)일 때만 인입 알림 타이틀을 켠다. `ended`·`idle`은 동일하게 원 제목 복구.
