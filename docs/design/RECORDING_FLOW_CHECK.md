# 레코딩 파일 저장 → Frontend 조회 흐름 점검
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`TTS_RTP_AND_STT_QUEUE_DESIGN.md`](TTS_RTP_AND_STT_QUEUE_DESIGN.md)
>
---


## 1. 전체 흐름 요약

| 단계 | 담당 | 상태 | 비고 |
|------|------|------|------|
| 1. 통화 중 녹음 저장 | 녹음 파이프라인 | ✅ 구현됨 | `src/recording/wav_writer.py`, `recording_processor.py` |
| 2. API로 파일 제공 | `src/api/routers/recordings.py` | ✅ 구현됨 | stream / mixed.wav / exists |
| 3. 라우터 등록 | `src/api/main.py` | ✅ 구현됨 | `include_router(recordings.router)` |
| 4. Frontend 조회·재생·다운로드 | `frontend/app/call-history/page.tsx` | ✅ 구현됨 | 상세 다이얼로그 내 녹음 섹션 |

---

## 2. 저장 (1단계) — 구현 완료

- **저장 경로**: `RECORDINGS_DIR / {call_id} / mixed.wav` (recordings API와 동일 규칙, call_id sanitize 적용).
- **구현 파일**:
  - **`src/recording/wav_writer.py`**: `save_mixed_wav(call_id, user_chunks, ai_chunks)` — 발신자/AI PCM 청크를 스테레오 16kHz 16bit WAV로 저장 (채널0=발신자, 채널1=AI).
  - **`src/ai_voicebot/pipecat/processors/recording_processor.py`**: Pipecat `RecordingInputProcessor`(발신자 오디오 수집), `RecordingOutputProcessor`(AI 오디오 수집 + EndFrame 시 저장). `create_recording_processors(call_id)` 로 (collector, input_proc, output_proc) 생성.
- **파이프라인 연동**: Pipecat 파이프라인을 조립하는 쪽에서 아래처럼 추가하면 됨.

```python
from src.ai_voicebot.pipecat.processors.recording_processor import create_recording_processors

call_id = rtp_worker.media_session.call_id  # 또는 해당 통화 ID
collector, rec_input, rec_output = create_recording_processors(call_id)

pipeline = Pipeline([
    transport.input(),
    rec_input,    # 발신자 오디오 수집
    vad, stt, ..., tts,
    rec_output,  # AI 오디오 수집 + EndFrame 시 mixed.wav 저장
    transport.output(),
])
```

- 통화 종료 시 파이프라인에 `EndFrame`이 흐르면 `RecordingOutputProcessor`가 `save_mixed_wav`를 호출해 `recordings/{call_id}/mixed.wav`에 저장함.

---

## 3. API 제공 (2·3단계) — 정상 구현

### 3.1 recordings 라우터 (`src/api/routers/recordings.py`)

- **경로 규칙**: `RECORDINGS_DIR / safe_id / "mixed.wav"`, `safe_id = re.sub(r"[^\w\-]", "", call_id)`.
- **엔드포인트**:
  - `GET /api/recordings/{call_id}/exists` → `{ "exists": true|false, "call_id": "..." }`.
  - `GET /api/recordings/{call_id}/mixed.wav` → 파일 다운로드 (Content-Disposition 파일명 포함).
  - `GET /api/recordings/{call_id}/stream` → 스트리밍, Range 헤더 지원 (206 Partial Content).
- **동작**: 파일 없으면 404. 있으면 정상 응답. ✅

### 3.2 라우터 등록 (`src/api/main.py`)

- `from src.api.routers import recordings` 후 `app.include_router(recordings.router)` 로 등록됨. ✅

### 3.3 경로 해석 (작업 디렉터리)

- `RECORDINGS_DIR` 기본값이 `"recordings"` 이므로 **상대 경로**.
- 서버 실행 시 **현재 작업 디렉터리(cwd)** 기준으로 `recordings/` 가 사용됨.
- **권장**: `uvicorn src.api.main:app ...` 실행 시 프로젝트 루트를 cwd로 두거나, 운영 환경에서는 `RECORDINGS_DIR` 에 절대 경로 지정.

---

## 4. Frontend 조회 (4단계) — 정상 구현

### 4.1 통화 상세 다이얼로그 (`frontend/app/call-history/page.tsx`)

- **재생**: `<audio controls src="{API_URL}/api/recordings/{call_id}/stream">` 사용. ✅
- **에러 처리**: `onError` 시 `<audio>` 숨기고 "녹음 파일 없음" 문구 표시. ✅
- **다운로드**: `<a href="{API_URL}/api/recordings/{call_id}/mixed.wav" download target="_blank">` 사용. ✅
- **API URL**: `process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'` 로 백엔드와 일치. ✅

### 4.2 call_history와의 연동

- 목록/상세 응답에 `has_recording` 은 백엔드(call_history)에서 `_recording_exists(call_id)` 로 계산해 제공.
- Frontend는 목록에서 `has_recording` 으로 배지 등 추가 표시는 선택 사항이며, 현재는 상세에서 항상 "녹음" 섹션을 노출하고, 재생 실패 시에만 "녹음 파일 없음"으로 처리. ✅

---

## 5. 참고사항 점검

### 5.1 파이프라인 조립 코드

- **점검 결과**: Pipecat 파이프라인 조립 코드 **구현 완료**.
  - **파일**: `src/ai_voicebot/pipecat/pipeline_builder.py`
  - **PipelineBuilder**: `build_pipeline(rtp_worker, vad, stt, tts, llm_client, ...)` 로 Pipeline 생성. `build_and_run(callee, rtp_worker, ...)` 로 파이프라인 실행 후 종료 시 `on_call_ended(call_id)` 콜백 호출.
  - **레코딩**: 조립 시 `create_recording_processors(call_id)` 로 `rec_input`·`rec_output` 를 자동 삽입 (input 다음, output 직전).
  - **순서**: `transport.input()` → `rec_input` → vad → stt → rag_llm → tts → `rec_output` → `transport.output()`.
- **연동**: CallManager(또는 RTP Worker)에서 `PipelineBuilder(on_call_ended=emit_call_ended).build_and_run(callee, rtp_worker, vad=..., stt=..., tts=..., llm_client=...)` 호출. VAD/STT/TTS/llm_client 는 호출 측에서 생성해 전달.

**CallManager 연동 (기존 코드 대체)**  
AI 통화 시작 시 아래 **한 함수만** 호출하면 됨. `emit_call_started` / `emit_call_ended` / HITL 연동은 내부에서 처리함.

```python
from src.ai_voicebot.run_ai_call import run_ai_voice_pipeline

async def on_ai_call_started(callee: str, rtp_worker):
    await run_ai_voice_pipeline(
        callee=callee,
        rtp_worker=rtp_worker,
        vad=vad, stt=stt, tts=tts, llm_client=llm_client,
        knowledge_service=knowledge_service,
    )
```

### 5.2 RECORDINGS_DIR 및 작업 디렉터리

- **점검 결과**: `RECORDINGS_DIR` 기본값은 `"recordings"` 로 **상대 경로**임 (`recordings.py`, `wav_writer.py`, `call_history.py` 공통).
- **영향**: 서버(cwd)에 따라 `recordings/` 가 다른 디렉터리를 가리킬 수 있음. FastAPI(uvicorn)와 파이프라인(녹음 저장)이 **서로 다른 프로세스**라면, 같은 `RECORDINGS_DIR`(또는 동일 절대 경로)를 쓰도록 맞춰야 API에서 저장된 파일을 찾을 수 있음.
- **권장**: 운영 시 `RECORDINGS_DIR` 환경변수에 **절대 경로** 지정. 단일 프로세스에서 API·파이프라인 모두 돌릴 경우, 실행 cwd를 프로젝트 루트로 통일.

### 5.3 요약

| 참고사항 | 점검 결과 | 조치 |
|----------|-----------|------|
| 파이프라인 조립 코드가 이 레포에 구현돼 있나? | ❌ 미구현 (pipeline_builder.py 등 조립부 없음) | 파이프라인 조립하는 코드에서 `create_recording_processors` 연동 필요 |
| RECORDINGS_DIR 상대 경로 | ✅ 상대 경로 사용 중 | 운영 시 절대 경로 지정 권장, 또는 cwd 통일 |

---

## 6. 결론 및 체크리스트

- **레코딩 파일 저장 (모듈/프로세서)**: 구현 완료. `src/recording/wav_writer.py` + `recording_processor.py`. 파이프라인에 `create_recording_processors(call_id)` 로 생성한 두 프로세서를 삽입하면 EndFrame 시 자동 저장.
- **레코딩 API (제공)**: 구현·등록 모두 완료. 경로·Range·다운로드 파일명 정상.
- **Frontend 조회·재생·다운로드**: 구현 완료. URL·에러 처리 적절함.

| 항목 | 결과 |
|------|------|
| 저장 경로 규칙 일치 (API ↔ 저장) | ✅ 동일 규칙 (RECORDINGS_DIR, safe call_id) |
| save_mixed_wav / RecordingProcessor | ✅ 구현됨 |
| GET /api/recordings/{id}/exists | ✅ 구현됨 |
| GET /api/recordings/{id}/stream | ✅ 구현됨 (Range 지원) |
| GET /api/recordings/{id}/mixed.wav | ✅ 구현됨 |
| FastAPI에 recordings 라우터 등록 | ✅ main.py에 등록됨 |
| 상세에서 재생 URL 및 에러 처리 | ✅ 구현됨 |
| 상세에서 다운로드 링크 | ✅ 구현됨 |
| 파이프라인 연동(조립부) | ✅ 구현됨 | `pipeline_builder.py` 에 레코딩 프로세서 포함, `build_and_run` 시 실행 |
