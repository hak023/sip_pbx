# 통화 분석: `ESwY-200ZV` (2026-03-21)

## 요약

| 항목 | 내용 |
|------|------|
| 발·착신 | 1003 → 1004 (AI 테넌트) |
| 흐름 | B2BUA → 10초 무반응 → **무응답 타임아웃 AI 인수** → Pipecat |
| 인사 | KB `greeting_phase1` / phase2 정상, TTS·RTP 진행 |
| **치명적 오류** | 사용자 발화 후 **`IntentClassifier` import 실패** → LLM 응답 워커 중단 |

## 타임라인 (app.log)

1. **03:00:32** INVITE, RTP early bind, 착신 leg `callee_endpoint: 0.0.0.0:0` (더미 바인딩 — 설계상 정상).
2. **03:00:32** `180 Ringing`, `callee_tag` 확보.
3. **03:00:42** `no_answer_timeout_activating_ai` (10초) → CANCEL → 착신 취소, **발신자에게 AI 200 OK**.
4. **03:00:42~** Pipecat 파이프라인 기동, STT/RTP 정상.
5. **03:00:55** STT 최종 `"안녕하세요."` → RAG 사용자 입력 처리 **직후** `user_message_worker_error`.
6. 동일 로그가 **03:01:12** 두 번째 발화에서도 반복.

## 근본 원인 (에러)

```
cannot import name 'IntentClassifier' from 'src.ai_voicebot.pipecat.intents'
```

- `rag_processor._process_with_agent()`가 `from ..intents import IntentClassifier, Intent` 를 사용.
- `intents.py`에는 프롬프트 빌더 함수만 있고 **`Intent` / `IntentClassifier` 미정의** → 첫 사용자 발화에서 ImportError.

## 부가 이슈 (경고·관찰, 통화 실패 원인 아님)

- **`tts_rtp_duration_mismatch`**: Notifier 프레임 수 vs Output 큐 프레임 수 차이 — 로깅/집계 기준 차이 가능, 별도 튜닝.
- **`rtp_interval_violation`**: 20ms 스케줄러 지터 (CPU 부하·동시 TTS/STT).
- **`rtp_tts_queue_empty_timeout`**: PCM 큐 공백 구간 — TTS 청크 간격/합성 지연.
- **`rag_greeting_blocking_start`**: 인사 대기 중 `event.wait()` — 설계상 STT 블로킹 추적용 로그.

## 조치 (구현)

- **`src/ai_voicebot/pipecat/intents.py`** 에 `Intent` enum, `IntentClassifier.classify_quick()` 추가.
  - `TRANSFER_REQUEST`: 한국어 호전환 키워드·정규식 (과매칭 완화).
  - 그 외: `GENERAL` → 기존 LangGraph/RAG 경로.

## 재테스트

1. 동일 시나리오로 통화 후 `user_message_worker_error` 미발생 확인.
2. “마케팅팀에 연결해 주세요” 류 발화 시 `transfer_request_detected` 로그 확인.
