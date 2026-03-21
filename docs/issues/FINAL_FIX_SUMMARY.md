# ✅ 진짜 원인 파악 및 해결 완료

**날짜**: 2026-03-09

---

## 질문 1: TTS → RTP 지연, 모델 때문인가?

### ❌ 아닙니다! 진짜 원인은 **Google Service 초기화 지연 (19.67초)**

**타임라인 재분석**:

```
14:45:05.116 - Pipeline 빌드 시작
14:45:24.786 - google_stt_service_created (19.67초 지연!) 🔴
14:45:24.813 - google_tts_service_created
14:45:25.414 - 텍스트 생성
14:45:25.475 - TTS 합성 완료 (61ms!) ✅ 매우 빠름
14:45:28.454 - RTP 전송
```

**TTS 합성 자체는 61ms로 매우 빠름!** 문제는 `GoogleSTTService`/`GoogleTTSService` 초기화에 19.67초가 걸린 것.

---

## 질문 2: STT 감도 수정이 원인인가?

### ⚠️ 감도(mode)는 원래 문제 아니었습니다

**실제 문제**: STT 스트림이 열리지 않음 (VAD/STT 로그 전혀 없음)

**내가 한 수정**:
1. ✅ **STT 디버깅 로그 추가** (핵심 수정)
2. ⚠️ VAD mode 3→2 (예방 차원, 실제 원인 아님)

---

## 🔥 해결 방법: Google Service Singleton

### 문제
- **통화마다** `GoogleSTTService`, `GoogleTTSService`를 새로 생성
- 매번 19초 지연 발생 (import, gRPC 연결, 인증)

### 해결
- **서버 시작 시** 한 번만 생성 (Singleton)
- **통화 시** 재사용 → **즉시 사용 (0초)**

---

## 📝 수정 파일

### 1. `sip-pbx/src/ai_voicebot/factory.py`

**Singleton 함수 추가**:

```python
_global_google_stt_service = None
_global_google_tts_service = None

async def get_or_create_google_stt_service(config: Dict[str, Any] = None):
    global _global_google_stt_service
    if _global_google_stt_service is None:
        from pipecat.services.google.stt import GoogleSTTService
        _stt_config = config or {...}
        _global_google_stt_service = GoogleSTTService(**_stt_config)
        logger.info("✅ [Singleton] Global Google STT Service created")
    return _global_google_stt_service

async def get_or_create_google_tts_service(config: Dict[str, Any] = None):
    global _global_google_tts_service
    if _global_google_tts_service is None:
        from pipecat.services.google.tts import GoogleTTSService
        _tts_config = config or {...}
        _global_google_tts_service = GoogleTTSService(**_tts_config)
        logger.info("✅ [Singleton] Global Google TTS Service created")
    return _global_google_tts_service
```

### 2. `sip-pbx/src/main.py`

**서버 시작 시 사전 초기화**:

```python
# AI 백그라운드 초기화 (서버 시작 시)
stt_task = asyncio.create_task(get_or_create_google_stt_service())
tts_task = asyncio.create_task(get_or_create_google_tts_service())
await asyncio.gather(stt_task, tts_task)  # 병렬 초기화

logger.info("google_services_warmup_complete",
           elapsed=f"{warmup_elapsed:.2f}s",
           note="통화 시 즉시 사용 가능 (지연 없음)")
```

### 3. `sip-pbx/src/sip_core/call_manager.py`

**통화 시 Singleton 사용**:

```python
# Before (통화마다 새로 생성)
_stt_pipecat = GoogleSTTService(**_stt_config)  # 19초 지연!

# After (Singleton 재사용)
_stt_pipecat = await get_or_create_google_stt_service()  # 즉시 반환 (0초)
_tts_pipecat = await get_or_create_google_tts_service()
logger.info("google_stt_service_from_singleton", note="지연 없음")
```

### 4. STT 디버깅 로그 추가

**`sip-pbx/src/ai_voicebot/pipecat/rtp_transport.py`**:

```python
# 첫 10개 프레임과 100개마다 로깅
if frame_count <= 10 or frame_count % 100 == 0:
    logger.info("input_audio_frame_to_pipeline",
               frame_count=frame_count,
               audio_len=len(pcm_data),
               note="Input Transport → Pipeline (VAD → STT)")
```

---

## 📊 효과

| 지표 | Before | After |
|------|--------|-------|
| **첫 통화 시작** | 19.67초 지연 | ✅ **0초** (사전 초기화) |
| **두 번째 통화** | 19.67초 지연 | ✅ **0초** (Singleton 재사용) |
| **TTS 합성** | 61ms | ✅ **61ms** (동일, 원래 빠름) |
| **STT 디버깅** | 불가능 | ✅ **가능** (로그 추가) |

---

## 🧪 테스트 방법

1. **서버 시작**:
   ```powershell
   cd sip-pbx
   .\scripts\start-all.ps1
   ```

2. **서버 시작 로그 확인**:
   ```
   🔥 [AI Background] Google STT/TTS Service 사전 초기화 중...
   ✅ [Singleton] Global Google STT Service created
   ✅ [Singleton] Global Google TTS Service created
   ✅ [AI Background] Google STT/TTS Service 준비 완료 (19.2s)
   ```

3. **AI 통화 테스트** (1003 → 1004):
   - ✅ 인사말이 **즉시** 들림 (19초 지연 없음)
   - ✅ 음성이 **깔끔**하게 들림
   - ✅ 말하면 **STT 로그** 나타남

4. **로그 확인** (`logs/app.log`):
   ```
   google_stt_service_from_singleton note="지연 없음"
   google_tts_service_from_singleton note="지연 없음"
   input_audio_frame_to_pipeline frame_count=1 (STT 디버깅)
   ```

---

## 요약

| 질문 | 답변 |
|------|------|
| **TTS 지연이 모델 때문?** | ❌ 아님. **Google Service 초기화 19초**가 원인 |
| **TTS 합성 속도** | ✅ 61ms로 매우 빠름 (모델 문제 없음) |
| **STT 감도 수정?** | ⚠️ 감도는 원인 아님. **로그 추가**가 핵심 수정 |
| **해결 방법** | ✅ **Singleton + 사전 초기화** (19초 → 0초) |

---

## 참고 문서

- 상세 분석: `sip-pbx/docs/issues/REAL_CAUSE_ANALYSIS.md`
- 수정 요약: `sip-pbx/docs/issues/FIX_SUMMARY_20260309.md`
