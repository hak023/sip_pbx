# 호 전환 Frontend 설계 수정안

**수정일**: 2026-03-17  
**이유**: LiveCallMonitor를 별도 페이지가 아닌 Dashboard에 통합

---

## 기존 설계의 문제점

### ❌ 기존 설계
```
/live-calls 페이지 (별도)
└─ LiveCallMonitor 컴포넌트
   ├─ 실시간 통화 목록
   └─ 호 전환 버튼
```

**문제**:
- 운영자가 두 개의 페이지를 왔다갔다 해야 함
- Dashboard와 기능이 중복될 수 있음
- UX가 비효율적

---

## ✅ 수정된 설계

### 통합 Dashboard 구조

```
/dashboard 페이지 (메인)
├─ 실시간 통화 섹션 (LiveCallMonitor 기능 통합)
│  ├─ 진행 중인 통화 목록
│  ├─ 각 통화별 상세 정보
│  └─ [착신 테넌트로 전환] 버튼
│
├─ HITL 요청 섹션 (기존)
│  ├─ 미처리 HITL 목록
│  └─ 응답 입력 폼
│
└─ 시스템 상태 섹션 (선택)
   ├─ AI 상태
   └─ 통화 통계
```

---

## 구현 방안

### Option 1: Dashboard 단일 페이지 (권장)

**파일**: `frontend/app/dashboard/page.tsx`

```typescript
"use client";

import { useEffect, useState } from "react";
import { io, Socket } from "socket.io-client";

interface ActiveCall {
  call_id: string;
  caller_number: string;
  callee_number: string;
  status: string;
  start_time: string;
}

interface HITLRequest {
  call_id: string;
  question: string;
  context: any;
  urgency: string;
}

const TENANT_PHONE_MAP: Record<string, string> = {
  "1003": "02-1234-5678",
  "1004": "02-8765-4321",
};

export default function Dashboard() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState<ActiveCall[]>([]);
  const [hitlRequests, setHitlRequests] = useState<HITLRequest[]>([]);

  useEffect(() => {
    const newSocket = io("http://localhost:8001");
    setSocket(newSocket);

    // 통화 관련 이벤트
    newSocket.on("call_started", (data) => {
      setActiveCalls((prev) => [...prev, {
        call_id: data.call_id,
        caller_number: data.caller_number,
        callee_number: data.callee_number,
        status: "진행 중",
        start_time: new Date().toISOString(),
      }]);
    });

    newSocket.on("call_ended", (data) => {
      setActiveCalls((prev) => prev.filter(c => c.call_id !== data.call_id));
    });

    // HITL 이벤트
    newSocket.on("hitl_requested", (data) => {
      setHitlRequests((prev) => [...prev, data]);
    });

    newSocket.on("hitl_resolved", (data) => {
      setHitlRequests((prev) => prev.filter(h => h.call_id !== data.call_id));
    });

    return () => {
      newSocket.close();
    };
  }, []);

  const handleTransfer = (call: ActiveCall) => {
    if (!socket) return;
    
    const targetNumber = TENANT_PHONE_MAP[call.callee_number];
    if (!targetNumber) {
      alert("테넌트 전화번호가 등록되지 않았습니다.");
      return;
    }

    socket.emit("manual_transfer_request", {
      call_id: call.call_id,
      operator_id: "operator_001",
      target_number: targetNumber,
    }, (response: any) => {
      if (response.success) {
        alert("호 전환이 시작되었습니다.");
      } else {
        alert(`호 전환 실패: ${response.message}`);
      }
    });
  };

  const handleHITLResponse = (hitl: HITLRequest, responseText: string) => {
    if (!socket) return;

    socket.emit("submit_hitl_response", {
      call_id: hitl.call_id,
      response_text: responseText,
      original_question: hitl.question,
      save_to_kb: false,
    });
  };

  return (
    <div className="min-h-screen bg-gray-100 p-6">
      <h1 className="text-3xl font-bold mb-8">운영자 대시보드</h1>

      {/* 실시간 통화 섹션 */}
      <section className="mb-8">
        <h2 className="text-2xl font-semibold mb-4">
          실시간 통화 ({activeCalls.length}건)
        </h2>
        
        {activeCalls.length === 0 ? (
          <div className="bg-white p-6 rounded-lg shadow text-gray-500">
            진행 중인 통화가 없습니다.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {activeCalls.map((call) => (
              <div key={call.call_id} className="bg-white p-6 rounded-lg shadow">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <p className="text-sm text-gray-600">통화 ID</p>
                    <p className="font-mono text-xs">{call.call_id}</p>
                  </div>
                  <span className="px-2 py-1 bg-green-100 text-green-700 rounded text-sm">
                    {call.status}
                  </span>
                </div>

                <div className="space-y-2 mb-4">
                  <div>
                    <p className="text-sm text-gray-600">발신</p>
                    <p className="font-semibold">{call.caller_number}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-600">착신 (테넌트)</p>
                    <p className="font-semibold">
                      {call.callee_number}
                      <span className="text-gray-500 text-sm ml-2">
                        ({TENANT_PHONE_MAP[call.callee_number]})
                      </span>
                    </p>
                  </div>
                </div>

                <button
                  onClick={() => handleTransfer(call)}
                  className="w-full bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600"
                >
                  착신 테넌트로 전환
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* HITL 요청 섹션 */}
      <section>
        <h2 className="text-2xl font-semibold mb-4">
          HITL 요청 ({hitlRequests.length}건)
        </h2>
        
        {hitlRequests.length === 0 ? (
          <div className="bg-white p-6 rounded-lg shadow text-gray-500">
            대기 중인 HITL 요청이 없습니다.
          </div>
        ) : (
          <div className="space-y-4">
            {hitlRequests.map((hitl) => (
              <div key={hitl.call_id} className="bg-white p-6 rounded-lg shadow">
                <div className="mb-4">
                  <p className="text-sm text-gray-600">질문</p>
                  <p className="font-semibold">{hitl.question}</p>
                </div>
                
                <textarea
                  placeholder="답변을 입력하세요..."
                  className="w-full border rounded p-2 mb-2"
                  rows={3}
                  id={`hitl-${hitl.call_id}`}
                />
                
                <button
                  onClick={() => {
                    const textarea = document.getElementById(`hitl-${hitl.call_id}`) as HTMLTextAreaElement;
                    handleHITLResponse(hitl, textarea.value);
                  }}
                  className="bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600"
                >
                  답변 전송
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
```

---

### Option 2: 컴포넌트 분리 (확장성 고려)

**파일 구조**:
```
frontend/
├─ app/
│  └─ dashboard/
│     └─ page.tsx  (메인 레이아웃)
│
└─ components/
   ├─ ActiveCallsPanel.tsx  (실시간 통화)
   ├─ HITLRequestsPanel.tsx  (HITL 요청)
   └─ SystemStatusPanel.tsx  (선택)
```

**메인 페이지**: `frontend/app/dashboard/page.tsx`

```typescript
"use client";

import ActiveCallsPanel from "@/components/ActiveCallsPanel";
import HITLRequestsPanel from "@/components/HITLRequestsPanel";
import { useWebSocket } from "@/hooks/useWebSocket";

export default function Dashboard() {
  const { socket, activeCalls, hitlRequests } = useWebSocket();

  return (
    <div className="min-h-screen bg-gray-100 p-6">
      <h1 className="text-3xl font-bold mb-8">운영자 대시보드</h1>
      
      <div className="space-y-8">
        <ActiveCallsPanel calls={activeCalls} socket={socket} />
        <HITLRequestsPanel requests={hitlRequests} socket={socket} />
      </div>
    </div>
  );
}
```

**WebSocket Hook**: `frontend/hooks/useWebSocket.ts`

```typescript
import { useEffect, useState } from "react";
import { io, Socket } from "socket.io-client";

export function useWebSocket() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState([]);
  const [hitlRequests, setHitlRequests] = useState([]);

  useEffect(() => {
    const newSocket = io("http://localhost:8001");
    setSocket(newSocket);

    newSocket.on("call_started", (data) => {
      setActiveCalls((prev) => [...prev, data]);
    });

    newSocket.on("call_ended", (data) => {
      setActiveCalls((prev) => prev.filter(c => c.call_id !== data.call_id));
    });

    newSocket.on("hitl_requested", (data) => {
      setHitlRequests((prev) => [...prev, data]);
    });

    newSocket.on("hitl_resolved", (data) => {
      setHitlRequests((prev) => prev.filter(h => h.call_id !== data.call_id));
    });

    return () => {
      newSocket.close();
    };
  }, []);

  return { socket, activeCalls, hitlRequests };
}
```

**실시간 통화 패널**: `frontend/components/ActiveCallsPanel.tsx`

```typescript
import { Socket } from "socket.io-client";

interface ActiveCall {
  call_id: string;
  caller_number: string;
  callee_number: string;
  status: string;
}

const TENANT_PHONE_MAP: Record<string, string> = {
  "1003": "02-1234-5678",
  "1004": "02-8765-4321",
};

interface Props {
  calls: ActiveCall[];
  socket: Socket | null;
}

export default function ActiveCallsPanel({ calls, socket }: Props) {
  const handleTransfer = (call: ActiveCall) => {
    if (!socket) return;
    
    const targetNumber = TENANT_PHONE_MAP[call.callee_number];
    if (!targetNumber) {
      alert("테넌트 전화번호가 등록되지 않았습니다.");
      return;
    }

    socket.emit("manual_transfer_request", {
      call_id: call.call_id,
      operator_id: "operator_001",
      target_number: targetNumber,
    }, (response: any) => {
      alert(response.success ? "호 전환 시작" : `실패: ${response.message}`);
    });
  };

  return (
    <section>
      <h2 className="text-2xl font-semibold mb-4">
        실시간 통화 ({calls.length}건)
      </h2>
      
      {calls.length === 0 ? (
        <div className="bg-white p-6 rounded-lg shadow text-gray-500">
          진행 중인 통화가 없습니다.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {calls.map((call) => (
            <div key={call.call_id} className="bg-white p-6 rounded-lg shadow">
              {/* 통화 정보 표시 */}
              <div className="mb-4">
                <p className="text-sm text-gray-600">발신: {call.caller_number}</p>
                <p className="text-sm text-gray-600">
                  착신: {call.callee_number} ({TENANT_PHONE_MAP[call.callee_number]})
                </p>
              </div>
              
              <button
                onClick={() => handleTransfer(call)}
                className="w-full bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600"
              >
                착신 테넌트로 전환
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
```

---

## 설계 비교

### ❌ 기존 설계 (별도 페이지)

**장점**:
- 기능별 분리가 명확
- 각 페이지가 단순함

**단점**:
- 페이지 전환 필요 (UX 저하)
- 중복된 WebSocket 연결
- 운영자가 여러 화면을 봐야 함

### ✅ 수정 설계 (Dashboard 통합)

**장점**:
- **단일 화면에서 모든 정보 확인** ✨
- WebSocket 연결 1개로 통합
- 실시간 통화와 HITL을 동시에 모니터링
- 운영자 경험 향상

**단점**:
- 한 페이지가 복잡해질 수 있음
  → **해결책**: 컴포넌트로 분리 (Option 2)

---

## 권장 구현 방안

### Phase 1: 단순 통합 (Option 1)
- Dashboard 단일 파일로 구현
- 빠른 프로토타이핑
- 기능 검증

### Phase 2: 컴포넌트 분리 (Option 2)
- 확장성 고려
- 재사용 가능한 컴포넌트
- 유지보수 용이

---

## 결론

**별도 페이지 (LiveCallMonitor)가 아닌 Dashboard 통합이 올바른 설계입니다.**

이유:
1. ✅ 운영자는 **하나의 화면**에서 모든 것을 모니터링해야 함
2. ✅ 실시간 통화와 HITL은 **동시에 발생**할 수 있음
3. ✅ 페이지 전환 없이 **즉시 대응** 가능
4. ✅ WebSocket 연결 1개로 **리소스 절약**

**Frontend 구현**: `/dashboard` 페이지 하나면 충분합니다!

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-17
