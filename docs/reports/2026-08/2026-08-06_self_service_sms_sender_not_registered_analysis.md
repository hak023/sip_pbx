# 셀프서비스 AI 도우미 문자 전송 시 `sender_not_registered` 오류 — 로직 점검

- 작성일: 2026-08-06
- 상태: 원인 확인 완료(코드 버그 아님, SIP REGISTER 필요 — 환경 제약), 실제 REGISTER로 재현·검증 완료
- 관련 문서: [1.39.response-simulator-integration-review.story.md](../../stories/1.39.response-simulator-integration-review.story.md),
  [2026-08-05_story_1.39_response_simulator_removal_and_real_chat_panel.md](../2026-08/2026-08-05_story_1.39_response_simulator_removal_and_real_chat_panel.md)

## 증상

owner=9001로 로그인한 상태에서 "실제 채팅"(GlobalSmsDock, 자기 자신에게 문자)으로 메시지를
보내면 다음 오류가 발생한다.

```
sender_not_registered — 발신 내선이 SIP에 등록되어 있지 않습니다: '9001'
```

## 로직 확인

`send_chat_sip_message()`(`src/sip_core/sip_endpoint.py:4035`)는 메시지 전송 전에 발신·수신
양쪽이 실제로 SIP `REGISTER`된 내선인지 확인한다.

```python
fk, from_info = self.lookup_registered_user(from_user)
if not fk or not from_info:
    return {"success": False, "code": "sender_not_registered", ...}
```

`lookup_registered_user()`는 서버가 메모리에 들고 있는 `_registered_users`(실제 SIP `REGISTER`
요청을 받아야만 채워짐) 딕셔너리를 조회한다. 즉 **`owner`(예: 9001)로 실제 SIP 소프트폰이
REGISTER되어 있어야만** 통과되는 검사이며, "AI 도우미 셀프서비스" 문자 전송도 일반 고객
메시지와 **완전히 동일한 SIP MESSAGE 발신 경로**(`/api/chat/send` → `send_chat_sip_message`)를
탄다. 셀프서비스라고 이 검사를 우회하는 별도 로직은 없다(설계상 의도된 것으로 보이며, 실제
버그는 아니다).

이 문제는 이미 Story 1.39 실서버 IV에서도 동일하게 관측되어 "본 Story의 결함이 아니라
개발/QA 환경에 owner 9001을 REGISTER한 실제 SIP UA(소프트폰)가 없기 때문"이라고 기록되어
있었다.

## 실증 검증(2026-08-06)

가설을 직접 검증하기 위해, 인증 없이 아무 REGISTER나 200 OK로 수락하는 서버 로직
(`src/sip_core/register_handler.py` — "요구사항: 모든 REGISTER 요청을 항상 200 OK로 응답")을
이용해 임시 테스트 UA로 9001을 REGISTER한 뒤 재현했다.

1. 임시 스크립트로 `REGISTER sip:127.0.0.1:5060`(From/Contact user=9001) 전송 → `200 OK` 수신
   확인(정상 등록됨).
2. 등록된 상태에서 `POST /api/chat/send`(`to_phone=9001, owner=9001`) 호출 →
   `logs/app.log`에 기록된 결과:
   ```
   chat_send_done code=sip_timeout ok=false owner=9001 sip_from=9001 to=9001
   ```
   **`sender_not_registered`가 아니라 `sip_timeout`으로 바뀜** — 발신 내선 등록 검사를
   통과해 실제로 SIP MESSAGE를 전송하는 단계까지 진행됐다는 뜻이다. `sip_timeout`은 임시
   테스트 UA가 20~25초짜리 짧은 리스닝 창을 이미 닫은 뒤 AI 응답(RAG 검색 등으로 지연)이
   와서 발생한 것으로, 별도 문제가 아니라 테스트 스크립트의 한계다.
3. 검증 후 임시 스크립트는 삭제(서버 상태에 영구적 변경 없음, REGISTER는 자연 만료됨).

**결론**: `sender_not_registered`는 self-service 로직의 버그가 아니라, "이 번호(9001)로
실제 SIP 소프트폰이 REGISTER되어 있어야 한다"는 SIP MESSAGE 발신의 정상적인 사전 조건이
충족되지 않아서 발생한다.

## 해결 방법

owner 9001로 로그인해 셀프서비스 문자를 테스트하려면, **그 번호로 실제 SIP 소프트폰(예:
Zoiper, Linphone, X-Lite 등)을 REGISTER**해야 한다. REGISTER는 인증 없이 수락되므로(위
`register_handler.py` 참고), 소프트폰의 SIP 서버 주소를 이 PBX(`config/config.yaml`의
`listen_port: 5060`)로, 계정 사용자명을 `9001`로 설정하고 REGISTER만 성공시키면 이후
셀프서비스 문자 전송·AI 응답 수신이 정상 동작할 것으로 예상된다(단, AI 응답까지 실제
수신 확인은 RAG 검색 지연 등으로 소프트폰 쪽 타임아웃 여유도 충분히 잡아야 함).

## 남은 확인 사항

- 실제 소프트폰으로 등록 후 "AI 응답까지 끝까지" 수신되는지는 이번 세션에서 확인하지 못함
  (임시 UA가 응답을 오래 기다리도록 설계되지 않음) — 다음 검증 시 소프트폰을 실제로 붙여
  종단 확인 권장.
- `sip_timeout`이 발생한 원인(RAG 검색이 수십 초 걸림)은 성능 이슈일 수 있으나, 이번
  점검의 범위(sender_not_registered 원인 규명)를 벗어나 별도 조사가 필요하면 후속으로 진행.

*최종 업데이트: 2026-08-06*
