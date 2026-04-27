# AI Voicebot 에스컬레이션 모드 설계 및 구현

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-04-09 |
| 상태 | 구현 완료 |
| 관련 경로 | `src/config/models.py`, `src/api/routers/persona.py`, `src/ai_voicebot/langgraph/nodes/hitl_alert.py`, `src/ai_voicebot/pipecat/processors/hitl_processor.py`, `frontend/app/settings/persona/page.tsx` |

---

## 1. 배경 및 요구사항

기존에는 AI가 답변하지 못하는 내용이 들어오면 무조건 **HITL(Human-In-The-Loop)** 방식으로 처리했다:
- 운영자 대시보드에 알림 발송
- 운영자가 대시보드에서 답변 입력 → AI가 TTS로 전달

테스트 결과, 상황에 따라 **HITL 대신 즉시 상담원 내선으로 호전환**하는 것이 더 유용한 경우가 있음을 확인.

### 요구사항

| # | 내용 |
|---|---|
| R-01 | Frontend 페르소나 설정 페이지에서 에스컬레이션 방식을 HITL/상담원 중 선택 |
| R-02 | 상담원 선택 시 착신 내선번호를 지정 |
| R-03 | AI 한계 도달 시 설정값에 따라 HITL 또는 SIP 호전환으로 자동 분기 |
| R-04 | 상담원 연결 모드에서는 고객에게 별도 TTS 멘트("담당 상담원에게 연결해 드리겠습니다") 안내 |

---

## 2. 두 가지 에스컬레이션 방식 비교

| 항목 | HITL 모드 | 상담원 직접 연결 모드 |
|---|---|---|
| 설정값 | `escalation_mode = "hitl"` | `escalation_mode = "transfer"` |
| 동작 | 운영자 대시보드에 알림 → 운영자 답변 → AI TTS 전달 | AI TTS("잠시만요, 상담원 연결") → 즉시 SIP REFER |
| 적합한 경우 | 운영자가 대기 중이고 빠르게 답변 가능한 경우 | 복잡한 상담이 필요하거나 운영자 상주가 어려운 경우 |
| 운영자 대시보드 알림 | O | X (바로 호전환) |
| 고객 대기 시간 | 운영자 응답 시간 | SIP REFER 처리 시간 (~1초) |

---

## 3. 아키텍처

```
고객 발화
    │
    ▼
classify_intent → ... → generate_response
    │
    ▼
hitl_alert_node
    │  needs_human=False → 정상 응답
    │
    │  needs_human=True
    ▼
_get_escalation_mode(state)  ← Persona DB에서 escalation_mode 조회
    │
    ├─ escalation_mode="hitl"
    │      needs_transfer=False
    │      → HITLManager.handle_hitl_result(needs_transfer=False)
    │          → 운영자 대시보드 WebSocket 알림
    │          → HITL_REQUEST_MESSAGE TTS 반환
    │
    └─ escalation_mode="transfer"
           needs_transfer=True, transfer_extension="200"
           → HITLManager.handle_hitl_result(needs_transfer=True, transfer_extension="200")
               → TRANSFER_REQUEST_MESSAGE TTS 반환 ("잠시만요. 담당 상담원에게 연결해 드리겠습니다.")
               → on_transfer_request(call_id, reason, extension) 콜백 → SIP REFER 트리거
```

---

## 4. 변경된 파일

### 4-1. `src/config/models.py` — OrganizationPersona 모델

```python
class OrganizationPersona(BaseModel):
    # ... 기존 필드 ...
    escalation_mode: str = Field(
        default="hitl",
        description="에스컬레이션 방식: 'hitl' 또는 'transfer'"
    )
    transfer_extension: Optional[str] = Field(
        default=None,
        description="escalation_mode='transfer'일 때 착신 내선번호"
    )
```

### 4-2. `src/api/routers/persona.py` — API 요청/응답 모델

- `CreatePersonaRequest`: `escalation_mode`, `transfer_extension` 필드 추가
- `UpdatePersonaRequest`: 동일 (Optional)
- `PersonaResponse`: 동일
- `PUT /{owner}` 엔드포인트: 부분 업데이트 로직에 두 필드 반영

### 4-3. `src/ai_voicebot/langgraph/state.py` — ConversationState

```python
needs_transfer: bool   # True면 HITL 대신 SIP 호전환 트리거
transfer_extension: str  # 호전환 대상 내선번호
```

### 4-4. `src/ai_voicebot/langgraph/nodes/hitl_alert.py` — hitl_alert_node

- `_get_escalation_mode(state)` 헬퍼 추가: Persona DB에서 `escalation_mode`, `transfer_extension` 비동기 조회
- `needs_human=True` 시에만 조회 (불필요한 DB 호출 방지)
- 조회 결과를 `needs_transfer`, `transfer_extension` 키로 state에 추가

### 4-5. `src/ai_voicebot/pipecat/processors/hitl_processor.py` — HITLManager

`handle_hitl_result` 메서드에 `needs_transfer`, `transfer_extension` 인자 추가:

```python
if needs_transfer:
    # Transfer 모드: HITL 알림 없이 SIP 호전환 바로 트리거
    await self._on_transfer_request(call_id, reason, extension)
    return "잠시만요. 담당 상담원에게 연결해 드리겠습니다. 잠시 기다려 주세요."
else:
    # HITL 모드: 운영자 대시보드 알림
    await self._on_alert(alert_data)
    return "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다..."
```

### 4-6. `src/ai_voicebot/pipecat/processors/rag_processor.py` — RAGLLMProcessor

`needs_human=True` 분기에서 `result`의 `needs_transfer`, `transfer_extension`을 읽어 `handle_hitl_result`로 전달.

### 4-7. `frontend/app/settings/persona/page.tsx` — Persona 설정 페이지

에스컬레이션 방식 섹션 추가:
- **라디오 버튼**: HITL vs 상담원 직접 연결
- **전환 내선번호 입력**: `escalation_mode=transfer` 선택 시 동적 표시
- **목록 배지**: 각 Persona 카드에 현재 에스컬레이션 방식 표시

---

## 5. 에스컬레이션 모드별 고객 TTS 멘트

| 상황 | HITL 모드 | Transfer 모드 |
|---|---|---|
| AI 한계 도달 | "죄송합니다. 해당 내용은 제가 알지 못하는 내용입니다. 다른 도움이 필요하시면 말씀해 주세요." | "잠시만요. 담당 상담원에게 연결해 드리겠습니다. 잠시 기다려 주세요." |
| 고객이 상담원 요청 (intent=transfer) | 호전환 콜백 + HITL_REQUEST_MESSAGE | 호전환 콜백 + TRANSFER_REQUEST_MESSAGE |

---

## 6. SIP 호전환 콜백 연동

`HITLManager`의 `on_transfer_request` 콜백에 `transfer_extension` 인자가 추가됨.

기존 2-arg 콜백 `(call_id, reason)` 대비 3-arg `(call_id, reason, extension)` 지원:
- 3-arg 우선 시도, `TypeError`면 2-arg 폴백 (하위 호환성 유지)

실제 SIP REFER는 `run_ai_call.py`(또는 SIP B2BUA)의 `on_transfer_request` 구현체에서 처리.
`transfer_extension`이 있으면 해당 내선으로, 없으면 기존 로직(기본 내선)으로 전환.

---

## 7. 설정 방법 (운영자 가이드)

1. Frontend → **설정 → 조직 페르소나** 접속
2. 대상 Persona 수정 버튼 클릭
3. **AI 한계 도달 시 에스컬레이션 방식** 섹션에서 선택:
   - **HITL (운영자 대시보드 알림)**: 기존 방식 유지
   - **상담원 직접 연결 (SIP 호전환)**: 선택 후 상담원 내선번호 입력 (예: `200`)
4. 저장

이후 AI가 답변하지 못하는 질문이 들어오면 설정에 따라 자동 분기됨.

---

## 8. 주의사항 및 제한

- `escalation_mode=transfer`로 설정 시, HITL Q&A 지식베이스 축적이 되지 않음 (알림 자체가 없으므로)
- 호전환 성공/실패는 SIP B2BUA 레이어에서 처리 (`transfer_success` / `transfer_failed` WebSocket 이벤트)
- `transfer_extension`이 비어있으면 기존 `on_transfer_request` 기본 동작으로 폴백
