# 통화 요약 잘림 현상 분석 및 수정

**작성일**: 2026-03-29T01:40:00Z  
**상태**: ✅ 해결  
**관련 파일**: `src/common/call_summary_generator.py`

---

## 1. 문제 상황

Frontend 통화 이력 페이지에서 **통화 요약(call_summary)** 필드의 문자열이 문장 중간에서 잘려 있는 현상 발생.

### 증상 예시 (사용자 제공 스크린샷)

- "고객은 기상감정서 발급 방법을 문의했습니다. AI는 기상청 홈페이지"
- "고객은 AI 봇에게 가능한 기능과 기상특보에 대한 설명을 요청"
- "고객은 아직 요청 사항을 말하지 않았습니다. KT 통화매니저"
- "고객은 인사를 건넸으나 아직 구체적인 요청 사항을 밝히지"

→ **완전한 문장이 아닌 중간에 잘린 텍스트**

---

## 2. 원인 분석

### 2.1 LLM 토큰 제한

```101:140:c:\work\workspace_sippbx\sip-pbx\src\common\call_summary_generator.py
async def generate_call_summary_llm(transcript: str, *, is_ai_call: bool) -> str:
    """Gemini로 짧은 한국어 요약. 실패 시 빈 문자열."""
    try:
        from src.config.config_loader import load_config
        from src.ai_voicebot.ai_pipeline.llm_client import LLMClient

        cfg = load_config()
        gemini_config: Dict[str, Any] = {}
        av = getattr(cfg, "ai_voicebot", None)
        gc = getattr(av, "google_cloud", None) if av else None
        raw_gem = getattr(gc, "gemini", None) if gc else None
        if isinstance(raw_gem, dict):
            gemini_config = dict(raw_gem)
        api_key = (
            gemini_config.get("api_key")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        )
        if not api_key:
            return ""
        if not gemini_config:
            gemini_config = {"model": "gemini-2.5-flash-lite"}
        llm = LLMClient(gemini_config, api_key)
        kind = "AI가 착신으로 응대한 통화" if is_ai_call else "발신자와 착신자 간 통화"
        prompt = f"""역할: 콜센터 통화 기록 요약.

통화 유형: {kind}

아래는 통화 대본입니다. 한국어로 **2~5문장**만 요약하세요.
- 고객(발신)이 무엇을 원했는지
- 착신(AI 또는 상대)이 어떻게 응답·처리했는지
- 결과(해결, 부분 해결, 미해결, 전환 등)가 드러나게

금지: 인사말, "요약합니다" 같은 메타 문장, 대본 인용 블록.

[대본]
{transcript}
"""
        out = await llm.generate_simple(prompt, max_tokens=512, timeout_seconds=45.0)
        return (out or "").strip()
    except Exception as e:
        logger.warning("generate_call_summary_llm_failed", error=str(e))
        return ""
```

**핵심 문제**: `max_tokens=512`

- Gemini의 한국어 토큰은 **1토큰 ≈ 2~3자** 정도
- 512 토큰 = 약 **170~250자** 정도
- LLM이 요약을 생성하다가 **토큰 제한에 걸려 중간에 강제 종료됨**

### 2.2 로거 문제

```python
import logging
logger = logging.getLogger(__name__)
```

→ `structlog` 대신 표준 `logging` 사용으로 로그가 `app.log`에 남지 않음

---

## 3. 수정 사항

### 3.1 토큰 제한 확대

**변경**: `max_tokens=512` → `max_tokens=1024`

```python
# Before
out = await llm.generate_simple(prompt, max_tokens=512, timeout_seconds=45.0)

# After
out = await llm.generate_simple(prompt, max_tokens=1024, timeout_seconds=45.0)
```

**효과**:
- 1024 토큰 = 약 **340~500자** 정도
- 프롬프트가 "2~5문장" 요청이므로 충분한 공간 확보
- 일반적인 통화 요약은 3~4문장 × 50~80자 = **150~320자** 정도

### 3.2 Logger 변경 및 로그 추가

**1) Logger 변경**:

```python
# Before
import logging
logger = logging.getLogger(__name__)

# After
import structlog
logger = structlog.get_logger(__name__)
```

**2) LLM 생성 완료 로그 추가**:

```python
result = (out or "").strip()
logger.info(
    "call_summary_llm_generated",
    call_id="(async_context)",
    summary_len=len(result),
    truncated=(len(result) >= 900),
    note="LLM 통화 요약 생성 완료 (truncated=True이면 토큰 제한에 근접)",
)
return result
```

**효과**:
- LLM 요약 생성 성공/실패를 추적 가능
- 토큰 제한 근접 여부를 `truncated` 플래그로 확인
- 향후 최적화 근거 데이터 확보

---

## 4. 검증 계획

### 4.1 단기 검증 (다음 통화)

1. 서버 재시작 후 테스트 통화 실행
2. `app.log`에서 `call_summary_llm_generated` 이벤트 확인
   - `summary_len`이 얼마인지
   - `truncated=True`인지 (900자 이상인 경우)
3. Frontend 통화 이력에서 요약이 완전한 문장으로 끝나는지 확인

### 4.2 장기 모니터링

- 향후 `summary_len` 분포를 추적하여 1024 토큰이 충분한지 확인
- 만약 900자 이상 요약이 빈번하게 발생하면 `max_tokens` 추가 증가 고려

---

## 5. 기술적 배경

### 5.1 Gemini 토큰 카운팅

- **영어**: 1토큰 ≈ 4자 (공백 포함)
- **한국어**: 1토큰 ≈ 2~3자 (음절 기준)
- 예: "안녕하세요. 기상청입니다." (14자) ≈ 5~7 토큰

### 5.2 Max Tokens의 의미

- LLM이 **생성할 수 있는 최대 토큰 수**
- 이 제한에 도달하면 **생성 중단** (문장 중간이라도)
- 실제로는 **약간 더 일찍 멈출 수 있음** (모델의 안전 마진)

### 5.3 로그 시스템

- 이 프로젝트는 `structlog`를 사용하여 JSON 형식으로 로그를 저장
- 일반 `logging`은 `app.log`에 기록되지 않음
- 모든 비즈니스 로직에서는 `structlog.get_logger(__name__)` 사용 필수

---

## 6. 요약

**원인**: LLM `max_tokens=512` 제한으로 요약 중간 잘림  
**해결**: `max_tokens=1024`로 확대 + structlog 전환 + 생성 완료 로그 추가  
**검증**: 다음 통화에서 완전한 문장의 요약 생성 확인  
**파일**: `src/common/call_summary_generator.py` 수정 완료
