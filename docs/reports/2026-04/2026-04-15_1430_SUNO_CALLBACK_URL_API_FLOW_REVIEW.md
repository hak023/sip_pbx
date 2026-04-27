## 메타

- **작성일(로컬)**: 2026-04-15
- **상태**: 문서·로그 보강
- **참고**: [Generate Suno AI Music](https://docs.sunoapi.org/suno-api/generate-music), [Music Generation Callbacks](https://docs.sunoapi.org/suno-api/generate-music-callbacks)

## 개요

Suno API(sunoapi.org)는 ``POST https://api.sunoapi.org/api/v1/generate`` 요청 JSON에 **필수** 필드로 ``callBackUrl``(URI)을 요구한다. 완료·실패 시 해당 URL로 POST 콜백을내며, 폴링은 대안이다. 현재 PBX 구현은 **아웃바운드 generate 본문에 ``callBackUrl``을 포함**하고 있으며, 값은 **환경변수·config**에서만 채운다(클라이언트→PBX 요청에 실을 필요 없음).

## 현재 로직 대조

| 공식 요구 | PBX ``generate_suno_music`` |
|-----------|---------------------------|
| ``POST /api/v1/generate`` | 동일 |
| 필수 ``customMode``, ``instrumental``, ``model``, ``callBackUrl`` | 모두 포함 |
| 커스텀·비기악기: ``style``, ``title``, ``prompt`` | ``style``, ``title``, ``prompt`` 포함 |
| ``callBackUrl`` camelCase | 동일 키명 |
| 콜백 HTTPS·공개 권장 | 운영자 설정으로 보장(미설정 시 로컬에서 400) |

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----------|-----------|------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | 모듈·함수 docstring에 이중 API 흐름·문서 링크; ``suno_generate_outbound`` INFO 로그; 오해 소지 있던 warning `note` 문구 수정 | |

## 잔여 과제

- 콜백 수신 엔드포인트에서 ``callbackType``(text/first/complete)별 idempotent 처리 강화는 선택.
