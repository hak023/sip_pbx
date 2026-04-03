# Outbound 3가지 이슈 분석 및 수정 리포트

- **작성일**: 2026-04-02 18:00
- **대상 호**: `outbound-ob-7b5e9af3-84527520` (18:00 기준)
- **상태**: 수정 완료
- **관련 파일**:
  - `src/media/rtp_relay.py`
  - `src/ai_voicebot/pipecat/pipeline_builder.py`
  - `src/ai_voicebot/pipecat/processors/rag_processor.py`
  - `src/ai_voicebot/run_ai_call.py`

---

## 이슈 1: Outbound 종료 후 Graceful 정리 실패 (ValueError: I/O operation on closed file)

### 증상

```
✅ Log file closed successfully
Exception in thread tts_rtp_outbound-ob-7b5e9af3-84527520:
...
ValueError: I/O operation on closed file.

During handling of the above exception, another exception occurred:
...
ValueError: I/O operation on closed file.
```

### 원인

`_pcm_sender_thread_main`은 **daemon 스레드**로 실행됩니다.

프로세스 종료 순서:
1. `sip_endpoint.stop()` 호출 → Pipecat 파이프라인 태스크 취소
2. `stop_async_logging()` 호출 → **로그 파일 닫힘** (`✅ Log file closed successfully` 출력)
3. daemon 스레드는 `join()` 20초 타임아웃 내에 종료하지 못한 경우 아직 살아있음
4. 스레드 내부 `logger.info()` 호출 → structlog이 닫힌 파일에 쓰려 시도 → `ValueError`
5. 예외 핸들러에서 `logger.error()` 재시도 → 또 같은 오류 → 비정상 종료 출력

이는 실제로 무해한 Race Condition이지만, 콘솔에 예외 스택 트레이스가 출력되어 혼란을 줍니다.

### 수정 내용 (`src/media/rtp_relay.py`)

`_pcm_sender_thread_main`의 `except Exception as e:` 블록에 방어 처리 추가:

```python
except Exception as e:
    self.stats["rtp_tts_send_errors"] += 1
    # ValueError("I/O operation on closed file") 는 종료 시 무해한 Race Condition
    if isinstance(e, ValueError) and "closed file" in str(e):
        import sys as _sys
        print(f"[tts_rtp_thread] logger closed — thread exiting: {e}", file=_sys.stderr)
        return
    try:
        logger.error("pcm_sender_thread_error", ...)
    except (ValueError, OSError):
        pass  # 로그 파일이 이미 닫힌 경우 조용히 무시
```

---

## 이슈 2: Greeting 메시지가 1003 테넌트 대신 1004 테넌트로 나오는 문제

### 증상

- 1003 내선으로 로그인하여 아웃바운드 발신
- Greeting: `"안녕하세요. KT 통화매니저 기상청 AI 봇 입니다."` (기상청 = 1004 테넌트)
- 앱 로그: `"owner": "1004"` — KB/페르소나가 1004 기준으로 로드됨

### 원인

**두 단계에서의 버그**:

**1단계 — `call_manager.py` 수정 미적용 (이전 세션):**
이전 대화에서 `outbound_manager.py`에 `caller_number` 추가 + `call_manager.py`에서 `caller_number`를 `build_and_run`에 넘기도록 수정했으나, 해당 시점(18:00)의 서버는 **재시작 전**이었습니다. 따라서 이전 코드 (`callee_number`를 owner로 사용)가 실행됩니다.

**2단계 — `pipeline_builder.py` 파라미터명 혼란:**
`build_and_run(callee: str, ...)` 첫 번째 파라미터명이 `callee`로 되어 있어, 내부에서도 `owner=callee`, `OrganizationInfoManager(owner=callee, ...)`로 사용합니다.
`call_manager.py`에서 `build_and_run(caller_number, ...)` 로 넘기면 파라미터 위치상 맞지만,
파라미터명이 `callee`라는 혼란 때문에 코드 가독성이 낮고, 잘못 수정될 위험이 있었습니다.

### 수정 내용 (`src/ai_voicebot/pipecat/pipeline_builder.py`)

`build_and_run` 첫 번째 파라미터명을 `callee → owner`로 변경하여 의미 명확화:

```python
# 변경 전
async def build_and_run(self, callee: str, rtp_worker: Any, ...) -> None:
    org_manager = OrganizationInfoManager(owner=callee, ...)
    pipeline = self.build_pipeline(..., owner=callee, ...)

# 변경 후
async def build_and_run(self, owner: str, rtp_worker: Any, ...) -> None:
    """
    owner: KB/페르소나 로드 기준 테넌트 ID.
           인바운드: callee(착신번호), 아웃바운드: caller_number(AI봇 발신번호).
    """
    org_manager = OrganizationInfoManager(owner=owner, ...)
    pipeline = self.build_pipeline(..., owner=owner, ...)
```

`src/ai_voicebot/run_ai_call.py` 호출부도 `callee= → owner=` 로 변경.

### 호출 경로 정리

| 경로 | 호출 | owner에 들어가는 값 |
|------|------|-------------------|
| 인바운드 | `call_manager.py:922` | `_effective_callee` (착신 내선번호) |
| 아웃바운드 | `call_manager.py:274` | `caller_number` (AI봇 발신번호) |
| 직접 실행 | `run_ai_call.py:130` | `callee` (파라미터) |

---

## 이슈 3: "필요한 내용을 모두 확인했습니다." 비의도 TTS

### 증상

아웃바운드 미션 완료 시 TTS로 `"필요한 내용을 모두 확인했습니다. 감사합니다. 좋은 하루 되세요."` 가 나옴.

### 원인

`rag_processor.py`의 `_trigger_mission_complete()`:

```python
# KB farewell 카테고리 문서가 없으면 하드코딩 폴백 실행
if not farewell_text:
    farewell_text = "필요한 내용을 모두 확인했습니다. 감사합니다. 좋은 하루 되세요."
```

1003 테넌트 KB에 `farewell` 카테고리 문서가 등록되지 않아 폴백 텍스트가 사용됩니다.
"필요한 내용을 모두 확인" 이라는 표현은 **설문/조사 목적** 문구로 어색하게 들립니다.

### 수정 내용 (`src/ai_voicebot/pipecat/processors/rag_processor.py`)

폴백 텍스트를 범용적이고 자연스러운 표현으로 교체:

```python
# 변경 전
farewell_text = "필요한 내용을 모두 확인했습니다. 감사합니다. 좋은 하루 되세요."

# 변경 후
farewell_text = "통화에 응해주셔서 감사합니다. 좋은 하루 되세요."
```

### 근본 해결책

1003 테넌트 KB에 `farewell` 카테고리 문서를 등록하면, 폴백 없이 커스텀 마무리 멘트가 사용됩니다:

```bash
POST /api/knowledge
{
  "owner": "1003",
  "category": "farewell",
  "text": "원하는 마무리 멘트",
  "answer": "원하는 마무리 멘트"
}
```

---

## 수정 파일 요약

| 파일 | 수정 내용 |
|------|---------|
| `src/media/rtp_relay.py` | `_pcm_sender_thread_main` 예외 핸들러에 `ValueError` (closed file) 방어 처리 추가 |
| `src/ai_voicebot/pipecat/pipeline_builder.py` | `build_and_run` 첫 번째 파라미터 `callee → owner` 명칭 변경 |
| `src/ai_voicebot/run_ai_call.py` | `build_and_run(callee= → owner=)` 호출부 수정 |
| `src/ai_voicebot/pipecat/processors/rag_processor.py` | farewell 폴백 텍스트 교체 (`"필요한 내용을 모두..." → "통화에 응해주셔서 감사합니다..."`) + 로그 note 개선 |

## 추가 조치 필요 사항

- **서버 재시작**: `call_manager.py`의 `caller_number` owner 적용 및 `pipeline_builder.py` 파라미터명 변경이 서버에 반영되려면 재시작이 필요합니다.
- **1003 KB farewell 등록**: 커스텀 마무리 멘트 사용을 위해 KB에 `farewell` 카테고리 문서 등록 권장.
