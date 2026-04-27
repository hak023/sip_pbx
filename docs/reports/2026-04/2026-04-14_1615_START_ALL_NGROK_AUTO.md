## 메타

- 작성일: 2026-04-14
- 상태: 완료
- 관련: `sip-pbx/start-all.ps1`, `config/config.yaml` (`ringback.use_ngrok_tunnel`)

## 개요

`start-all.ps1` 실행 시 `config.yaml`에 `use_ngrok_tunnel: true`이면 ngrok 로컬 API(`127.0.0.1:4040`)로 에이전트 동작 여부를 확인하고, 미동작 시 `ngrok http localhost:8000`을 별도 프로세스로 기동한다. PBX 종료(Ctrl+C) 시 이 스크립트가 띄운 ngrok만 함께 종료한다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/start-all.ps1` | 수정 | `use_ngrok_tunnel`일 때 ngrok 자동 기동·종료, `$ApiPort` 변수 | 설계대로 |
| `sip-pbx/docs/reports/2026-04/2026-04-14_1615_START_ALL_NGROK_AUTO.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- ngrok은 **항상**이 아니라 **`use_ngrok_tunnel: true`일 때만** 자동 기동해, Suno/링백 미사용 시 불필요한 프로세스를 피함.
- 이미 4040에 터널이 있으면 **중복 기동하지 않음**.
- 사용자가 수동으로 띄운 ngrok은 PID를 추적하지 않으므로 **종료 시 건드리지 않음**.

## 잔여 과제 (선택)

- API 포트를 `config.yaml`과 단일 소스로 맞추려면 스크립트에서 YAML 파싱 또는 환경 변수 연동이 필요함(현재 `$ApiPort = 8000` 고정).
