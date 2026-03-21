# Phase 2 인사말 미수신 / DB 로깅 / STT 이슈 점검 보고서

**작성일**: 2026-03-11  
**대상 로그**: app.log 1280–1307 구간 (AI 2-Phase 인사말 및 이후)

---

## 1. Phase 2 인사말이 들리지 않는 문제

### 로그 타임라인

| 시각 | 이벤트 |
|------|--------|
| 19:11:30.809 | Phase 2 Capability guide 생성, TTS started (87자) |
| 19:11:30.831 | **Barge-in detected, stopping TTS** (22ms 후) |
| 19:11:30.831 | TTS stop requested, TTS stopped |
| 19:11:33.197 | TTS synthesis done (2.39s 후), TTS stopped (barge-in) |

### 원인

- Phase 2 TTS가 **시작한 지 22ms 만에** 바지인(Barge-in)이 감지되어 TTS가 중단됨.
- **문제의 본질**: VAD가 음성을 감지했다고 해서 곧바로 “사용자 발화”로 간주하고 `StartInterruptionFrame`을 보내 TTS를 중단한 것이 잘못된 동작임.
- 사용자 발화 인식 조건은 이미 있음: **STT 결과**가 **STT 후처리 필터**(예: 3자 이상, blocklist, 감탄만 스킵 등)를 통과할 때만 인정해야 함.

### 적용한 수정 (VAD 전용 바지인 억제)

- **그레이스 기간 방식 제거**: “일정 시간만 바지인 무시”는 잘못된 방향. 근본적으로 **VAD만으로는 사용자 발화로 보지 않음**.

1. **`barge_in_suppress.py` 추가**
   - `StartInterruptionFrame` / `StopInterruptionFrame`을 **항상 차단**하여 TTS로 전달하지 않음.
   - VAD에서 나온 바지인 이벤트는 “사용자 발화”가 아니므로, TTS가 VAD만으로 중단되지 않음.

2. **사용자 발화 인정 조건 (기존 유지)**
   - **STT** → `TranscriptionFrame` → **RAGLLMProcessor**의 **STT 후처리 필터** (`stt_post_filter`: 3자 이상, blocklist, 감탄만 스킵 등) 통과 시에만 사용자 발화로 처리.
   - 이 조건을 만족할 때만 LLM 응답이 생성되고, 그때 새 TTS가 나가면 됨.

3. **`pipeline_builder.py` – 파이프라인 구성**
   - `vad_wrapped`와 `stt` 사이에 `BargeInSuppressProcessor` 삽입.
   - VAD → **BargeInSuppressProcessor** → STT → RAG/LLM → TTS. 바지인 프레임은 TTS에 도달하지 않음.

### 기대 효과

- Phase 2 인사말이 에코/노이즈에 의해 조기 중단되지 않음.
- “바지인 감지 = 사용자 발화”가 아닌, **“STT 결과 + 기존 조건 = 사용자 발화”**로 일관되게 동작함.

---

## 2. "DB client not configured, skipping LLM logging" 경고

### 발생 위치

- **파일**: `src/ai_voicebot/logging/ai_logger.py`
- **함수**: `log_llm_process()` (비동기)
- **호출**: `llm_client.py`의 `generate_response()` 내부에서  
  `log_llm_process_sync()` → `log_llm_process()` 호출.

### 원인

- `ai_logger`는 전역 `_db_client`에 DB 클라이언트가 **주입된 경우에만** RAG/LLM/지식매칭 로그를 DB에 기록함.
- `set_db_client(db)`가 **한 번도 호출되지 않으면** `_db_client`는 `None`이며,  
  LLM 처리 시 `log_llm_process()`에서 위 경고를 남기고 로깅을 스킵함.

### 해결 방법

**A) DB 로깅을 쓰는 경우 (권장)**

- 앱 초기화 시 DB 클라이언트를 준비한 뒤, AI 로거에 주입.

```python
# main.py 또는 AI 초기화 구간
from src.ai_voicebot.logging.ai_logger import get_ai_logger, set_db_client, try_init_db_from_config

# 방법 1: config에 db_url이 있으면 자동 연결
await try_init_db_from_config(config)

# 방법 2: 직접 클라이언트 생성 후 주입
# db_client = get_database_client()  # 프로젝트의 DB 래퍼
# set_db_client(db_client)
```

- `config`에 `ai_voicebot.logging.db_url` (예: PostgreSQL `asyncpg` URL)이 설정되어 있으면  
  `try_init_db_from_config(config)`만 호출해도 됨.

**B) DB 로깅을 쓰지 않는 경우**

- 현재처럼 경고가 1회만 나오도록 이미 `_db_skip_warned`로 제한되어 있음.
- DB를 쓰지 않을 계획이면, 경고를 제거하거나 `logger.debug`로 낮추려면  
  `ai_logger.py`의 해당 `logger.warning`을 수정하면 됨.

### 요약

- **원인**: `set_db_client()` 미호출로 `_db_client`가 `None`.
- **조치**: DB 사용 시 초기화 시점에 `try_init_db_from_config(config)` 또는 `set_db_client(db)` 호출.

---

## 3. STT 미동작 및 전화 끊김

### 로그에서 보이는 상황

- `"STT streaming started"` (19:11:23.834) 로그는 있음.
- 이후 구간에는 **STT 최종 결과(TranscriptionFrame)** 나 **사용자 발화 내용**을 직접 보여주는 로그가 없음.
- 19:11:30.809에 `"LLM response generated"`, `user_text_length: 140`이 있음 →  
  **어떤 경로로든** 140자 분량의 사용자 입력이 LLM까지 전달된 것은 맞음 (가능성: 이전 대화/세션, 또는 다른 경로).
- 19:11:33.197에 `"engine": "legacy"`로 **AI call handling started** 로그가 찍힘.
- 사용자 진술: “STT가 동작하지 않았고, 전화가 끊겼다.”

### 가능 원인 정리

1. **Phase 2 바지인으로 인한 파이프라인 상태**
   - Phase 2 TTS가 22ms 만에 중단되면서, 파이프라인 내부 상태(TTS 중단, 큐 플러시 등)가 꼬였을 수 있음.
   - 이 경우 STT는 동작하더라도 결과가 다음 단계로 전달되지 않거나, 통화가 불안정해져 끊김으로 이어질 수 있음.
   - **Phase 2 그레이스 기간** 적용으로, 바지인 오탐이 줄어들면 STT와 통화 안정성 개선이 기대됨.

2. **Legacy 엔진 사용**
   - `config`에서 `pipeline_engine`이 `"pipecat"`이 아니면 Pipecat 파이프라인 대신 **legacy** 오케스트레이터가 사용됨.
   - 로그의 `"engine": "legacy"`는 이 구성을 반영한 것일 수 있음.
   - Legacy 경로에서는 STT/LLM/TTS 연결 방식이 다를 수 있으므로,  
     **실제로 Pipecat 파이프라인이 올라와 있는지** config와 초기화 로그 확인 필요.

3. **RTP/연결 이슈**
   - 이전에 분석한 `rtp_relay_connection_lost` 등으로 인해,  
     상대측으로 오디오가 제대로 전달되지 않거나 연결이 끊기면 STT 입력이 부족해질 수 있음.
   - RTP 수정이 반영된 환경에서 다시 테스트해 보는 것이 좋음.

### 권장 점검 사항

- **config**: `ai_voicebot.pipeline_engine`이 `"pipecat"`인지 확인.
- **초기화 로그**: `"Pipecat Pipeline Builder 연결 완료"` / `"pipeline_engine": "pipecat"` 여부 확인.
- **재현 테스트**: Phase 2 그레이스 기간 적용 후, 동일 시나리오에서  
  - Phase 2 인사말이 들리는지,  
  - STT 로그(예: `transcription_final`, `user_text` 등)가 나오는지,  
  - 통화가 끊기지 않는지 확인.

### STT 로그 보강 제안

- Pipecat 파이프라인에서 **TranscriptionFrame**(최종 인식 결과)을 받는 지점에  
  `logger.info("stt_final", text=..., call_id=...)` 등을 추가하면,  
  “STT가 실제로 동작했는지” 로그만으로도 확인하기 쉬움.

---

## 4. 수정/추가된 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/ai_voicebot/pipecat/processors/barge_in_suppress.py` | **신규**. VAD에서 나온 `StartInterruptionFrame`/`StopInterruptionFrame` 항상 차단. 사용자 발화는 STT 결과(기존 조건)로만 인정. |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | 파이프라인에 `BargeInSuppressProcessor` 삽입 (vad_wrapped ↔ stt 사이). |
| ~~`barge_in_grace_filter.py`~~ | **삭제**. 그레이스 기간 방식 미사용. |

---

## 5. 검증 체크리스트

- [ ] Phase 2 인사말이 에코/노이즈로 조기 중단되지 않고 들리는지 확인.
- [ ] 로그에 `vad_barge_in_suppressed`가 (VAD 바지인 발생 시) 찍히는지 확인.
- [ ] 실제 사용자 발화(STT 결과가 3자 이상 등 조건 통과)만 LLM으로 전달되는지 확인.
- [ ] DB 사용 시: `set_db_client()` 또는 `try_init_db_from_config()` 호출 후  
  `"DB client not configured, skipping LLM logging"` 미발생 확인.
- [ ] 동일 시나리오에서 STT 관련 로그 및 통화 끊김 여부 재확인.
