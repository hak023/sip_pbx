## 메타

- 작성일: 2026-04-23 (로컬)
- 상태: 점검 메모 (코드 추적)
- 관련: 착신 제어 규칙 우선순위 vs 실제 SIP 라우팅

## 개요

「즉시 AI 응대」규칙을 UI에서 최상위로 두었는데 실콜에서 기대와 다르게 동작하는 경우, 백엔드 평가 순서·스케줄 의미·발신자 필터·owner 일치 여부를 의심한다.

## 백엔드 평가 순서 (실제 인입 INVITE)

`src/sip_core/sip_endpoint.py` 기준:

1. **발신자 필터** (`resolve_caller_filter(callee, caller)`) — 매칭 시 **착신 규칙 목록은 평가하지 않음**
2. 없으면 **`resolve_rule(callee)`** — `src/call_control/routing_engine.py`
3. 규칙이 하나도 안 맞으면 **`operator_status` away** 시에만 `immediate_ai` 폴백, 그 외 **직접 연결**

## 우선순위 숫자 의미 (역전 주의)

- DB 조회: `ORDER BY priority ASC` (`src/call_control/db.py` `list_rules`)
- 모델 주석: **priority가 낮을수록 먼저 평가** (`src/call_control/models.py` `RoutingRule`)

즉 **숫자가 작은 규칙이 “더 센” 우선순위**이다. UI가 “1순위 = 큰 숫자”로 저장하면 **즉시 AI가 아래로 밀린다**.

## 스케줄이 “항상 참”인 경우

`routing_engine._schedule_matches`:

- `days`가 비어 있으면 요일 검사를 건너뜀
- `time_ranges`가 비어 있으면 시간 검사를 건너뜀 → **항상 매칭**

따라서 **priority 숫자가 더 작은 다른 규칙**이 이런 스케줄에 묶여 있으면, 화면에서 즉시 AI를 위로 올려도 **평가 순서상 먼저인 규칙이 매번 이긴다**.

반대로 `schedule_id is None`인 규칙은 루프에서 **해당 순서에 도달하는 즉시** 매칭된다 (항상 조건).

## 대시보드 “현재 적용 규칙” API 한계

`GET /api/call-control/status/{owner}`는 **`resolve_rule(owner)`만** 호출한다 (`call_control_api.get_current_status`).

- **발신자 필터는 반영하지 않는다** → 미리보기는 “즉시 AI”인데 실콜은 필터의 `direct` / 전환 등이 될 수 있다.

## 권장 확인 절차

1. `GET /api/call-control/rules?owner=<착신 내선>` 으로 두 규칙의 **`priority` 정수** 확인 — **즉시 AI가 더 작은 값**인지 확인
2. 다른 규칙의 **`schedule_id`** 및 해당 스케줄의 `days` / `time_ranges` — 비어 있으면 사실상 24/7 매칭
3. `GET /api/call-control/caller-filters?owner=...` — 테스트한 발신 번호가 패턴에 걸리는지
4. 실콜 시 `app.log`에서 `call_control_rule_resolved` / `call_control_caller_filter_matched` 로 **실제 선택된 rule_id·action** 확인

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| (없음) | — | 코드 변경 없음, 분석만 | — |
