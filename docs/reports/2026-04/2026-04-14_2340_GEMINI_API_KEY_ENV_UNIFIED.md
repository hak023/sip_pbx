## 메타

- 작성일: 2026-04-14
- 상태: 완료
- 관련: Gemini LLM 키 해석 통일, config.yaml 키 제거

## 개요

링백 가사 LLM과 AI 보이스봇·지식 추출·통화이력 초안 등이 **동일한 환경 변수 규칙**으로 API 키를 읽도록 통일했다. `config.yaml`의 `gemini.api_key`는 제거하고, **`GEMINI_API_KEY` → `GOOGLE_API_KEY`** 순으로만 해석하는 공통 모듈을 두었다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/src/common/gemini_api_key.py` | 추가 | `resolve_gemini_api_key()` — env만, 위 순서 | 설계대로 |
| `sip-pbx/src/common/__init__.py` | 추가 | 패키지 마커 | |
| `sip-pbx/src/ai_voicebot/factory.py` | 수정 | LLM 키를 config가 아닌 `resolve_gemini_api_key()`로만 로드; dict에서 `api_key` 키 제거 | 설계대로 |
| `sip-pbx/src/sip_core/sip_endpoint.py` | 수정 | 지식 추출용 LLM 동일 헬퍼 사용 | 설계대로 |
| `sip-pbx/src/services/ringback_service.py` | 수정 | 로컬 `_resolve_gemini_api_key` 제거, 헬퍼 사용 | 설계대로 |
| `sip-pbx/src/main.py` | 수정 | help 캐시용 `LLMClient()` 무인자 호출 제거 → env 키 + gemini 설정 dict로 생성 | 설계대로 |
| `sip-pbx/src/api/routers/call_history.py` | 수정 | 미처리 답변 초안용 키도 헬퍼로 통일 | 설계대로 |
| `sip-pbx/config/config.yaml` | 수정 | `gemini.api_key` 실값 삭제, env 안내 주석만 유지 | Git 노출 방지 |

## 주요 결정 사항

- 키는 **파일(config)에 저장하지 않고** 운영 환경(`GEMINI_API_KEY` 또는 `GOOGLE_API_KEY`)에만 둔다.
- 기존 배포에 남아 있을 수 있는 YAML의 `api_key`는 팩토리에서 **로드 후 `pop`하여 무시**한다.

## 잔여 과제

- 이미 커밋·공유된 키가 있다면 **키 로테이션**을 권장한다.
