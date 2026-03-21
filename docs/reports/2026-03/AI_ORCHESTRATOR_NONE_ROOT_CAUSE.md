# AI Orchestrator Not Available — 원인 및 조치

## 로그에서 보이는 현상

부재중 타임아웃(no_answer_timeout) 후 AI 터크오버 시:

```
🔄 [AI Takeover] AI Orchestrator not available (caller RTP will still go to on_packet_received)
ai_orchestrator_not_available: AI Orchestrator is None - cannot activate AI mode
ai_orchestrator_not_available_for_activation: Cannot activate AI mode
```

- B2BUA는 CANCEL 전송, 200 OK 전송, RTP 리다이렉트까지 수행하지만  
- **Pipecat 파이프라인은 기동되지 않음** (오디오는 전달되나 AI 인사말/STT/TTS 없음).

## 원인 (app.log 18:08 재기동 구간 기준)

1. **18:08:30** — Knowledge Extractor 초기화 중 **ImportError**  
   `cannot import name 'TextEmbedder' from 'src.ai_voicebot.knowledge.embedder'`

2. **18:08:31** — CallManager 생성 시 **ai_enabled: false**, **knowledge_extraction_enabled: false**  
   (지식 추출 실패로 AI 관련 플래그가 꺼진 상태로 생성됨)

3. **18:08:33** — AI Voicebot 백그라운드 초기화 **실패**  
   동일 `TextEmbedder` ImportError로 AI Orchestrator·Pipecat Builder가 생성되지 않음.

4. **18:08:33** — `ai_readiness_at_startup`: **ai_orchestrator_set: false**, **pipecat_builder_set: false**

5. **18:09:49** — 부재중 타임아웃 발생 시 Orchestrator가 **None**이라 `ai_orchestrator_not_available` 발생.

정리하면, **TextEmbedder 임포트 실패 → AI Voicebot 초기화 실패 → Orchestrator 미주입** 이어서, no_answer 시점에 Orchestrator가 없는 상태입니다.

## 왜 해결이 안 되는가 (체크 포인트)

`ai_orchestrator_not_available` 이 계속 나오는 경우, **기동 직후**에 찍히는 `ai_readiness_at_startup` 은 **백그라운드 AI 초기화가 끝나기 전** 시점이라 항상 `ai_orchestrator_set: false` 일 수 있다. 따라서 아래를 구분해 봐야 한다.

| 확인할 로그 이벤트 | 의미 |
|--------------------|------|
| **ai_readiness_after_background_init** (ai_orchestrator_set: true) | AI 백그라운드 초기화 **성공** → 부재중 터크오버 시 AI 사용 가능. 이 로그가 **없으면** 아래 중 하나. |
| **ai_init_timeout_60s** | AI 초기화가 60초 안에 끝나지 않음 → 서버는 AI 없이 시작. (Knowledge/Chroma/STT·TTS 워밍업 등이 느릴 때 발생) |
| **ai_voicebot_background_init_error** | AI 초기화 중 예외 발생 (ImportError, ChromaDB, 설정 등). `error`, `error_type` 필드 확인. |
| **ai_voicebot_init_failed** | `create_ai_orchestrator` 가 None 반환 (설정/비활성화 등). |

**부재중 터크오버 시점** 로그에서 다음이 함께 찍힌다 (진단용):

- **no_answer_timeout_activating_ai** — `ai_orchestrator_is_set`, `pipecat_builder_is_set` 로 당시 상태 확인.
- **ai_orchestrator_not_available** — `suggest_check` 에 app.log 검색 키워드 안내.

## 적용한 코드 수정 (sip-pbx)

| 구분 | 파일 | 내용 |
|------|------|------|
| **TextEmbedder export** | `src/ai_voicebot/knowledge/embedder.py` | `TextEmbedder` 클래스 추가 및 export. Knowledge Extraction / AI 초기화에서 `from ...embedder import TextEmbedder` 가 동작하도록 함. |
| **TextEmbedder model_name** | `src/ai_voicebot/knowledge/embedder.py` | 호출부가 `TextEmbedder(model_name="...")` 로 생성하므로 `__init__(self, model=None, model_name=None, **kwargs)` 지원 추가. model_name 이 있으면 해당 이름으로 SentenceTransformer 로드. |
| **DEFAULT_PERSIST_DIRECTORY** | `src/ai_voicebot/knowledge/chromadb_client.py` | `DEFAULT_PERSIST_DIRECTORY = get_chroma_persist_path()` 추가. 시드/메인에서 해당 이름으로 import 시 오류 방지. |

## 점검 방법

1. **서버 재기동** 후 기동 로그 확인:
   - `❌ Knowledge Extractor initialization failed` / `ai_voicebot_background_init_error` 없어야 함.
   - **ai_readiness_after_background_init** 에 **ai_orchestrator_set: true**, **pipecat_builder_set: true** 가 나와야 함 (이 로그가 있어야 부재중 터크오버 시 AI 사용 가능).
   - `server_ready` 에 **ai_voicebot_enabled: true** 가 나와야 함.

2. **통화 시나리오**  
   부재중 10초 후 터크오버 시:
   - `ai_orchestrator_not_available` 없이
   - `✅ [AI Takeover] Pipecat mode - RTP Worker ready` 및 파이프라인 기동 로그가 나오는지 확인.

3. **추가 실패 시**  
   기동 직후 로그에서 다음 순서로 확인:
   - **ai_readiness_after_background_init** 가 있는지 (성공 시 ai_orchestrator_set: true)
   - **ai_init_timeout_60s**, **ai_voicebot_background_init_error**, **ai_voicebot_init_failed** 가 있는지
   - Knowledge Extractor / TextEmbedder 관련 ImportError 또는 초기화 실패
   - `call_manager_initialized` 의 `ai_enabled` 값
   - `ai_readiness_at_startup` (참고: 이 시점에는 아직 백그라운드 초기화 전이라 false일 수 있음)

## 이슈 리포팅 (AI Orchestrator not available)

이슈를 보고할 때 아래 정보를 포함하면 원인 파악이 빠릅니다.

1. **app.log 일부**
   - 서버 **기동 시점**부터 약 2분 구간 (AI 백그라운드 초기화 완료 시점 포함).
   - 다음 이벤트가 **있는지/없는지** 표시:
     - `ai_readiness_after_background_init` (있으면 ai_orchestrator_set, pipecat_builder_set 값)
     - `ai_init_timeout_60s`, `ai_voicebot_background_init_error`, `ai_voicebot_init_failed`
     - `ai_voicebot_ready`, `pipecat_builder_connected_to_call_manager`
   - 부재중 터크오버가 발생한 **통화 시점** 전후 로그:
     - `no_answer_timeout_activating_ai` (ai_orchestrator_is_set, pipecat_builder_is_set 값)
     - `ai_orchestrator_not_available` (전체 라인)

2. **환경**
   - OS, Python 버전, ChromaDB/문서에 적힌 의존성 버전.
   - AI 초기화에 60초 이상 걸리는지 (첫 기동 시 STT/TTS/Chroma 워밍업 등).

3. **재현 절차**
   - 서버 기동 후 몇 초/분 뒤에 발신했는지.
   - 부재중 10초 후 터크오버가 발생한 직후 로그에 `ai_orchestrator_not_available` 가 나오는지.

4. **요약**
   - "app.log에 ai_readiness_after_background_init 없음" / "ai_init_timeout_60s 있음" / "ai_voicebot_background_init_error 있음 (error: ...)" 등 한 줄 요약.

## 참고

- **정상 기동 시** (15:49 구간): Knowledge Import 4단계 성공 → CallManager 생성 후 AI 주입 → `ai_readiness_at_startup` true → 해당 세션에서는 부재중 터크오버 시 AI 정상 기동.
- **실패 기동 시** (18:08 구간): Step 3/4 TextEmbedder import 실패 → AI 초기화 스킵 → Orchestrator 미설정 → 부재중 시 `ai_orchestrator_not_available` 발생.
