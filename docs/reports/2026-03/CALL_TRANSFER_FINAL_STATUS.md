# 호 전환 구현 현황 최종 점검

**점검일**: 2026-03-17  
**상태**: ✅ Backend 완료, 🔴 Frontend 필요

---

## ✅ Backend 구현 완료 (검증 완료)

### 1. ContactKnowledgeExtractor ✅
**파일**: `src/ai_voicebot/knowledge/contact_extractor.py`
- [x] 파일 존재 확인: **True**
- [x] ChromaDB 검색 기능
- [x] 전화번호, 부서명, 담당자명 추출

### 2. call_transfer 모듈 ✅
**파일**: `src/call_transfer.py`
- [x] 파일 존재 확인: **True**
- [x] `initiate_call_transfer()` 구현
- [x] `manual_transfer_from_operator()` 구현
- [x] WebSocket 이벤트 연동

### 3. intents 모듈 ✅
**파일**: `src/ai_voicebot/pipecat/intents.py`
- [x] 파일 존재 확인: **True**
- [x] `build_transfer_announcement_prompt()` 구현
- [x] `build_transfer_fallback_prompt()` 구현

### 4. contact category 지원 ✅
**수정 파일**:
- [x] `knowledge_service.py` - "contact" 추가 확인
- [x] `knowledge_router.py` - phone_number 필드 확인
- [x] API 유효성 검증 확인

### 5. WebSocket 수동 전환 ✅
**파일**: `src/websocket/server.py`
- [x] `manual_transfer_request` 핸들러 확인

---

## 🔴 Frontend 구현 필요 (2개 기능)

사용자 요구사항:
- ❌ 연락처 등록 페이지 **불필요** (운영자가 직접 등록하지 않음)
- ✅ 실시간 통화 모니터링 **필요**
- ✅ 착신 테넌트 번호로 호 전환 **필요**

### 필요 기능 1: 실시간 통화 모니터링

**목적**: 운영자가 현재 AI와 통화 중인 모든 통화를 실시간으로 모니터링

**필요 정보**:
- 통화 ID
- 발신 번호 (caller)
- 착신 번호 (callee) - 테넌트 번호
- 통화 상태 (진행 중, AI 응대 중)
- 통화 시작 시간
- STT 실시간 텍스트 (선택)

**WebSocket 이벤트** (이미 구현됨):
```typescript
socket.on("call_started", (data) => {
  // { call_id, caller_number, callee_number, status }
});

socket.on("call_ended", (data) => {
  // { call_id }
});

socket.on("stt_transcript", (data) => {
  // { call_id, text, is_final }
});
```

### 필요 기능 2: 착신 테넌트 번호로 호 전환

**시나리오**:
1. 운영자가 실시간 모니터링 화면에서 통화 확인
2. "내게 전환" 또는 "착신 번호로 전환" 버튼 클릭
3. 해당 통화가 **착신 테넌트의 전화번호**로 전환됨

**착신 테넌트 번호 매핑**:
```
테넌트 1003 (이탈리안 비스트로) → 02-1234-5678
테넌트 1004 (기상청) → 02-8765-4321
```

**Frontend 구현**:
```typescript
const handleTransferToTenant = (callId: string, calleeId: string) => {
  // calleeId (테넌트 ID)로 전화번호 조회
  const tenantPhone = getTenantPhoneNumber(calleeId);
  
  socket.emit("manual_transfer_request", {
    call_id: callId,
    operator_id: currentUser.id,
    target_number: tenantPhone,  // 착신 테넌트 번호
  });
};
```

---

## Frontend 구현 가이드

### 1. LiveCallMonitor 컴포넌트

**파일**: `frontend/components/LiveCallMonitor.tsx`

```typescript
"use client";

import { useEffect, useState } from "react";
import { io, Socket } from "socket.io-client";

interface ActiveCall {
  call_id: string;
  caller_number: string;
  callee_number: string;  // 테넌트 ID (1003, 1004 등)
  status: string;
  start_time: string;
}

// 테넌트 ID → 전화번호 매핑
const TENANT_PHONE_MAP: Record<string, string> = {
  "1003": "02-1234-5678",  // 이탈리안 비스트로
  "1004": "02-8765-4321",  // 기상청
};

export default function LiveCallMonitor() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState<ActiveCall[]>([]);

  useEffect(() => {
    const newSocket = io("http://localhost:8001");
    setSocket(newSocket);

    // 통화 시작
    newSocket.on("call_started", (data) => {
      setActiveCalls((prev) => [
        ...prev,
        {
          call_id: data.call_id,
          caller_number: data.caller_number,
          callee_number: data.callee_number,
          status: data.status || "진행 중",
          start_time: new Date().toISOString(),
        },
      ]);
    });

    // 통화 종료
    newSocket.on("call_ended", (data) => {
      setActiveCalls((prev) =>
        prev.filter((call) => call.call_id !== data.call_id)
      );
    });

    return () => {
      newSocket.close();
    };
  }, []);

  // 착신 테넌트 번호로 호 전환
  const handleTransferToTenant = async (call: ActiveCall) => {
    if (!socket) return;

    const targetNumber = TENANT_PHONE_MAP[call.callee_number];
    
    if (!targetNumber) {
      alert(`테넌트 ${call.callee_number}의 전화번호가 등록되지 않았습니다.`);
      return;
    }

    try {
      socket.emit(
        "manual_transfer_request",
        {
          call_id: call.call_id,
          operator_id: "operator_001",  // 실제로는 로그인 정보에서 가져옴
          target_number: targetNumber,
        },
        (response: { success: boolean; message: string }) => {
          if (response.success) {
            alert("호 전환이 시작되었습니다.");
          } else {
            alert(`호 전환 실패: ${response.message}`);
          }
        }
      );
    } catch (error) {
      console.error("호 전환 오류:", error);
      alert("호 전환 중 오류가 발생했습니다.");
    }
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">실시간 통화 모니터링</h1>

      {activeCalls.length === 0 ? (
        <p className="text-gray-500">진행 중인 통화가 없습니다.</p>
      ) : (
        <div className="space-y-4">
          {activeCalls.map((call) => (
            <div
              key={call.call_id}
              className="border rounded-lg p-4 bg-white shadow"
            >
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div>
                  <p className="text-sm text-gray-600">통화 ID</p>
                  <p className="font-mono text-sm">{call.call_id}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">상태</p>
                  <p className="text-green-600 font-semibold">{call.status}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">발신 번호</p>
                  <p className="font-semibold">{call.caller_number}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">착신 번호 (테넌트)</p>
                  <p className="font-semibold">
                    {call.callee_number}
                    <span className="text-gray-500 text-sm ml-2">
                      ({TENANT_PHONE_MAP[call.callee_number] || "번호 미등록"})
                    </span>
                  </p>
                </div>
              </div>

              <button
                onClick={() => handleTransferToTenant(call)}
                className="w-full bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors"
              >
                착신 테넌트로 전환 ({TENANT_PHONE_MAP[call.callee_number]})
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 2. 페이지 라우팅

**파일**: `frontend/app/live-calls/page.tsx`

```typescript
import LiveCallMonitor from "@/components/LiveCallMonitor";

export default function LiveCallsPage() {
  return <LiveCallMonitor />;
}
```

### 3. 테넌트 전화번호 설정

**옵션 1**: 하드코딩 (간단)
```typescript
const TENANT_PHONE_MAP = {
  "1003": "02-1234-5678",
  "1004": "02-8765-4321",
};
```

**옵션 2**: API에서 조회 (권장)
```typescript
// GET /api/tenants/:tenantId
// 응답: { id: "1003", name: "이탈리안 비스트로", phone: "02-1234-5678" }

const fetchTenantPhone = async (tenantId: string) => {
  const res = await fetch(`http://localhost:8000/api/tenants/${tenantId}`);
  const data = await res.json();
  return data.phone;
};
```

**옵션 3**: ChromaDB에서 조회 (최선)
```typescript
// category="tenant_config"로 저장
// GET /api/knowledge?owner=1003&category=tenant_config
// metadata: { phone_number: "02-1234-5678" }
```

---

## Backend 추가 구현 (선택)

### 테넌트 정보 API

**파일**: `src/api/tenant_router.py` (신규)

```python
from fastapi import APIRouter

router = APIRouter(tags=["tenants"])

# 테넌트 정보 (하드코딩 또는 DB)
TENANT_INFO = {
    "1003": {"id": "1003", "name": "이탈리안 비스트로", "phone": "02-1234-5678"},
    "1004": {"id": "1004", "name": "기상청", "phone": "02-8765-4321"},
}

@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str):
    tenant = TENANT_INFO.get(tenant_id)
    if not tenant:
        raise HTTPException(404, "테넌트 없음")
    return tenant
```

---

## 데이터 흐름

### 착신 테넌트로 호 전환

```
[1. 통화 진행 중]
발신자(010-1111-2222) → B2BUA → AI (테넌트 1004)
    ↓
[2. 운영자 모니터링]
LiveCallMonitor 화면
├─ 통화 ID: abc123
├─ 발신: 010-1111-2222
├─ 착신: 1004 (02-8765-4321)
└─ [착신 테넌트로 전환] 버튼
    ↓
[3. 버튼 클릭]
socket.emit("manual_transfer_request", {
    call_id: "abc123",
    target_number: "02-8765-4321"  // 테넌트 1004 번호
})
    ↓
[4. Backend 처리]
server.py: manual_transfer_request()
    → call_transfer.manual_transfer_from_operator()
    → initiate_call_transfer(call_id, "02-8765-4321")
    ↓
[5. B2BUA 호 전환]
AI 레그 종료 (BYE)
    → 02-8765-4321로 INVITE 발신
    → 발신자 ↔ 테넌트 직접 연결
    ↓
[6. 결과]
발신자(010-1111-2222) → B2BUA → 테넌트(02-8765-4321)
✅ AI 없이 직접 통화
```

---

## 구현 우선순위

### Priority 1: Frontend 실시간 모니터링 (필수)
- [ ] `LiveCallMonitor.tsx` 컴포넌트
- [ ] WebSocket 연결 및 이벤트 수신
- [ ] 진행 중인 통화 목록 표시

### Priority 2: 호 전환 버튼 (필수)
- [ ] "착신 테넌트로 전환" 버튼
- [ ] `manual_transfer_request` 이벤트 발송
- [ ] 성공/실패 알림

### Priority 3: 테넌트 전화번호 관리 (권장)
- [ ] 테넌트 정보 API 또는
- [ ] ChromaDB에 tenant_config 저장 또는
- [ ] Frontend 하드코딩

---

## 테스트 시나리오

### 시나리오: 착신 테넌트로 전환

```
1. 통화 시작
   - 발신자: 010-1111-2222
   - 착신: 1004 (기상청)
   - AI가 응대 중

2. 운영자 모니터링
   - LiveCallMonitor 화면 접속
   - 진행 중인 통화 확인
   - 발신: 010-1111-2222
   - 착신: 1004 (02-8765-4321)

3. 호 전환 실행
   - [착신 테넌트로 전환] 버튼 클릭
   - 확인 메시지: "호 전환이 시작되었습니다."

4. Backend 로그 확인
   grep "manual_transfer_request_received" app.log
   grep "call_transfer_success" app.log

5. 실제 동작
   - AI 레그 종료
   - 02-8765-4321로 INVITE
   - 발신자 ↔ 기상청 직접 통화

6. 화면 업데이트
   - 통화 목록에서 해당 통화 제거 (call_ended 이벤트)
```

---

## 요약

### ✅ Backend 완료 (검증 완료)
1. ContactKnowledgeExtractor ✅
2. call_transfer 모듈 ✅
3. intents 모듈 ✅
4. contact category 지원 ✅
5. WebSocket 수동 전환 핸들러 ✅

### 🔴 Frontend 필요 (2개)
1. **실시간 통화 모니터링** - LiveCallMonitor 컴포넌트
2. **착신 테넌트로 호 전환** - manual_transfer_request 버튼

### ❌ Frontend 불필요
- 연락처 등록 페이지 (사용자 요구사항에 따라 제외)

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-17
