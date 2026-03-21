# 호 전환 로직 점검 보고서

**점검일**: 2026-03-17  
**요청**: 호 전환 로직 검토  
**상태**: 🔴 부분 구현됨 (누락 사항 다수)

---

## 사용자 요구사항

### 1. Frontend 지식베이스에서 호전환 번호 등록
- 지식베이스에 부서별 전화번호 등록
- AI가 사용자 요청 시 해당 번호로 호 전환

### 2. Frontend 실시간 모니터링에서 수동 전환
- 상담원이 실시간 통화를 보면서 버튼 클릭
- 자신의 테넌트 번호로 호 전환

---

## 시스템 아키텍처 확인

### ✅ B2BUA (Back-to-Back User Agent) 구조

로그 확인 결과:
```
Line 45: "SIP B2BUA endpoint initialized (signaling + media relay)"
Line 38: "transfer_manager_initialized"
Line 48: "transfer_manager_initialized" (announcement_mode: template, ring_timeout: 30)
Line 93: "TransferManager configured"
Line 94: "✅ [Transfer] TransferManager connected to AI Orchestrator"
```

### B2BUA에서 호 전환 방식

**REFER 메서드 불필요!**

B2BUA 아키텍처에서는:
1. **현재 통화**: 발신자 ↔ B2BUA ↔ AI Voicebot
2. **호 전환 시**: 
   - B2BUA가 AI Voicebot 쪽 레그를 BYE로 종료
   - B2BUA가 대상 번호로 새 INVITE 발신
   - 발신자 ↔ B2BUA ↔ 대상 번호로 재연결

**즉, REFER 대신 "BYE + 새 INVITE" 방식 사용**

---

## 현재 구현 상태

### ✅ 구현된 부분

#### 1. WebSocket 이벤트 (완료)
`src/websocket/server.py` (Lines 198-315)

```python
async def emit_transfer_initiated(call_id, target_number, department)
async def emit_transfer_ringing(call_id, target_number)
async def emit_transfer_success(call_id, target_number, department)
async def emit_transfer_failed(call_id, target_number, reason)
```

✅ Frontend에 호 전환 상태 알림 준비 완료

#### 2. RAGProcessor 호 전환 로직 (부분 구현)
`src/ai_voicebot/pipecat/processors/rag_processor.py` (Lines 494-619)

**구현된 것**:
- intent="transfer" 감지
- ContactKnowledgeExtractor로 연락처 검색 (호출만 있음)
- LLM으로 안내 멘트 생성
- TTS로 안내 멘트 출력
- WebSocket 이벤트 발송
- `src.call_transfer.initiate_call_transfer()` 호출

**로직 흐름**:
```python
if intent == "transfer":
    # 1. 연락처 검색
    contact = await contact_extractor.search_contact(user_text, tenant_id)
    
    # 2. 안내 멘트 생성 및 TTS
    announcement = await llm.generate_simple(prompt)
    await push_frame(TextFrame(text=announcement))
    
    # 3. WebSocket 이벤트
    await emit_transfer_initiated(call_id, target_number, department)
    
    # 4. 실제 호 전환
    transfer_success = await initiate_call_transfer(...)
```

#### 3. TransferManager 초기화 (완료)
로그에서 확인:
```
Line 38: transfer_manager_initialized
Line 48: transfer_manager_initialized (announcement_mode: template, ring_timeout: 30)
Line 94: ✅ [Transfer] TransferManager connected to AI Orchestrator
```

---

### 🔴 미구현 부분 (Critical)

#### 1. ContactKnowledgeExtractor 클래스 없음
`src/ai_voicebot/pipecat/processors/rag_processor.py` Line 499:
```python
from src.ai_voicebot.knowledge import ContactKnowledgeExtractor
```

**상태**: ❌ 모듈 존재하지 않음
- `src/ai_voicebot/knowledge/` 폴더에 해당 파일 없음
- import 시 `ModuleNotFoundError` 발생 예상

**필요 기능**:
```python
class ContactKnowledgeExtractor:
    async def search_contact(self, query: str, tenant_id: str) -> Optional[Dict]:
        """
        ChromaDB에서 category="contact"인 지식 검색
        
        Returns:
            {
                "department": "영업팀",
                "phone_number": "010-1234-5678",
                "name": "김철수"
            }
        """
```

#### 2. call_transfer 모듈 없음
`src/ai_voicebot/pipecat/processors/rag_processor.py` Line 557:
```python
from src.call_transfer import initiate_call_transfer
```

**상태**: ❌ 모듈 존재하지 않음
- `src/call_transfer.py` 파일 없음
- import 시 `ModuleNotFoundError` 발생 예상

**필요 기능**:
```python
async def initiate_call_transfer(
    call_id: str,
    target_number: str,
    department: str,
    phone_display: str,
    user_request_text: str
) -> bool:
    """
    B2BUA를 통한 호 전환 실행
    
    1. AI Voicebot 레그 종료 (BYE)
    2. 대상 번호로 새 INVITE 발신
    3. 발신자와 대상 연결
    
    Returns:
        True: 호 전환 성공
        False: 호 전환 실패
    """
```

#### 3. intents 모듈의 transfer 함수 없음
`src/ai_voicebot/pipecat/processors/rag_processor.py` Line 514:
```python
from ..intents import build_transfer_announcement_prompt
```

**상태**: ⚠️ 확인 필요
- `src/ai_voicebot/pipecat/intents.py` 또는
- `src/ai_voicebot/intents.py` 존재 여부 확인 필요

**필요 기능**:
```python
def build_transfer_announcement_prompt(department: str, phone_number: str) -> str:
    """
    호 전환 안내 멘트 생성용 LLM 프롬프트
    
    예: "영업팀으로 연결해 드리겠습니다. 잠시만 기다려 주세요."
    """
```

#### 4. 지식베이스 category="contact" 지원 없음
`src/api/knowledge_router.py` 확인 결과:

**현재 VALID_CATEGORIES**:
- greeting_phase1, greeting_phase2
- farewell_phase1, farewell_phase2
- capability, faq, question

**필요**: `contact` category 추가
```python
VALID_CATEGORIES = {
    ...,
    "contact",  # 호 전환용 연락처
}
```

**KnowledgeCreateRequest 확장 필요**:
```python
class KnowledgeCreateRequest(BaseModel):
    text: str  # 부서명/담당자명
    category: str  # "contact"
    phone_number: Optional[str] = None  # 전화번호 (contact 시 필수)
    department: Optional[str] = None  # 부서명
    name: Optional[str] = None  # 담당자명
```

#### 5. Frontend 컴포넌트 모두 삭제됨
Git status 확인 결과:
```
D frontend/components/HITLDialog.tsx
D frontend/components/LiveCallMonitor.tsx
D frontend/components/OperatorStatusToggle.tsx
D frontend/hooks/useWebSocket.ts
```

**필요 컴포넌트**:
1. `ContactKnowledgeForm.tsx` - 연락처 등록 UI
2. `LiveCallMonitor.tsx` - 실시간 통화 모니터링 + 전환 버튼
3. `TransferButton.tsx` - 호 전환 버튼

---

## 구현 우선순위

### Priority 1: Backend 핵심 모듈 (필수)

#### 1.1 ContactKnowledgeExtractor 구현
**파일**: `src/ai_voicebot/knowledge/contact_extractor.py`

```python
"""
연락처 지식 검색 모듈

지식베이스(ChromaDB)에서 category="contact"인 항목을 검색하여
호 전환에 필요한 전화번호 반환
"""

from typing import Optional, Dict
import structlog

logger = structlog.get_logger(__name__)


class ContactKnowledgeExtractor:
    """연락처 지식 추출기"""
    
    def __init__(self, vector_db=None, embedder=None):
        self.vector_db = vector_db
        self.embedder = embedder
    
    async def search_contact(
        self, 
        query: str, 
        tenant_id: str
    ) -> Optional[Dict[str, str]]:
        """
        연락처 검색
        
        Args:
            query: 사용자 질문 (예: "영업팀 연결해줘")
            tenant_id: 테넌트 ID (owner)
        
        Returns:
            {
                "department": "영업팀",
                "phone_number": "010-1234-5678",
                "name": "김철수"
            }
            또는 None (찾지 못한 경우)
        """
        if not self.vector_db or not self.embedder:
            logger.warning("contact_search_skip_no_deps")
            return None
        
        try:
            # 1. 쿼리 임베딩
            query_embedding = self.embedder.embed_text(query)
            
            # 2. ChromaDB 검색
            results = self.vector_db.collection.query(
                query_embeddings=[query_embedding],
                n_results=1,
                where={
                    "$and": [
                        {"owner": tenant_id},
                        {"category": "contact"}
                    ]
                },
                include=["documents", "metadatas", "distances"]
            )
            
            if not results or not results['ids'] or len(results['ids'][0]) == 0:
                logger.info("contact_search_no_results",
                           query=query[:50],
                           tenant_id=tenant_id)
                return None
            
            # 3. 메타데이터에서 연락처 정보 추출
            metadata = results['metadatas'][0][0]
            contact = {
                "department": metadata.get("department", ""),
                "phone_number": metadata.get("phone_number", ""),
                "name": metadata.get("name", ""),
            }
            
            if not contact["phone_number"]:
                logger.warning("contact_search_no_phone",
                              department=contact["department"])
                return None
            
            logger.info("contact_search_found",
                       department=contact["department"],
                       phone=contact["phone_number"][:8] + "***")
            
            return contact
            
        except Exception as e:
            logger.error("contact_search_error", error=str(e), exc_info=True)
            return None
```

**__init__.py 수정**:
`src/ai_voicebot/knowledge/__init__.py`:
```python
from .contact_extractor import ContactKnowledgeExtractor

__all__ = ["ContactKnowledgeExtractor"]
```

#### 1.2 call_transfer 모듈 구현
**파일**: `src/call_transfer.py`

```python
"""
호 전환 모듈

B2BUA를 통한 SIP 호 전환 실행
"""

import structlog
from typing import Optional

logger = structlog.get_logger(__name__)


async def initiate_call_transfer(
    call_id: str,
    target_number: str,
    department: str,
    phone_display: Optional[str] = None,
    user_request_text: Optional[str] = None
) -> bool:
    """
    B2BUA 호 전환 실행
    
    Args:
        call_id: 통화 ID
        target_number: 대상 전화번호
        department: 부서명
        phone_display: 표시용 전화번호
        user_request_text: 사용자 요청 원문
    
    Returns:
        True: 호 전환 성공
        False: 호 전환 실패
    
    B2BUA 동작:
        1. AI Voicebot 레그 종료 (BYE)
        2. 대상 번호로 새 INVITE 발신
        3. 발신자와 대상 연결
    """
    logger.info("call_transfer_initiated",
               call_id=call_id,
               target=target_number,
               department=department)
    
    try:
        # CallManager 가져오기
        from src.websocket.server import _call_manager
        
        if not _call_manager:
            logger.error("call_transfer_no_manager", call_id=call_id)
            return False
        
        # TransferManager 가져오기
        transfer_manager = getattr(_call_manager, 'transfer_manager', None)
        if not transfer_manager:
            logger.error("call_transfer_no_transfer_manager", call_id=call_id)
            return False
        
        # 호 전환 실행
        success = await transfer_manager.initiate_transfer(
            call_id=call_id,
            target_number=target_number,
            department=department
        )
        
        if success:
            logger.info("call_transfer_success",
                       call_id=call_id,
                       target=target_number)
            
            # WebSocket 이벤트 발송
            try:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_transfer_success(
                    call_id=call_id,
                    target_number=target_number,
                    department=department
                )
            except Exception as e:
                logger.warning("transfer_success_event_failed", error=str(e))
        else:
            logger.warning("call_transfer_failed",
                          call_id=call_id,
                          target=target_number)
            
            # WebSocket 이벤트 발송
            try:
                from src.websocket import manager as ws_manager
                await ws_manager.emit_transfer_failed(
                    call_id=call_id,
                    target_number=target_number,
                    reason="transfer_manager_rejected"
                )
            except Exception as e:
                logger.warning("transfer_failed_event_failed", error=str(e))
        
        return success
        
    except Exception as e:
        logger.error("call_transfer_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        
        # WebSocket 이벤트 발송
        try:
            from src.websocket import manager as ws_manager
            await ws_manager.emit_transfer_failed(
                call_id=call_id,
                target_number=target_number,
                reason=str(e)
            )
        except Exception:
            pass
        
        return False
```

#### 1.3 intents 모듈 구현
**파일**: `src/ai_voicebot/pipecat/intents.py` (또는 `src/ai_voicebot/intents.py`)

```python
"""
Intent 관련 유틸리티 함수
"""


def build_transfer_announcement_prompt(department: str, phone_number: str) -> str:
    """
    호 전환 안내 멘트 생성용 LLM 프롬프트
    
    Args:
        department: 부서명
        phone_number: 전화번호
    
    Returns:
        LLM 프롬프트
    """
    return f"""다음 정보로 호 전환 안내 멘트를 작성해주세요:

부서: {department}
전화번호: {phone_number}

요구사항:
1. 친절하고 자연스러운 톤
2. 1-2문장으로 간결하게
3. "연결해 드리겠습니다" 또는 "전환해 드리겠습니다" 표현 사용
4. 잠시 기다려달라는 안내 포함

안내 멘트:"""
```

### Priority 2: 지식베이스 확장

#### 2.1 contact category 추가
**파일**: `src/ai_voicebot/knowledge/knowledge_service.py`

```python
VALID_CATEGORIES = {
    "greeting_phase1", "greeting_phase2",
    "farewell_phase1", "farewell_phase2",
    "capability", "faq", "question",
    "contact",  # 추가
}
```

#### 2.2 KnowledgeCreateRequest 확장
**파일**: `src/api/knowledge_router.py`

```python
class KnowledgeCreateRequest(BaseModel):
    text: str
    owner: str
    category: str
    doc_type: Optional[str] = "knowledge"
    answer: Optional[str] = None
    source: Optional[str] = "api"
    call_id: Optional[str] = None
    # contact category용 추가 필드
    phone_number: Optional[str] = Field(None, description="전화번호 (contact 시 필수)")
    department: Optional[str] = Field(None, description="부서명")
    name: Optional[str] = Field(None, description="담당자명")
```

**POST /api/knowledge 핸들러 수정**:
```python
@router.post("/knowledge")
async def post_knowledge(...):
    ...
    # category="contact" 유효성 검증
    if category == "contact":
        if not body.phone_number:
            raise HTTPException(
                status_code=400,
                detail="contact category는 phone_number 필수"
            )
    
    # metadata에 전화번호 포함
    result = add_knowledge(
        ...,
        phone_number=body.phone_number,
        department=body.department,
        name=body.name,
    )
```

#### 2.3 add_knowledge 함수 수정
**파일**: `src/ai_voicebot/knowledge/knowledge_service.py`

```python
def add_knowledge(
    vector_db,
    embedder,
    text: str,
    owner: str,
    category: str,
    doc_type: str = "knowledge",
    source: str = "api",
    answer: Optional[str] = None,
    call_id: Optional[str] = None,
    # contact용 추가
    phone_number: Optional[str] = None,
    department: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    ...
    metadata = {
        "owner": owner,
        "category": category,
        "doc_type": doc_type,
        "source": source,
        "created_at": datetime.now().isoformat(),
    }
    
    # contact category 추가 메타데이터
    if category == "contact":
        if phone_number:
            metadata["phone_number"] = phone_number
        if department:
            metadata["department"] = department
        if name:
            metadata["name"] = name
    ...
```

### Priority 3: Frontend 구현

#### 3.1 연락처 등록 UI
**파일**: `frontend/app/contacts/page.tsx`

```typescript
"use client";

import { useState } from "react";

export default function ContactsPage() {
  const [formData, setFormData] = useState({
    text: "",
    owner: "1004",
    category: "contact",
    phone_number: "",
    department: "",
    name: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    const response = await fetch("http://localhost:8000/api/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formData),
    });
    
    if (response.ok) {
      alert("연락처가 등록되었습니다.");
      // 폼 초기화
    } else {
      alert("등록 실패");
    }
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">호 전환 연락처 등록</h1>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label>부서명/담당자</label>
          <input
            type="text"
            value={formData.text}
            onChange={(e) => setFormData({...formData, text: e.target.value})}
            placeholder="예: 영업팀"
            className="border p-2 w-full"
            required
          />
        </div>
        
        <div>
          <label>전화번호</label>
          <input
            type="text"
            value={formData.phone_number}
            onChange={(e) => setFormData({...formData, phone_number: e.target.value})}
            placeholder="010-1234-5678"
            className="border p-2 w-full"
            required
          />
        </div>
        
        <div>
          <label>부서명</label>
          <input
            type="text"
            value={formData.department}
            onChange={(e) => setFormData({...formData, department: e.target.value})}
            placeholder="영업팀"
            className="border p-2 w-full"
          />
        </div>
        
        <div>
          <label>담당자명</label>
          <input
            type="text"
            value={formData.name}
            onChange={(e) => setFormData({...formData, name: e.target.value})}
            placeholder="김철수"
            className="border p-2 w-full"
          />
        </div>
        
        <button type="submit" className="bg-blue-500 text-white px-4 py-2 rounded">
          등록
        </button>
      </form>
    </div>
  );
}
```

#### 3.2 실시간 모니터링 + 전환 버튼
**파일**: `frontend/components/LiveCallMonitor.tsx`

```typescript
"use client";

import { useEffect, useState } from "react";
import { io, Socket } from "socket.io-client";

interface Call {
  call_id: string;
  caller_number: string;
  callee_number: string;
  status: string;
}

export default function LiveCallMonitor() {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [activeCalls, setActiveCalls] = useState<Call[]>([]);

  useEffect(() => {
    const newSocket = io("http://localhost:8001");
    setSocket(newSocket);

    newSocket.on("call_started", (data) => {
      setActiveCalls((prev) => [...prev, data]);
    });

    newSocket.on("call_ended", (data) => {
      setActiveCalls((prev) => prev.filter((c) => c.call_id !== data.call_id));
    });

    return () => {
      newSocket.close();
    };
  }, []);

  const handleTransfer = async (callId: string) => {
    if (!socket) return;

    // 수동 호 전환: 상담원 자신의 번호로 전환
    socket.emit("manual_transfer_request", {
      call_id: callId,
      operator_id: "operator_001",  // 실제로는 로그인 정보에서 가져옴
      target_number: "010-9999-8888",  // 상담원 번호
    });
  };

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">실시간 통화 모니터링</h1>
      
      <div className="space-y-4">
        {activeCalls.map((call) => (
          <div key={call.call_id} className="border p-4 rounded">
            <div>통화 ID: {call.call_id}</div>
            <div>발신: {call.caller_number}</div>
            <div>착신: {call.callee_number}</div>
            <div>상태: {call.status}</div>
            
            <button
              onClick={() => handleTransfer(call.call_id)}
              className="mt-2 bg-green-500 text-white px-4 py-2 rounded hover:bg-green-600"
            >
              내게 전환
            </button>
          </div>
        ))}
        
        {activeCalls.length === 0 && (
          <p className="text-gray-500">진행 중인 통화가 없습니다.</p>
        )}
      </div>
    </div>
  );
}
```

#### 3.3 WebSocket manual_transfer_request 핸들러
**파일**: `src/websocket/server.py`

```python
@sio.event
async def manual_transfer_request(sid: str, data: dict) -> dict:
    """
    상담원 수동 호 전환 요청
    
    Args:
        data: {
            "call_id": str,
            "operator_id": str,
            "target_number": str  # 상담원 자신의 번호
        }
    """
    call_id = data.get("call_id")
    operator_id = data.get("operator_id")
    target_number = data.get("target_number")
    
    if not call_id or not target_number:
        return {"success": False, "message": "call_id 및 target_number 필수"}
    
    try:
        from src.call_transfer import initiate_call_transfer
        
        success = await initiate_call_transfer(
            call_id=call_id,
            target_number=target_number,
            department=f"상담원 {operator_id}",
            user_request_text="수동 전환"
        )
        
        if success:
            logger.info("manual_transfer_success",
                       call_id=call_id,
                       operator=operator_id,
                       target=target_number)
            return {
                "success": True,
                "message": "호 전환이 시작되었습니다."
            }
        else:
            logger.warning("manual_transfer_failed",
                          call_id=call_id)
            return {
                "success": False,
                "message": "호 전환 실패"
            }
            
    except Exception as e:
        logger.error("manual_transfer_error",
                    call_id=call_id,
                    error=str(e),
                    exc_info=True)
        return {
            "success": False,
            "message": f"오류: {str(e)}"
        }
```

---

## 요약

### ✅ 이미 구현된 것
1. WebSocket 전환 이벤트 (4개)
2. TransferManager 초기화
3. RAGProcessor에 전환 로직 골격

### 🔴 구현 필요 (Critical)
1. **ContactKnowledgeExtractor** 클래스
2. **call_transfer** 모듈
3. **intents** 모듈의 transfer 함수
4. **contact category** 지원
5. **Frontend** 전체 (연락처 등록 + 실시간 모니터링)

### 🎯 REFER 불필요!
- B2BUA 아키텍처이므로 "BYE + 새 INVITE" 방식 사용
- TransferManager가 이미 구현되어 있음 (확인 필요)

---

**작성자**: AI Assistant  
**최종 업데이트**: 2026-03-17
