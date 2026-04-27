## 메타

- 작성일: 2026-04-14 (로컬)
- 상태: 점검·수정 반영
- 관련: `sip-pbx/src/services/ringback_service.py`, `sip-pbx/src/api/routers/ringback.py`, `sip-pbx/frontend/app/settings/call-control/page.tsx`

## 개요

자동 가사 생성이 owner 페르소나를 **참조하도록 설계**되어 있는지 점검했고, 사용자가 본 고정 한국어 가사가 **페르소나 미반영이 아니라 LLM 실패 폴백**임을 확인했다. `GOOGLE_API_KEY` 미인식·동기 `generate_content`·빈 응답 등 보완과 API `warning` 필드를 추가했다.

## 결론 (동작 설명)

1. **`auto_generate_lyrics`** 는 `_fetch_persona_info(owner)` 로 **Chroma 조직 페르소나**(`ensure_persona_service` → `get_persona`)와 **`/api/knowledge`** 일부 카테고리를 합쳐 프롬프트의 `업체 정보` 블록을 만든다.
2. 보고된 가사(`[Intro] 전화 주셔서…`)는 코드의 **`_FALLBACK_LYRICS` 와 동일**하며, 기존 `_call_llm` 의 **예외 시 반환 문자열**과 일치한다. 즉 **Gemini 호출이 실패했거나 키가 없어** 페르소나가 아무리 채워져도 최종 출력이 레스토랑 톤으로 나오지 않았다.
3. 통화이력 등 다른 라우터는 `GEMINI_API_KEY` **또는** `GOOGLE_API_KEY` 를 쓰는데, 링백만 `GEMINI_API_KEY` 만 보던 불일치가 있어 `GOOGLE_API_KEY` 만 설정된 환경에서 가사만 항상 폴백될 수 있었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `_resolve_gemini_api_key`, `_extract_gemini_text`, `generate_content_async`, 무키 시 로그·폴백 명시; `auto_generate_lyrics` 가 dict 반환 (`used_llm`, `warning` 등) |
| `sip-pbx/src/api/routers/ringback.py` | 수정 | `/generate-lyrics` 가 위 dict 그대로 반환 |
| `sip-pbx/frontend/app/settings/call-control/page.tsx` | 수정 | `data.warning` 있으면 에러 영역에 표시 |

## owner `1003` 추가 확인 사항

- Chroma 문서 id는 `persona_{owner}` 이므로 API에 넘기는 `owner` 문자열이 저장 시와 **동일**해야 한다 (공백 제거는 요청·서비스에서 처리).
- 키·네트워크 정상 시에도 내용이 일반적이면, 로그의 `ringback_org_persona_included` / `has_org_persona` 로 페르소나 블록 포함 여부를 확인하면 된다.
