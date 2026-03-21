# 아웃바운드 API — 대시보드·call_data_record 연동 점검

## 요약

- **대시보드 활성 통화**: 아웃바운드 발신 요청 생성 시 `register_active_call(outbound_id, caller, callee)` 호출로 **활성 통화 목록에 표시**되도록 연동함.
- **call_data_record 로그**: 동일 시점에 `log_call_data(outbound_id, "call_event", "outbound_request_created", ...)` 로 **로그 기록**되도록 연동함.
- **취소 시**: `unregister_active_call(outbound_id)` + `log_call_data(..., "outbound_cancelled")` 로 목록에서 제거 및 로그 기록.

## 동작 구조

| 구분 | 인바운드(실통화) | 아웃바운드(요청) |
|------|------------------|-------------------|
| 활성 통화 등록 | `pipeline_builder` 통화 연결 시 `register_active_call(call_id, ...)` | `POST /api/outbound/` 시 `register_active_call(outbound_id, ...)` |
| call_data_record | `call_connected` / `call_ended` 등 파이프라인 이벤트 | `outbound_request_created` / `outbound_cancelled` |
| 해제 | 통화 종료 시 `unregister_active_call(call_id)` | `POST /api/outbound/{id}/cancel` 시 `unregister_active_call(outbound_id)` |

## 점검 방법

1. **API 서버 기동**  
   - `uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000` (또는 메인 앱에서 API 포함 실행)

2. **아웃바운드 발신 요청 생성**  
   - 프론트: `/outbound/new`에서 발신 요청 후 "발신 요청" 클릭  
   - 또는: `curl -X POST http://localhost:8000/api/outbound/ -H "Content-Type: application/json" -d '{"caller_number":"1004","callee_number":"1003","purpose":"테스트","questions":["확인사항1"],"caller_display_name":"기상청"}'`

3. **대시보드 활성 통화 목록**  
   - 대시보드 페이지에서 **활성 통화** 목록에 방금 만든 요청이 **call_id = outbound_id**, caller/callee가 발신/착신 번호로 뜨는지 확인.  
   - API 직접 확인: `GET http://localhost:8000/api/calls/active` 응답에 해당 `outbound_id` 항목 존재 여부 확인.

4. **call_data_record 로그**  
   - `logs/call_data_record_YYYYMMDD.log` 파일에 아래와 같은 한 줄이 추가되는지 확인.  
   - 생성 시: `"event":"outbound_request_created"`, `caller_number`, `callee_number`, `purpose` 등 포함.  
   - 취소 시: `"event":"outbound_cancelled"` 포함.

5. **취소 후**  
   - `POST /api/outbound/{outbound_id}/cancel` 호출 후  
   - `GET /api/calls/active`에서 해당 항목이 사라졌는지,  
   - `call_data_record_*.log`에 `outbound_cancelled` 한 줄이 추가되었는지 확인.

## 참고

- 아웃바운드는 현재 **요청 생성/취소만** 구현되어 있으며, 실제 SIP 발신·파이프라인 연결은 추후 연동 예정.
- 대시보드와 API가 **같은 프로세스**(같은 uvicorn 인스턴스)에서 동작할 때만 활성 통화 목록에 아웃바운드가 표시됨.
