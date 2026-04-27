## 메타

- **작성일(로컬)**: 2026-04-16
- **상태**: 구현 완료
- **관련 플랜**: 인입 알림(백그라운드 탭) 및 UI (탭 1개 이상 열림 전제)

## 개요

대시보드 외 라우트에서도 Socket.IO `call_started` / `stt_transcript` / `tts_*` / `call_ended` 를 구독해 **전역 플로팅 독(GlobalCallDock)** 과 **데스크톱 알림(권한·백그라운드 옵션·벨 잠금 해제)** 을 제공한다. CID용으로 **직전 종료 통화 1건**을 조회하는 REST `GET /api/call-history/caller-context` 를 추가했고, 대시보드는 **`?call_id=`** 쿼리로 피드 통화를 맞춘다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/common/call_record_db.py` | 수정 | `get_prior_inbound_call_for_caller` 추가 | SQLite `call_records` |
| `sip-pbx/src/api/routers/call_history.py` | 수정 | `GET /caller-context` 엔드포인트·숫자 매칭 헬퍼 | `contact_display_name` 는 예약(null) |
| `sip-pbx/frontend/store/useActiveCallDockStore.ts` | 추가 | Zustand + persist(설정만) | |
| `sip-pbx/frontend/lib/callerDisplay.ts` | 추가 | SIP URI 발신 표시 문자열 | |
| `sip-pbx/frontend/lib/playIncomingBeep.ts` | 추가 | 인입 벨 공용 오실레이터 비프 | |
| `sip-pbx/frontend/components/ActiveCallDockProvider.tsx` | 추가 | `wsClient` 이벤트·알림·CID fetch | |
| `sip-pbx/frontend/components/GlobalCallDock.tsx` | 추가 | 플로팅 UI·설정 패널 | |
| `sip-pbx/frontend/components/AppShell.tsx` | 수정 | Provider + Dock 삽입 | 로그인 제외 |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | `?call_id=` 우선으로 `selectedFeedCallId` 동기화 | |
| `sip-pbx/docs/reports/2026-04/2026-04-16_0930_GLOBAL_CALL_DOCK_AND_CALLER_CONTEXT_API.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- **탭이 하나라도 열려 있을 때**만 전제: Web Push 없이 **Notification API + Page Visibility(백그라운드만 옵션)**.
- **벨 소리**: 자동 재생 정책 회피를 위해 **「소리 허용·테스트」** 사용자 제스처 후 `ringUnlocked` + 짧은 오실레이터 비프.
- **이전 통화 매칭**: 발신 문자열에서 숫자 끝 8자(최소 4자)로 `caller_id LIKE` — SIP URI·하이픈 혼용 대응.
- **연락처 이름**: DB 연락처 테이블 미도입으로 API는 `contact_display_name: null` 고정, UI는 **「첫 통화」/「재방문」** 라벨.

## 잔여 과제

- `next build`는 기존 `booking/slots` 타입 오류로 전체 실패할 수 있음(본 변경과 무관).
- 연락처 CRUD 도입 시 `caller-context` 에 `contact_display_name` 연동.
