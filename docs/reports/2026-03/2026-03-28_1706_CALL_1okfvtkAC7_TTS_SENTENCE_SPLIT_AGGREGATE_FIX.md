# TTS 늘어짐 원인 분석 및 수정 - Call 1okfvtkAC7

**작성일:** 2026-03-28 17:06  
**Call ID:** `1okfvtkAC7`  
**상태:** 수정 완료 (재시작 필요)

---

## 문제 증상

사용자 질의: **"날씨 정보를 문자로 받을 수 있나요?"**

AI 응답 (82자):
> "네, 기상청 공식 페이지에서 날씨 정보를 문자로 받아보실 수 있습니다. 문자 받아보기 신청을 해주시면 됩니다. 더 도움이 필요하시면 말씀해 주세요."

**증상:**
- TTS 재생 시 **늘어지는 현상** 발생
- 인사말은 문제없음

---

## 로그 분석

### app.log 핵심 이벤트

```
16:56:19.711 - llm_exchange_full (82자 전체)
16:56:19.726 - tts_text_input (39자) "네, 기상청 공식 페이지에서..."
16:56:20.537 - tts_text_input (39자) [중복]
16:56:20.537 - tts_text_input (21자) "문자 받아보기 신청을..."
16:56:20.996 - tts_text_input (21자) [중복]
16:56:20.998 - tts_text_input (20자) "더 도움이 필요하시면..."
16:56:21.656 - tts_text_input (20자) [중복]
```

**발견 사항:**
1. 전체 82자 텍스트가 **3개 문장으로 분할**됨
2. 각 문장이 **2번씩 중복** 로깅됨
3. 분할 경계가 **문장 종결자(마침표)** 기준

---

## 원인 규명

### 1. 코드 수정 확인

이전에 수정한 파일들:
- `src/ai_voicebot/langgraph/nodes/generate_response.py` (16:32:58 수정)
  - `chunks = []` (라인 216) ✅ 수정됨
- `src/ai_voicebot/pipecat/processors/rag_processor.py` (16:32:44 수정)
  - `await self.push_frame(TextFrame(text=response))` (라인 1324) ✅ 수정됨

서버 시작: **16:54:06** → 수정된 코드로 실행됨

### 2. 파이프라인 구조

```
rag_llm → korean_tts_numbers → tts (GoogleTTSService) → tts_complete_notifier → rec_output → output
```

### 3. 근본 원인 발견

**`pipecat.services.tts_service.TTSService` 베이스 클래스:**
- `aggregate_sentences: bool = True` (기본값)
- 텍스트를 **문장 단위로 자동 분할**
- `AggregatedTextFrame` / `AggregationType.SENTENCE` 사용

**`src/ai_voicebot/factory.py` - `_build_google_tts_service()`:**
```python
def _build_google_tts_service(config: Dict[str, Any] = None):
    _tts_config = config or {
        "sample_rate": 16000,
        "voice_name": "ko-KR-Standard-A",
        "language_code": "ko-KR",
    }
    return GoogleTTSService(**_tts_config)  # ❌ aggregate_sentences 미지정 → 기본값 True
```

**결과:**
- RAG 응답 82자를 단일 `TextFrame`으로 전송
- Google TTS 서비스가 **내부적으로 문장 분할** (39자 + 21자 + 20자)
- 각 문장마다 **별도 Google TTS API 호출**
- 문장 간 **레이턴시 누적** → 클라이언트 재생 버퍼 고갈 → **늘어지는 현상**

### 4. 인사말은 왜 문제없었나?

**가설 검증 필요:** 인사말도 동일한 TTS 서비스를 사용하므로, 문장 분할이 발생했을 것.  
하지만:
- 인사말은 **더 짧거나**, 또는
- 인사말은 **초기 버퍼 상태**가 충분하여 분할되어도 끊김이 덜 느껴짐
- 또는 **중복 로깅 없음** (로그 조사 필요)

---

## 수정 내용

### 1. `src/ai_voicebot/factory.py`

**`_build_google_tts_service()` 함수 수정:**

```python
def _build_google_tts_service(config: Dict[str, Any] = None):
    """GoogleTTSService 인스턴스 생성 (Singleton·파이프라인 전용 공통)."""
    from pipecat.services.google.tts import GoogleTTSService

    _tts_config = config or {
        "sample_rate": 16000,
        "voice_name": "ko-KR-Standard-A",
        "language_code": "ko-KR",
    }
    # ✅ aggregate_sentences=False: 문장 자동 분할 비활성화
    # Google TTS API는 streaming 미지원 → 분할 시 각 문장마다 별도 API 호출로 레이턴시 누적
    # RAG 응답 전체를 한 번에 전송해야 최적의 재생 품질 (인사말과 동일 방식)
    _tts_config["aggregate_sentences"] = False
    return GoogleTTSService(**_tts_config)
```

**효과:**
- 전체 텍스트를 **단일 API 호출**로 합성
- 문장 간 지연 제거
- 연속적인 오디오 스트림 생성

### 2. 추가 디버깅 로깅

#### `src/ai_voicebot/pipecat/processors/rag_processor.py`

```python
# 📌 RAG → TTS 전달 직전 로깅 (분할 여부 추적)
logger.info("rag_textframe_pushed",
           call=True,
           call_id=self._call_id or "",
           progress="tts",
           category="tts",
           text_len=len(response),
           text_preview=response[:120] if response else "",
           note="RAG → 파이프라인 TextFrame 전송 (단일 프레임 확인용)")
```

#### `src/ai_voicebot/pipecat/processors/korean_tts_number_processor.py`

```python
# 📌 TTS 직전 TextFrame 추적 (분할 원인 파악용)
logger.info(
    "korean_numbers_textframe_input",
    call_id=self._call_id,
    progress="tts",
    category="tts",
    text_len=len(orig),
    text_preview=orig[:80] if orig else "",
    normalized=(norm != orig),
    note="korean_tts_numbers → TTS로 전달 직전 TextFrame (분할 여부 추적)",
)
```

#### `src/ai_voicebot/pipecat/rtp_transport.py`

```python
logger.info("tts_text_input",
            # ...
            direction=str(direction),  # 추가: 프레임 방향 추적
            # ...
            note="TTS로 전달된 텍스트. text_len·text_chunk_*·text_suffix_60 로 잘림 확인")
```

---

## 재시작 후 예상 동작

1. **`rag_textframe_pushed`**: RAG가 82자 전체를 단일 `TextFrame`으로 전송
2. **`korean_numbers_textframe_input`**: korean_tts_numbers 통과 (82자)
3. **`tts_text_input`**: Google TTS 서비스 입력 (82자, **1회만**)
4. **Google TTS API**: 단일 호출로 전체 텍스트 합성
5. **RTP**: 연속적인 오디오 스트림 전송 → **끊김 없는 재생**

---

## 근본 원인 요약

**Pipecat의 `TTSService` 기본 동작:**
- `aggregate_sentences=True` 기본값
- 긴 텍스트를 **문장 단위로 자동 분할**하여 각각 별도 합성

**Google TTS API 특성:**
- Streaming 미지원
- 각 분할된 문장마다 **별도 API 호출** (왕복 레이턴시 누적)
- 문장 간 지연으로 클라이언트 재생 버퍼 고갈

**최종 해결:**
- `aggregate_sentences=False` 설정
- 전체 텍스트를 **단일 API 호출**로 합성
- 인사말과 동일한 처리 방식 (일관성 확보)

---

## 액션 아이템

- [ ] 서버 재시작
- [ ] 동일 질의로 테스트 통화
- [ ] 로그 확인:
  - `rag_textframe_pushed` (82자)
  - `korean_numbers_textframe_input` (82자)
  - `tts_text_input` (82자, 1회만)
- [ ] TTS 재생 품질 확인 (늘어짐 현상 해소)

---

## 참고

### 중복 로깅 원인 (미해결)

각 문장이 2번씩 로깅된 이유는 명확히 밝혀지지 않았으나, 가능성:
- `OutputTransport`가 **다운스트림/업스트림** 양방향으로 프레임 수신
- 또는 파이프라인 내부 프레임 전파 중 특정 프로세서가 `TextFrame` 재발송

재시작 후 로그에서 `direction` 필드로 확인 가능.

### 추가 검증 포인트

- **인사말 로그**: 인사말도 `aggregate_sentences=True` 영향 받았는지 확인
- **중복 방지**: `direction` 필터링 필요 시 `OutputTransport`에서 `UPSTREAM` 무시 추가
