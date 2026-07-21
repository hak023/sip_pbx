# 결함①·② 근본 원인 점검 + 대화 안내 문구 개선(메인화면 클릭 경로) 완료 보고서

**작성일**: 2026-07-20
**관련 문서**:
- [self-service-ai-assistant-master-qa.md](../../qa/self-service-ai-assistant-master-qa.md) §3, §3-1 (갱신됨)
- [1.11.screen-graph-guided-assistance.story.md](../../stories/1.11.screen-graph-guided-assistance.story.md) (Change Log 갱신)

---

## 1. 요청 요약

1. 이전 세션에서 발견한 결함①(자동설정 "켜기" 실패)·결함②(도움말 페이지 탭 클릭 실패)의 근본
   원인을 점검.
2. AI가 대화 중 설정 화면을 안내할 때 API 경로/URL이 아니라 "메인화면에서 어떻게 이동해야
   하는지"를 설명하도록 개선 방향 검토.

## 2. 결함① 점검 결과 — 근본 원인 확정(2차 조사, 서버 재시작 후)

- 서버(포트 8000)가 진짜로 재시작되었음을 프로세스 시작 시각으로 확인(PID 60692, 17:40:15 시작 — 이전 프로세스와 다름)한 후, 동일 재현 시나리오("채팅 자동응답 켜줌" → "응 맞아, 켜줌")를 다시 실행해 진단 로그를 확보했다.
- **중요 정정**: 추가 표본으로 재검증한 결과 "켜기만 실패"라는 초기 결론이 틀렸다 — "끔기" 방향("치팅 자동응답 끄줘" → "응 맞아, 끄줘")도 동일하게 재현되었다(owner 9001). 최종 표본: 켜기 5회 시도 중 5회 실패, 끄기 3회 시도 중 1회 실패.
- 진단 로그(`self_service_agent_gemini_fc_empty_candidate`)로 매번 확인한 결과, 실패 라운드마다 `finish_reason: "1"`(Gemini SDK 기준 **STOP** = 정상 종료), `safety_ratings: []`, `parts: []`로 기록되었다. 즉 **예외도 안전 필터 차단도 아니고, Gemini가 스스로 "정상적으로" 완전히 빈 응답을 반환**하는 현상이다.
- **최종 판정**: self_service 코드 버그가 아니라 **외부 LLM API(`google-generativeai`)의 알려진 간헔적 신뢰성 문제**로 판정한다. "방향 특정 버그"라는 초기 결론은 표본이 적어서 발생한 재현이라는 점을 교훈으로 기록한다.
- **조치**: `_run_self_service_tool_loop()`에 빈 candidate 감지 시 동일 라운드 내 최대 2회 재시도(`_MAX_EMPTY_CANDIDATE_RETRIES=2`)하는 완화 로직을 추가했다. 단위 테스트 2건(재시도 후 성공 / 재시도 소진 후 빈 응답) 추가해 전체 self_service 스위트(280건) 회귀 없음 확인. **사용자가 재차 서버 재시작을 보류**해 재시도 로직 자체의 실서버 효과는 이번 세션에서 검증하지 못했다 — 다음 재시작 시 동일 시나리오를 5회 이상 반복 실행해 실패율이 낮아지는지 확인 필요.

## 3. 결함② 점검 결과 — 중요 정정

- 동일한 Playwright 클릭 타임아웃을 `/dashboard`(새로고침 버튼)와 최상단 내비게이션 링크
  ("지식베이스")에서도 재현했다 — **Story 1.11/1.12나 self_service 기능과 무관하게 앱
  전체에서 클릭이 등록되지 않는 전역 현상**임을 확인했다. 이전 세션의 "Story 1.11/1.12
  프론트엔드 결함"이라는 분류는 **잘못된 것으로 정정**한다.
- 근본 원인 후보: 브라우저 콘솔에 `ws://127.0.0.1:8001/socket.io` 연결 실패가 반복되고
  `/dashboard`가 "연결 중…" 상태에 멈춰 있다 — WebSocket(Socket.IO, 포트 8001) 핸드셰이크가
  근본적으로 실패하고 있는 것으로 보인다. 포트 자체는 열려 있고 백엔드도 `python-socketio`로
  정상 구현되어 있어 프로세스 미기동 문제는 아니며, 인증 토큰 거부나 handshake 프로토콜
  불일치 등 더 깊은 원인이 있을 것으로 추정되나 이번 세션에서 확정하지 못했다(self_service
  Epic 범위 밖의 별도 플랫폼 이슈로 판단).
- 이 문제가 실제 사용자의 수동 클릭에도 영향을 주는지, 아니면 Playwright의 엄격한 "안정성"
  판정 때문에 자동화에서만 나타나는 현상인지는 이번 조사로 확정할 수 없었다(수동 테스트 필요).

## 4. 대화 안내 문구 개선 (메인화면 클릭 경로)

### 문제

Branch C2/H1/H4 등 실제 QA 응답을 보면 AI가 "/settings/chat-relay 화면에서" 같은 **raw
프론트엔드 URL을 그대로 대화에 노출**했다. 전화·문자로 대화 중인 사용자는 URL을 알 수도,
알 필요도 없다.

### 조사

`frontend/components/AppHeader.tsx`의 실제 메뉴 구조를 확인했다:
- 최상단: 지식베이스 / 통화이력 / 연락처 / 발신 관리 / 예약 관리 / 채팅 관리 / **설정▾**
- 설정 드롭다운(그룹): 일반 설정(연동·외부 서비스) / 통화·착신(착신 제어) /
  조직·채팅(AI 에스컬레이션, 채팅·SIP MESSAGE) / 셀프서비스 AI 도우미(AI 도우미 변경 이력)

### 조치

- `src/ai_voicebot/self_service/screen_graph.py`: `ScreenEntry`에 `nav_hint` 필드 신규 추가
  (메인화면 기준 클릭 경로, 예: "화면 상단 메뉴의 '설정' 버튼을 누른 뒤 '조직·채팅' 항목의
  'AI 에스컬레이션'을 선택하세요"). 6개 도메인 모두 실제 메뉴 구조 기준으로 작성.
- `describe_screen_for_conversation()`이 `route`(raw URL) 대신 `nav_hint`를 사용하도록 수정.
  `route`는 프론트엔드 "화면 안내" 탭의 클릭 이동용으로만 남겨두었다(사람이 보고 클릭하는
  시각적 UI이므로 raw route가 적절 — 대화체 안내와는 다른 용도).
- 단위 테스트(`test_self_service_screen_graph.py`) 갱신 — raw route가 대화체 안내에 **없어야
  함**을 검증하도록 변경.

### 검증 상태

- 단위 테스트: 전체 self_service 스위트 재실행 → 회귀 없음(전부 PASS).
- **실서버 검증 완료**(2026-07-20 서버 재시작 후): owner 9003으로 "채팅 자동응답 설정 좀 보여줘"를
  질의한 결과, 응답이 "이 설정은 '설정' 메뉴에서 '조직·채팅' 항목의 '채팅·SIP MESSAGE'를
  선택하시면 확인하고 변경하실 수 있습니다"로 나와 raw route(`/settings/chat-relay`) 노출 없이
  메인화면 기준 클릭 경로만 언급됨을 확인했다.

## 5. 변경 파일

- `src/ai_voicebot/langgraph/nodes/self_service_agent.py` (수정 — 결함① 진단 로그 + 빈 candidate 재시도 완화 로직 추가)
- `src/ai_voicebot/self_service/screen_graph.py` (수정 — `nav_hint` 필드 추가, 6개 도메인 등록에 반영)
- `tests_new/unit/test_ai_voicebot/test_self_service_screen_graph.py` (수정 — nav_hint 검증으로 갱신)
- `tests_new/unit/test_ai_voicebot/test_self_service_settings_tool.py` (수정 — 빈 candidate 재시도 성공/소진 테스트 2건 추가)
- `docs/qa/self-service-ai-assistant-master-qa.md` (수정 — §3/§3-1 갱신, 결함① 근본 원인 정정, 결함② 재분류)
- `docs/stories/1.11.screen-graph-guided-assistance.story.md` (수정 — Change Log 추가)

## 6. 후속 권장 사항

1. **다음 서버 재시작 시 필수 검증**: 결함① 재시도 로직(`_MAX_EMPTY_CANDIDATE_RETRIES=2`)의 실서버
   효과 — 동일 시나리오를 5회 이상 반복 실행해 실패율이 낮아지는지 확인.
2. **결함②는 별도 트랙으로 분리 권장**: self_service Epic과 무관한 WebSocket/실시간 대시보드
   연결 문제이므로, 별도 이슈로 등록해 조사하는 것을 권장(대시보드의 "연결 중…" 고착 상태도
   함께 조사 대상).
3. **`booking_agent.py` 점검 권장**: 동일한 Gemini FC tool-calling 루프를 사용하므로 유사한
   빈 응답 현상이 잠재적으로 있을 수 있음(미확인) — 향후 유사 증상 보고 시 우선 의심 대상으로 기록.

*최종 업데이트: 2026-07-20*
