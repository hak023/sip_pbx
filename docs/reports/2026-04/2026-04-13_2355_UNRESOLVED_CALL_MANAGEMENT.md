## 개요

통화이력에 통화 단위 "미해결/해결" 상태를 도입하고, AI가 응대하지 못한 경우 통화 종료 시 자동으로 `is_unresolved=true`를 설정한다. "미처리 항목" 탭에 문자 전송 기능을 통합하고 별도 "문자 전송" 탭을 삭제한다. 대시보드의 "평균 AI 신뢰도" 카드를 "미해결 통화" 건수 카드로 교체하며, 모든 통화이력 행에 미해결↔해결 전환 버튼을 추가한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/common/call_insights_buffer.py` | 수정 | `flush_call_insights_to_dir()`에서 `ai_unhandled_count > 0`이면 `is_unresolved: true` 자동 설정 | call_insights.json 페이로드에 필드 추가 |
| `sip-pbx/src/booking/database.py` | 수정 | `call_records` DDL에 `is_unresolved INTEGER NOT NULL DEFAULT 0` 컬럼 추가, `_MIGRATIONS`에 ALTER TABLE 등록 | 기존 DB 자동 마이그레이션 |
| `sip-pbx/src/common/call_record_db.py` | 수정 | `upsert_call_record()`에 `is_unresolved: Optional[bool]` 인자 추가, INSERT/UPDATE 구문 반영 | None이면 UPDATE 시 변경 안 함 |
| `sip-pbx/src/api/routers/call_history.py` | 수정 | 목록 응답 item에 `is_unresolved` 필드 포함(DB·JSON 우선), `PATCH /{call_id}/resolve` 엔드포인트 신규 추가, `ResolveRequest` Pydantic 모델 추가 | JSON > DB 우선 순서 |
| `sip-pbx/frontend/types/api.ts` | 수정 | `CallHistoryRecordItem`에 `is_unresolved?: boolean` 필드 추가 | |
| `sip-pbx/frontend/components/call-history/CallHistoryPanel.tsx` | 수정 | `DetailTab`에서 `"sms"` 제거, "미처리 항목" 탭 하단에 `SmsSendTab` 통합, `FragmentRow`에 resolve 토글 버튼 추가, `CallHistoryPanel`에 `handleResolveToggle` 추가 | |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | "평균 AI 신뢰도" → "미해결 통화" 카드 교체, `DashboardResolveButton` 컴포넌트 추가, 통화이력 행에 토글 버튼 삽입, `handleHistoryResolveToggle` 추가 | |

## 주요 결정 사항

1. **is_unresolved 저장 위치**: `call_insights.json`(파일)과 DB `call_records.is_unresolved` 양쪽에 저장. API 응답 시 JSON이 DB보다 우선함. 수동 토글(`PATCH /resolve`) 시 JSON 파일과 DB 모두 갱신.

2. **자동 미해결 판단 기준**: 통화 종료 시 `flush_call_insights_to_dir()`에서 `ai_unhandled_count > 0`이면 `is_unresolved=true` 자동 설정. HITL로 해결된 건은 이미 `ai_unhandled_count`에서 제외되므로 별도 처리 불필요.

3. **문자 전송 탭 통합**: "문자 전송" 탭을 삭제하고 "미처리 항목" 탭 하단에 구분선과 함께 통합. SMS 상태(`smsText`, `smsSent` 등)는 기존과 동일하게 `CallDetailPanel` 로컬 state로 관리.

4. **대시보드 미해결 건수 계산 방식**: 클라이언트 집계 (A안) 채택. `callHistory.filter(r => r.is_unresolved).length`로 집계하며 백엔드 metrics API 변경 불필요.

5. **토글 버튼 표시 기준**: `is_unresolved` 필드가 없는 레거시 레코드는 `nUnhandled > 0`을 fallback으로 사용해 미해결로 간주.

## 추가 구현 (잔여 과제 해소)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|-----------|------|
| `sip-pbx/src/api/routers/metrics.py` | 수정 | `GET /api/metrics/dashboard` 응답에 `unresolved_calls_count` 추가. DB 우선, 없으면 recordings 폴더 스캔으로 집계 |
| `sip-pbx/frontend/types/api.ts` | 수정 | `DashboardMetrics`에 `unresolved_calls_count?: number` 추가 |
| `sip-pbx/frontend/app/dashboard/page.tsx` | 수정 | 미해결 통화 카드를 최근 20건 클라이언트 집계 → metrics API `unresolved_calls_count` 기반으로 교체. 토글 버튼 클릭 시 `fetchMetrics` 재호출로 카드 즉시 갱신 |
| `sip-pbx/src/api/routers/call_history.py` | 수정 | `POST /api/call-history/batch-init-unresolved` 배치 엔드포인트 추가: call_insights.json 유무·ai_unhandled_count 기반으로 `is_unresolved` 초기값 채움. `dry_run=true` 파라미터로 변경 없이 대상 확인 가능 |
