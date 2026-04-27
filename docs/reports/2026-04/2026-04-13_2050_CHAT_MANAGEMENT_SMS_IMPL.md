## 개요

SIP MESSAGE 수신/발신 이력을 SQLite에 저장하고, 프론트엔드에 **"채팅 관리"** 메뉴와
통화 이력 인라인 **"💬 문자 전송"** 탭을 추가하였다.

---

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|---|---|---|---|
| `sip-pbx/src/booking/database.py` | 수정 | `chat_messages` 테이블 DDL + 인덱스 2개 추가 | `_DDL` 스트링 말미에 삽입 |
| `sip-pbx/src/services/chat_service.py` | 신규 | `save_chat_message` / `get_threads` / `get_messages` 함수 | SQLite CRUD |
| `sip-pbx/src/api/routers/chat.py` | 신규 | `/api/chat/threads`, `/api/chat/messages`, `/api/chat/send` 엔드포인트 | FastAPI router |
| `sip-pbx/src/api/main.py` | 수정 | `chat_router` import 및 `app.include_router` 등록 | 기존 라우터 뒤에 추가 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_handle_sip_message_method` — WS emit 직후 `chat_service.save_chat_message` 호출 | 수신 메시지 DB 저장 |
| `sip-pbx/frontend/components/AppHeader.tsx` | 수정 | `NAV_ITEMS`에 `{ href: '/chat', label: '채팅 관리' }` 추가 | 6번째 메뉴 |
| `sip-pbx/frontend/app/chat/page.tsx` | 신규 | 스레드 목록(좌) + 대화창(우) + 실시간 WS `sip_message_received` 수신 | Next.js App Router |
| `sip-pbx/frontend/components/call-history/CallHistoryPanel.tsx` | 수정 | `DetailTab`에 `"sms"` 추가, 탭 배열에 `"💬 문자 전송"` 추가, `SmsSendTab` 컴포넌트 삽입 | KB 템플릿 자동 로드 |

---

## 주요 결정 사항

### 1. DB 테이블 — `chat_messages`

- `thread_id` = 고객 전화번호 (대화 기준 키)
- `owner` = 테넌트(서비스 착신번호)
- `direction` = `'inbound'` | `'outbound'`
- 기존 `sms_log` 테이블은 유지하고 신규 발신/수신은 `chat_messages`에 추가 기록
- 인덱스 2개: `(thread_id, owner)` 복합, `(created_at)` 단순

### 2. owner 결정 — `sip_endpoint.py`

SIP endpoint가 테넌트 개념을 직접 갖지 않으므로 다음 순서로 fallback:
1. `self._owner` 속성
2. `self.config.owner`
3. `self.config.sip.listen_ip` (서버 IP를 임시 owner로)
4. 최종 fallback: `"pbx"`

### 3. 채팅 관리 페이지 — WebSocket 실시간 수신

- `wsClient.on("sip_message_received", handler)` 로 실시간 수신
- 현재 열린 스레드와 발신자 일치 시 낙관적 업데이트
- 스레드 목록은 항상 `loadThreads()` 재조회로 갱신

### 4. SmsSendTab — KB 템플릿 자동 로드

- 탭 최초 렌더 시 `GET /api/knowledge?category=greeting_phase1` / `farewell` 호출
- 응답 없거나 오류 시 `DEFAULT_GREETING` / `DEFAULT_FAREWELL` 상수로 폴백
- 선택 버튼("인사말 템플릿", "종료 인사 템플릿", "직접 입력") 으로 textarea 갱신
- 전송: `POST /api/chat/send` — 성공 시 `smsSent=true`, 실패 시 `smsError` 표시

---

## 잔여 과제

- `owner` 결정 로직을 config에서 명시적으로 읽을 수 있도록 `SipConfig` 스키마 확장 고려
- `chat_messages` 미읽음 카운트 기반 알림 뱃지(채팅 관리 메뉴 옆)
- 발신 메시지 실패 시 재전송 UI
