## 개요

ngrok 자동 `callBackUrl` 활성화를 **환경변수만**이 아니라 **`config.yaml`의 `ringback` 섹션**에서 관리할 수 있게 했다. 기존 `RINGBACK_USE_NGROK_TUNNEL` / `RINGBACK_NGROK_LOCAL_API_URL` 은 선택적 오버라이드로 유지했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 |
|-----------|------------|------|
| `sip-pbx/src/services/ringback_service.py` | 수정 | `_yaml_truthy`, `_use_ngrok_tunnel_enabled`, `_ngrok_local_api_base_url`, `_try_public_base_from_ngrok_local_api`가 config 우선·env 보조 |
| `sip-pbx/config/config.yaml` | 수정 | `use_ngrok_tunnel: false`, `ngrok_local_api_url` 주석 |
| `sip-pbx/config/config.example.yaml` | 수정 | 동일 키·문서 안내 |

## 사용법

- 로컬 ngrok: `ringback.use_ngrok_tunnel: true` (및 필요 시 `ringback.ngrok_local_api_url`)
- 한 번에 끄려면 `false` 로 두면 된다.

## 주요 결정 사항

- config와 env **둘 중 하나라도 참**이면 ngrok API를 조회한다(배포·로컬 모두 대응).
