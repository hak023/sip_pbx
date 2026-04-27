## 메타

- 작성일: 2026-04-15
- 상태: 구현 완료
- 관련: contact 지식, Call Control 착신 전환, AI 호전환 INVITE

## 개요

연락처(contact) 지식 등록 시 Call Control «착신 전환» 대상을 불러와 `fwd:<uuid>`로 저장하고, 실제 SIP 전환 INVITE에서 착신 라우팅과 동일하게 내선으로 해석하도록 했다. 지식 UI에 안내·바로가기·선택/직접 내선 입력을 추가했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|------------|------|------|
| `src/call_control/forward_resolve.py` | 추가 | `fwd:` → 등록 내선 1개 해석 공유 함수 | DB·그룹 pick·등록 검증 |
| `src/sip_core/sip_endpoint.py` | 수정 | `_call_control_resolve_forward_target`의 fwd 분기를 공유 함수 사용 | 중복 제거 |
| `src/sip_core/sip_endpoint.py` | 수정 | `send_transfer_invite`에서 `fwd:`를 원호 callee 기준으로 내선 치환 후 INVITE | KB 전환 경로 |
| `src/api/routers/knowledge_api.py` | 수정 | `KnowledgeCreateBody.transfer_label`, `department`/`name` Field 설명 | 메타 저장 |
| `src/ai_voicebot/knowledge/contact_extractor.py` | 수정 | `transfer_label` 반환, fwd 로그 마스킹 | |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | 수정 | 안내 멘트·전환 호출에 `transfer_label`/부서 폴백, LLM 프롬프트에 fwd 비노출 문구 | |
| `frontend/app/knowledge/page.tsx` | 수정 | contact 시 forward-targets 로드, 선택·직접 내선, help, Call Control 링크 | |

## 주요 결정 사항

- `resolve_fwd_ref_to_registered_extension`를 call_control에 두어 착신 전환 라우팅과 전환 INVITE가 동일 알고리즘을 사용한다.
- 전환 INVITE의 `rule_owner`는 원호 `callee_username`으로 두어, Call Control `forward_targets.owner`와 일치시킨다.
- 직접 내선 입력이 선택보다 우선해 운영자가 빠르게 덮어쓸 수 있다.
- `transfer_label`은 착신 전환 대상 표시명을 자동 저장해 TTS 안내 맥락에 사용한다(수동 department/name UI 없음).

## 잔여 과제

- 지식 목록 테이블에서 contact 행의 `phone_number`/라벨 요약 표시는 선택 사항.
