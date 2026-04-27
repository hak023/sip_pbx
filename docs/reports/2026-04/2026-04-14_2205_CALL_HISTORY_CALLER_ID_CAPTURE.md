## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 점검·수정 반영
- 관련: `sip-pbx/src/sip_core/sip_identity_parse.py`, `sip-pbx/src/sip_core/sip_endpoint.py`, `sip-pbx/src/media/media_session.py`, `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py`, `sip-pbx/src/sip_core/call_manager.py`

## 개요

통화 이력에 발신번호가 비는 현상을 점검했다.원인은 (1) **From 헤더 파싱**이 `sip:` 고정·`tel:`/`sips:` 미지원으로 실패하는 경우, (2) **게이트웨이가 넣는 P-Asserted-Identity 등 미사용**, (3) **AI 통화 시작 시 `call_records`에 넣는 발신자**가 `media_session.caller` 같은 미존재 필드만 참조해 항상 빈 문자열이 되던 점이었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/sip_core/sip_identity_parse.py` | 추가 | `parse_sip_identity_from_header_value` — `sip`/`sips`/`tel`·꺾쇠 URI 공통 파싱 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | `_extract_username` 이 위 파서 사용; INVITE 시 From 비면 P-A-I / P-Preferred / Remote-Party-ID 순 시도; `MediaSession`에 `caller_identity`/`callee_identity` 설정; 아웃바운드 AI 세션에도 동일 필드 설정 |
| `sip-pbx/src/media/media_session.py` | 수정 | `caller_identity`, `callee_identity` 필드 추가 |
| `sip-pbx/src/ai_voicebot/pipecat/pipeline_builder.py` | 수정 | 통화 시작·종료 `upsert_call_record` 시 위 식별자 사용·종료 시 비어 있던 발신 채움 |
| `sip-pbx/src/sip_core/call_manager.py` | 수정 | 레거시 INVITE 경로에서도 `from_uri`/`to_uri`로 식별자 채움 |

## 주요 결정 사항

- SIP 식별자 파싱은 **RFC에서 흔한 변형**(대소문자, `sips:`, `tel:`)을 한 함수로 모은다.
- **명시적 신원 헤더**는 From이 비었을 때만 보조로 사용해 기존 동작을 크게 바꾸지 않는다.
- Pipecat 경로는 **`MediaSession.caller_identity`** 를 단일 소스로 삼아 DB·이력과 정렬한다.

## 잔여 과제 (선택)

- 이미 저장된 `metadata.json` / DB 행은 재처리하지 않음; 필요 시 배치 보정 스크립트 검토.
