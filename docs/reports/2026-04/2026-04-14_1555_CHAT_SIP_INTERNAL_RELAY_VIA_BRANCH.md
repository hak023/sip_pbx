## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 구현 반영
- 선행: `2026-04-14_1547_CHAT_SIP_MESSAGE_RELAY_AND_TENANT_DB.md` 잔여 과제

## 개요

1. **API 전용 프로세스**에서도 채팅 MESSAGE가 동작하도록, SIP가 떠 있는 PBX 프로세스에 **내부 HTTP**(`POST /internal/sip/chat-message`)를 두고 `deliver_chat_sip_message`가 **인프로세스 실패 시** 해당 URL로 위임한다.  
2. **프록시·다중 Via** 환경에서 잘못된 응답으로 트랜잭션을 닫지 않도록, MESSAGE 발신 시 저장한 **최상위 Via `branch`** 와 최종 응답의 **최상위 Via `branch`** 가 둘 다 있으면 일치할 때만 `Call-ID` 매칭을 완료한다.

## 환경 변수

| 변수 | 용도 |
|------|------|
| `SIP_INTERNAL_API_SECRET` | 내부 HTTP 인증(비어 있으면 PBX 쪽 **내부 서버 미기동**). API·PBX 동일 값. |
| `SIP_INTERNAL_HTTP_HOST` | 내부 바인딩 호스트 (기본 `127.0.0.1`). Docker 등에서는 `0.0.0.0` 등. |
| `SIP_INTERNAL_HTTP_PORT` | 내부 포트 (기본 `18080`). |
| `SIP_MESSAGE_RELAY_BASE_URL` | API 전용 프로세스만: `http://127.0.0.1:18080` 처럼 PBX 내부 URL (끝 `/` 없이). |

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/sip_core/sip_internal_http.py` | 추가 | FastAPI 내부 라우트 + `start_sip_internal_http_server_in_thread` |
| `sip-pbx/src/main.py` | 수정 | `_sip_endpoint` 노출 직후 내부 HTTP 스레드 기동 |
| `sip-pbx/src/services/chat_sip_delivery.py` | 수정 | 인프로세스 → HTTP 릴레이 폴백, 안내 메시지 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_extract_top_via_branch`, 트랜잭션에 branch 저장·응답 검증 |
| `sip-pbx/src/api/main.py` | 수정 | 모듈 docstring에 분리 기동 시 env 안내 |

## 잔여 과제 (선택)

- TLS(mTLS)로 내부 구간 보강.
- 응답에 Via가 여러 개이고 최상단 branch가 비어 있는 UA에 대한 추가 휴리스틱.
