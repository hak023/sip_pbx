## 메타

- 작성일: 2026-04-15
- 상태: 완료
- 관련: `src/ai_voicebot/langgraph/checkpointer.py`, `requirements-ai.txt`

## 개요

`app.log`의 `langgraph_checkpoint_sqlite_not_installed` 경고는 `langgraph-checkpoint-sqlite` 미설치 시 `SqliteSaver` import 실패 후 `MemorySaver`로 폴백하면서 출력된다. AI 의존성 목록에 패키지를 추가하고 venv에서 설치·import 검증을 수행했다.

## 변경 이력 (파일별)

| 파일 경로 | 변경 유형 | 요약 | 비고 |
|-----|-----|---|---|
| `sip-pbx/requirements-ai.txt` | 수정 | `langgraph-checkpoint-sqlite>=2.0.0` 추가 | |
| `sip-pbx/start-all.ps1` | 수정 | `NeedInstall` 시 `pip install -r requirements-ai.txt` 수행 | 기존에 스탬프만 비교하고 AI 파일 미설치였음 |
| `sip-pbx/docs/reports/2026-04/2026-04-15_1635_LANGGRAPH_CHECKPOINT_SQLITE_DEPS.md` | 추가 | 본 리포트 | |

## 주요 결정 사항

- `checkpointer.py` 로직은 유지하고, **선택 의존성을 명시**해 신규/재설치 시 SQLite 경로가 기본이 되도록 함.
- 버전 하한 `2.x`는 현재 venv의 `langgraph`와 호환되는 `SqliteSaver` import를 기준으로 함.

## 잔여 과제

- 이미 돌아가는 프로세스는 재시작 후 `langgraph_checkpointer_sqlite` INFO 로그로 전환되는지 확인.
