# 통화 이력 대화 내용 표시 오류 분석

**작성일**: 2026-03-11  
**Call ID**: `0IBsHSliVK`  
**상태**: 긴급 수정 필요 🔴  

---

## 🚨 핵심 문제

**Frontend 통화 이력 페이지에서 대화 내용이 표시되지 않음**

### 현상

사용자가 이미지에서 제공한 통화 이력 화면에서:
- 통화 ID: `0IBsHSliVK`
- 상태: "대화 내용이 없습니다" 표시
- 실제로는 transcript.txt에 대화 내용 존재

---

## 📋 확인된 사실

### 1. ✅ Transcript 파일 존재 확인

**파일 경로**: `sip-pbx/recordings/20260310_174029_1003_to_1004/transcript.txt`

**실제 내용** (10줄):
```
착신자: 안녕하세요 기 상 청 ai 통합 비 서 입니다 무엇을 도와 드릴 까요...
발신자: 오늘의
착신자: 수 있어요 어떤 것이 궁금하신 가요 실시간 오늘의 날씨 정보...
발신자: 날씨
착신자: w
발신자: 를 알려
착신자: w
발신자: 주세요
착신자: . k m a . 고 . k r 나 날씨 누 리 앱 에서 확인 하실 수...
발신자: 오늘의 날씨 를 알려 주세요 들 리 니 오 긴 키 데 스카
```

### 2. ✅ Metadata 파일 확인

**파일 경로**: `sip-pbx/recordings/20260310_174029_1003_to_1004/metadata.json`

**주요 내용**:
```json
{
  "call_id": "0IBsHSliVK",
  "caller_id": "1003",
  "callee_id": "1004",
  "start_time": "2026-03-10T17:40:29.775360",
  "end_time": "2026-03-10T17:41:43.600858",
  "duration": 73.825498,
  "has_transcript": true,  ← ✅ True로 설정됨
  "files": {
    "transcript": "20260310_174029_1003_to_1004\\transcript.txt"
  }
}
```

### 3. ❌ Frontend에서 대화 내용 미표시

**Frontend 코드** (`sip-pbx/frontend/app/call-history/page.tsx`):

```typescript
// Line 361-404: 대화 내용 렌더링 로직
const messages = transcripts[row.call_id] || row.transcripts || [];

if (messages.length > 0) {
  // TranscriptMessage[] 형식으로 표시
} else if (row.stt_transcript || row.transcript) {
  // 텍스트 형식으로 표시
} else {
  // ❌ "대화 내용이 없습니다" 표시
}
```

**문제점**:
- `row.transcripts`가 비어있음
- `row.stt_transcript` 또는 `row.transcript`가 없음
- API가 transcript 데이터를 반환하지 않음

### 4. ❌ API 백엔드 누락

**확인 결과**:
- `sip-pbx/src/api/` 디렉토리에 Python 파일 없음
- `/api/call-history` 엔드포인트 구현 누락
- `/api/calls/{call_id}/transcript` 엔드포인트 구현 누락

---

## 🔍 근본 원인

### 1. API 백엔드가 삭제되었거나 구현되지 않음

**필요한 엔드포인트**:

#### A. GET /api/call-history
```python
# 통화 이력 목록 반환
# 각 항목에 transcript 필드 포함 필요
{
  "items": [
    {
      "call_id": "0IBsHSliVK",
      "transcript": "...",  # 또는
      "transcripts": [      # TranscriptMessage[] 형식
        {"role": "assistant", "content": "안녕하세요..."},
        {"role": "user", "content": "오늘의"}
      ]
    }
  ]
}
```

#### B. GET /api/calls/{call_id}/transcript
```python
# 특정 통화의 transcript 반환
{
  "messages": [  # 또는 "transcripts"
    {"role": "assistant", "content": "안녕하세요..."},
    {"role": "user", "content": "오늘의"}
  ]
}
```

### 2. Transcript 파일 파싱 로직 누락

**현재 상태**:
- transcript.txt 파일은 존재
- 파일 내용: "착신자: ..." / "발신자: ..." 형식
- 이를 `TranscriptMessage[]` 형식으로 변환하는 로직 필요

---

## ✅ 해결 방안

### Step 1: API 백엔드 구현

#### A. transcript 읽기 유틸리티 함수 작성

```python
# sip-pbx/src/api/utils/transcript_parser.py

import os
from pathlib import Path
from typing import List, Dict, Optional

def parse_transcript_file(transcript_path: str) -> List[Dict[str, str]]:
    """
    transcript.txt 파일을 파싱하여 TranscriptMessage 형식으로 변환
    
    입력 형식:
        착신자: 안녕하세요...
        발신자: 오늘의
    
    출력 형식:
        [
            {"role": "assistant", "content": "안녕하세요..."},
            {"role": "user", "content": "오늘의"}
        ]
    """
    messages = []
    
    if not os.path.exists(transcript_path):
        return messages
    
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith('착신자:'):
                    # AI (assistant)
                    content = line.replace('착신자:', '').strip()
                    messages.append({
                        "role": "assistant",
                        "content": content
                    })
                elif line.startswith('발신자:'):
                    # User
                    content = line.replace('발신자:', '').strip()
                    messages.append({
                        "role": "user",
                        "content": content
                    })
    except Exception as e:
        print(f"Error parsing transcript: {e}")
    
    return messages

def get_transcript_for_call(call_id: str, recordings_dir: str = "recordings") -> Optional[List[Dict[str, str]]]:
    """
    call_id로 transcript 파일을 찾아 파싱
    """
    recordings_path = Path(recordings_dir)
    
    # recordings/ 하위의 모든 디렉토리 검색
    for dir_path in recordings_path.glob("*"):
        if not dir_path.is_dir():
            continue
        
        # metadata.json에서 call_id 확인
        metadata_path = dir_path / "metadata.json"
        if metadata_path.exists():
            import json
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    if metadata.get("call_id") == call_id:
                        # transcript.txt 파일 찾기
                        transcript_path = dir_path / "transcript.txt"
                        if transcript_path.exists():
                            return parse_transcript_file(str(transcript_path))
            except Exception:
                continue
    
    return None
```

#### B. API 엔드포인트 구현

```python
# sip-pbx/src/api/routers/calls.py

from fastapi import APIRouter, HTTPException
from typing import List, Dict
from ..utils.transcript_parser import get_transcript_for_call

router = APIRouter(prefix="/api/calls", tags=["calls"])

@router.get("/{call_id}/transcript")
async def get_call_transcript(call_id: str):
    """
    특정 통화의 transcript 반환
    """
    messages = get_transcript_for_call(call_id)
    
    if messages is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    return {
        "call_id": call_id,
        "messages": messages,
        "count": len(messages)
    }
```

```python
# sip-pbx/src/api/routers/call_history.py

from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from ..utils.transcript_parser import get_transcript_for_call
import os
import json
from pathlib import Path

router = APIRouter(prefix="/api/call-history", tags=["call-history"])

@router.get("")
async def get_call_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    callee: Optional[str] = None
):
    """
    통화 이력 목록 반환 (transcript 포함)
    """
    recordings_path = Path("recordings")
    items = []
    
    # recordings/ 하위의 모든 디렉토리 검색
    for dir_path in sorted(recordings_path.glob("*"), reverse=True):
        if not dir_path.is_dir():
            continue
        
        # metadata.json 읽기
        metadata_path = dir_path / "metadata.json"
        if not metadata_path.exists():
            continue
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # callee 필터링
            if callee and metadata.get("callee_id") != callee:
                continue
            
            # transcript 파싱
            transcripts = get_transcript_for_call(metadata.get("call_id", ""))
            
            item = {
                "call_id": metadata.get("call_id", ""),
                "caller_id": metadata.get("caller_id", ""),
                "callee_id": metadata.get("callee_id", ""),
                "start_time": metadata.get("start_time", ""),
                "end_time": metadata.get("end_time"),
                "has_recording": True,
                "has_transcript": metadata.get("has_transcript", False),
                "is_ai_handled": False,  # TODO: AI 응대 여부 판단
                "transcripts": transcripts or [],  # ✅ transcript 포함
                "hitl_status": None,
                "user_question": None,
                "ai_confidence": None,
                "timestamp": metadata.get("start_time", "")
            }
            
            items.append(item)
        except Exception as e:
            print(f"Error reading metadata: {e}")
            continue
    
    # 페이지네이션
    total = len(items)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated_items = items[start_idx:end_idx]
    
    return {
        "items": paginated_items,
        "total": total,
        "page": page,
        "limit": limit
    }
```

#### C. main.py에 라우터 등록

```python
# sip-pbx/src/api/main.py

from fastapi import FastAPI
from .routers import calls, call_history

app = FastAPI(title="SIP PBX API")

# 라우터 등록
app.include_router(calls.router)
app.include_router(call_history.router)

@app.get("/")
async def root():
    return {"message": "SIP PBX API"}
```

---

### Step 2: 테스트

#### A. API 서버 재시작

```bash
cd sip-pbx
python -m src.api.main
```

#### B. Transcript API 테스트

```bash
# 특정 통화의 transcript 조회
curl http://localhost:8000/api/calls/0IBsHSliVK/transcript

# 예상 응답:
{
  "call_id": "0IBsHSliVK",
  "messages": [
    {"role": "assistant", "content": "안녕하세요 기 상 청 ai 통합 비 서 입니다..."},
    {"role": "user", "content": "오늘의"},
    {"role": "assistant", "content": "수 있어요 어떤 것이 궁금하신 가요..."},
    ...
  ],
  "count": 10
}
```

#### C. Call History API 테스트

```bash
# 통화 이력 목록 조회
curl http://localhost:8000/api/call-history?page=1&limit=20

# 예상 응답:
{
  "items": [
    {
      "call_id": "0IBsHSliVK",
      "transcripts": [
        {"role": "assistant", "content": "안녕하세요..."},
        ...
      ]
    }
  ],
  "total": 1
}
```

#### D. Frontend 테스트

1. Frontend 접속: http://localhost:3000/call-history
2. 통화 행 클릭 (roll down)
3. ✅ 대화 내용 표시 확인

---

## 📊 예상 결과

### Before (현재)

```
통화 이력
┌─────────────────────────────────────────────┐
│ 통화 ID: 0IBsHSliVK                         │
│ ▼ 대화 내용                                 │
│   대화 내용이 없습니다                       │
│   (call_id: 0IBsHSliVK, has_recording: Yes) │
└─────────────────────────────────────────────┘
```

### After (수정 후)

```
통화 이력
┌─────────────────────────────────────────────┐
│ 통화 ID: 0IBsHSliVK                         │
│ ▼ 대화 내용                                 │
│                                             │
│   🤖 AI                                     │
│   안녕하세요 기 상 청 ai 통합 비 서 입니다  │
│   무엇을 도와 드릴 까요...                   │
│                                             │
│   👤 사용자                                 │
│   오늘의                                    │
│                                             │
│   🤖 AI                                     │
│   수 있어요 어떤 것이 궁금하신 가요...       │
│                                             │
│   ...                                       │
└─────────────────────────────────────────────┘
```

---

## 🎯 우선순위

| 순위 | 작업 | 예상 시간 | 영향도 |
|------|------|----------|--------|
| **P0** | transcript_parser.py 유틸리티 작성 | 20분 | 🔴 CRITICAL |
| **P0** | /api/calls/{call_id}/transcript 엔드포인트 구현 | 15분 | 🔴 CRITICAL |
| **P0** | /api/call-history 엔드포인트 구현 (transcript 포함) | 30분 | 🔴 CRITICAL |
| **P1** | API 서버 통합 및 테스트 | 15분 | 🟡 HIGH |
| **P2** | Frontend 검증 | 10분 | 🟢 MEDIUM |

---

## 📝 추가 개선 사항

### 1. Transcript 품질 개선

**현재 문제**:
```
착신자: 안녕하세요 기 상 청 ai 통합 비 서 입니다...
```

**개선 방안**:
- STT 결과에서 공백 정규화
- 특수 문자 처리 개선
- 문장 단위로 merge

### 2. Timestamp 추가

```python
# 각 메시지에 timestamp 추가
{
  "role": "assistant",
  "content": "안녕하세요...",
  "timestamp": "2026-03-10T17:40:35.123"  # ✅ 추가
}
```

### 3. 페이지네이션 최적화

```python
# 대용량 통화 이력 처리를 위한 DB 인덱싱
# SQLite 또는 PostgreSQL 사용 고려
```

---

## 📌 결론

### 핵심 문제

**API 백엔드가 구현되지 않아 transcript 데이터를 Frontend에 전달하지 못함**

### 즉시 필요한 조치

1. ✅ `transcript_parser.py` 유틸리티 작성
2. ✅ `/api/calls/{call_id}/transcript` 엔드포인트 구현
3. ✅ `/api/call-history` 엔드포인트에 `transcripts` 필드 추가
4. ✅ API 서버 재시작 및 테스트
5. ✅ Frontend 동작 확인

### 예상 효과

- ✅ 통화 이력에서 대화 내용 정상 표시
- ✅ AI와 사용자 구분하여 표시
- ✅ 실시간 대화 내용 확인 가능
- ✅ 고객 문의 분석 및 품질 개선 가능

---

**작성자**: AI Assistant  
**점검 일시**: 2026-03-11  
**상태**: API 백엔드 구현 필요 🔴  

**관련 문서**:  
- [frontend-architecture.md](../frontend-architecture.md) - Frontend 아키텍처  
- [SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md) - 시스템 개요  

---

*최종 업데이트: 2026-03-11*
