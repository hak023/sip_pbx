# 호 전환 로직 점검 — Python 계층·SIP(설계)·WebSocket

- **작성일**: 2026-03-23  
- **범위**: 이 저장소(`sip-pbx`)에 포함된 코드 기준  
- **상태**: 애플리케이션 계층은 추적 완료. **실제 SIP INVITE/BYE는 `CallManager.transfer_manager` 구현에 위임**되며, 해당 클래스 본문은 **본 스냅샷에 없음**.

---

## 1. 사용자 요청 → `target_number`까지

1. 사용자: 「상담원 연결해줘」 등 → `IntentClassifier.classify_quick` → `TRANSFER_REQUEST`.  
2. `rag_processor._process_with_agent`가 `ContactKnowledgeExtractor.search_contact`로 Chroma 조회 (`owner` + `category=contact`).  
3. 상위 결과 메타의 **`phone_number`**가 `initiate_call_transfer(..., target_number=...)`에 그대로 전달됨.  
4. (선행) TTS 안내 멘트 후, 대시보드용 **`transfer_initiated`** Socket.IO 이벤트 발송 시도 (`emit_transfer_initiated`).

---

## 2. Python: `initiate_call_transfer`가 하는 일 (`src/call_transfer.py`)

- **`_call_manager`**: `src.websocket.server`의 전역( `set_call_manager(cm)` 로 메인 프로세스가 주입).  
- **`transfer_manager`**: `getattr(_call_manager, "transfer_manager", None)`. 없으면 `False` + (설정 시) 실패 이벤트.  
- **실행**: 아래 중 존재하는 메서드 호출(비동기):
  - `await transfer_manager.initiate_transfer(call_id=..., target_number=..., department=...)`
  - 또는 `await transfer_manager.transfer_call(call_id=..., target=..., context={...})`
- **결과**:
  - 성공 시 `emit_transfer_success`, 실패/예외 시 `emit_transfer_failed` (구현부: `src.websocket.server`의 `emit_transfer_*`).
- **`validate_phone_number`**: 모듈에 정의되어 있으나 **`initiate_call_transfer`에서 호출되지 않음** (길이·형식 검증은 호출자/TransferManager에 의존).

---

## 3. SIP·양쪽 레그 처리 — **설계 문서(모듈 독스트링)**

`call_transfer.py` 상단 주석에 정의된 **B2BUA 전제**는 다음과 같다.

| 단계 | 동작 |
|------|------|
| 전제 토폴로지 | 발신자 ↔ **B2BUA** ↔ AI Voicebot(미디어/ SIP 레그) |
| 전환 시 (REFER 미사용) | ① B2BUA가 **AI Voicebot 쪽 레그를 BYE로 종료** |
| | ② B2BUA가 **`target_number`로 새 INVITE** 발신 |
| | ③ **발신자 ↔ B2BUA ↔ 대상**으로 재연결 |

즉 **“기재한 phone_number로 INVITE”**는 **B2BUA(또는 동등한 백투백 UA)가 새로 다이얼**하는 형태로 기술되어 있고, **REFER 기반 블라인드/어텐디드 전환은 쓰지 않는다**고 명시됨.

---

## 4. 이 저장소에 **없는** 부분 (실제 패킷 처리)

- **`CallManager` / `TransferManager` 클래스 정의**: 검색 결과 **본 트리에 소스 없음**. 런타임에만 주입되는 외부/다른 패키지 구현일 수 있음.  
- 따라서 **INVITE의 Request-URI, From/To, SDP 협상, 발신자 레그 유지 여부, BYE 타이밍** 등은 **여기서 코드 인용 불가**.  
- `emit_transfer_ringing` / `emit_transfer_success`를 **누가·언제** 호출하는지도 TransferManager 쪽에서 `server`의 emit을 호출하도록 연동했을 가능성이 큼(본 저장소에는 호출처 없음).

---

## 5. WebSocket 이벤트 계약 (`src/websocket/server.py`)

| 이벤트명 | 용도(주석 기준) |
|----------|-----------------|
| `transfer_initiated` | 전환 시작·대시보드 “전환 중” |
| `transfer_ringing` | 대상 180 Ringing 등 |
| `transfer_success` | 완료·AI 화면 전환 등 |
| `transfer_failed` | 실패 사유 `reason` |

---

## 6. 구현 정합성 메모 (스냅샷)

- `rag_processor`는 `src.websocket_events.emit_transfer_initiated` 사용 → **`websocket_events.py`가 `server`로 위임**하도록 추가함.  
- `call_transfer`의 `emit_transfer_*` 호출은 존재하지 않는 `src.websocket.manager` 대신 **`src.websocket.server`의 동명 함수**를 사용하도록 정리함.

---

## 7. 요약 한 줄

**앱 코드는 `phone_number`를 `TransferManager`에 넘기고, SIP 상세는 “B2BUA가 AI 레그 BYE 후 대상으로 INVITE” 설계로만 고정되어 있으며, 실제 INVITE/양쪽 레그 처리는 이 repo 밖의 `transfer_manager` 구현을 봐야 한다.**
