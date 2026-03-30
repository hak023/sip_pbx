# 호 전환 버튼 누락 · _drain_tts_udp_out_queue 에러 · 필러 TTS 늘어짐 수정

- **작성일**: 2026-03-30 14:19
- **상태**: 수정 완료 (재시작 후 검증 필요)
- **관련 파일**:
  - `sip-pbx/src/ai_voicebot/run_ai_call.py`
  - `sip-pbx/src/media/rtp_relay.py`
  - `sip-pbx/src/ai_voicebot/pipecat/services/debug_google_tts.py`

---

## 1. 호 전환 버튼 누락 (is_ai_handled 미등록)

### 증상
- 대시보드에서 AI 통화인데도 "유저 간"으로 표시되고 "호 전환" 버튼이 없음
- 프론트엔드 코드는 `call.is_ai_handled && (<button>)` 조건으로 정상

### 원인
- `run_ai_call.py`에서 Pipecat 직접 호출 시 `register_active_call()`만 호출
  → `_active_calls_registry`에만 등록
- `call_manager.ai_enabled_calls` (set)에는 **등록하지 않음**
- REST API `/api/calls/active`의 `_get_active_calls_from_manager()`는 3가지 소스를 OR로 확인:
  1. `cid in ai_enabled_calls` ← **False (미등록)**
  2. `metadata.is_ai_handled` ← **False (미설정)**
  3. `_active_calls_registry.get(cid).is_ai_handled` ← **True**
- 하지만 `_get_active_calls_from_manager`가 `get_active_sessions()`로 세션 순회 시,
  해당 call_id가 세션 목록에 없으면 레지스트리 값을 참조하지 못함

### 수정
- **`run_ai_call.py`**: `register_active_call()` 직후에 `_call_manager.ai_enabled_calls.add(call_id)` 추가
  ```python
  from src.api.routers.calls import _call_manager as _cm
  if _cm is not None and hasattr(_cm, "ai_enabled_calls"):
      _cm.ai_enabled_calls.add(call_id)
  ```

---

## 2. _drain_tts_udp_out_queue AttributeError

### 증상
```
AttributeError: 'NoneType' object has no attribute 'get_nowait'
```
- `rtp_relay.py:1048` — `self._tts_udp_out_queue`가 None 상태에서 접근

### 원인
- 통화 종료 시 `cleanup`에서 `self._tts_udp_out_queue = None` 설정 (Line 2157)
- 이미 스케줄링된 `_drain_tts_udp_out_queue` asyncio 태스크가 실행될 때 None 접근

### 수정
- **`rtp_relay.py`** `_drain_tts_udp_out_queue` 내부에서 `self._tts_udp_out_queue`를
  로컬 변수에 먼저 복사하고 None 체크 추가:
  ```python
  _q = self._tts_udp_out_queue
  if _q is None:
      break
  item = _q.get_nowait()
  ```

---

## 3. 필러 TTS ("정보를 확인 중입니다") 늘어짐

### 증상
- "정보를 확인 중입니다. 잠시만 기다려 주세요." 필러 음성이 늘어지는 현상
- 일반 AI 응답은 RTP 구조 개선(Continuous Silence) 후 정상

### 원인 분석
- 필러 TTS도 동일한 Pipecat 파이프라인(push_frame → GoogleTTS → SIPPBXOutput → PCM 큐)을 사용
- **Google TTS 스트리밍 API**가 오디오를 여러 청크로 나누어 반환
  - 청크 간 네트워크 지연(수십~수백ms)이 발생
  - Pipecat `GoogleTTSService._stream_tts()`에서 `async for response in streaming_responses`
  - `audio_buffer`가 `chunk_size`(16000 bytes, 500ms)에 도달할 때마다 프레임 yield
- 두 청크 yield 사이에 지연이 있으면 `pcm_buffer`가 비어 무음이 삽입됨
  → "늘어짐" 현상 발생

### 수정
- **`debug_google_tts.py`**: `run_tts()` 재정의
  - 기존: `async for frame in super().run_tts()` → 각 프레임을 즉시 yield
  - 수정: 모든 프레임을 **먼저 수집(`collected_frames`)** 후 **일괄 yield**
  - 이렇게 하면 Google 스트리밍 API의 청크 간 지연이 RTP 타이밍에 영향을 주지 않음
  - TTS 생성 대기 시간(TTFB)은 증가하지만, 이미 `_LLM_WAIT_NOTIFY_SEC=12초` 후에
    재생되므로 체감 지연 없음

### 트레이드오프
- TTS 첫 오디오 재생 시점이 약간 늦어짐 (전체 합성 완료까지 대기)
- 짧은 문장("정보를 확인 중입니다.", 약 1초)은 영향 미미
- 긴 응답도 `aggregate_sentences=False`이므로 한 번에 합성 → 마찬가지로 영향 적음

---

## 검증 방법

1. 서버 재시작 후 AI 통화 시작
2. 대시보드에서 "AI 응대" 배지 및 "호 전환" 버튼 확인
3. 콘솔에 `_drain_tts_udp_out_queue` 에러 없음 확인
4. LLM 처리 시간이 12초 이상일 때 필러 음성 청취 — 늘어짐 없어야 함
5. 로그에서 `google_tts_api_complete` 이벤트의 `api_elapsed_ms` 확인 (TTS 합성 시간)
6. 로그에서 `ai_enabled_calls_registered` 이벤트 확인
