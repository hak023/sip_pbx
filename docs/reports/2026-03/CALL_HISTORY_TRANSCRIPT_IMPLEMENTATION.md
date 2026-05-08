# 통화 이력 Transcript 표시 기능 구현 완료

**작성일**: 2026-03-11  
**버전**: 1.0  
**상태**: ✅ 구현 완료  

---

## 📋 구현 개요

Frontend 통화 이력 페이지에서 대화 내용이 표시되지 않는 문제를 해결하기 위해 API 백엔드를 구현했습니다.

---

## ✅ 완료된 작업

### 1. Transcript 파싱 유틸리티 (`transcript_parser.py`)

**파일**: `sip-pbx/src/api/utils/transcript_parser.py`

**주요 기능**:
- `parse_transcript_file()`: transcript.txt 파일을 TranscriptMessage 형식으로 변환
- `get_transcript_for_call()`: call_id로 transcript 파일 검색 및 파싱
- `get_all_call_metadata()`: 모든 통화의 metadata 읽기

**변환 로직**:
```
입력 (transcript.txt):
  착신자: 안녕하세요...
  발신자: 오늘의

출력 (JSON):
  [
    {"role": "assistant", "content": "안녕하세요..."},
    {"role": "user", "content": "오늘의"}
  ]
```

### 2. Calls API 라우터 (`calls.py`)

**파일**: `sip-pbx/src/api/routers/calls.py`

**엔드포인트**:

#### A. GET /api/calls/{call_id}/transcript
- 특정 통화의 대화 내용 반환
- TranscriptMessage[] 형식
- Frontend가 바로 사용 가능한 형태

**응답 예시**:
```json
{
  "call_id": "0IBsHSliVK",
  "messages": [
    {"role": "assistant", "content": "안녕하세요 기 상 청 ai 통합 비 서 입니다..."},
    {"role": "user", "content": "오늘의"}
  ],
  "count": 10
}
```

#### B. GET /api/calls/{call_id}/recording
- 녹음 파일 다운로드
- mixed.wav 파일 반환
- FileResponse로 스트리밍

### 3. Call History API 라우터 (`call_history.py`)

**파일**: `sip-pbx/src/api/routers/call_history.py`

**엔드포인트**:

#### GET /api/call-history
- 통화 이력 목록 반환
- **각 항목에 `transcripts` 필드 포함** ✅
- 페이지네이션 지원 (page, limit)
- callee 필터링 지원

**응답 예시**:
```json
{
  "items": [
    {
      "call_id": "0IBsHSliVK",
      "caller_id": "1003",
      "callee_id": "1004",
      "start_time": "2026-03-10T17:40:29.775360",
      "end_time": "2026-03-10T17:41:43.600858",
      "has_recording": true,
      "has_transcript": true,
      "transcripts": [
        {"role": "assistant", "content": "안녕하세요..."},
        {"role": "user", "content": "오늘의"},
        ...
      ]
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

### 4. Main API 업데이트 (`main.py`)

**파일**: `sip-pbx/src/api/main.py`

**변경 사항**:
- 새 라우터 등록: `call_history`, `calls`
- CORS 설정 유지 (Frontend 연동)
- 안전한 import (누락된 라우터 처리)

### 5. 테스트 스크립트 (`test_api.py`)

**파일**: `sip-pbx/test_api.py`

**테스트 항목**:
1. Health Check
2. Call History API
3. Transcript API
4. Recording API

**실행 방법**:
```bash
cd sip-pbx
python test_api.py
```

---

## 🚀 사용 방법

### Step 1: API 서버 시작

```bash
cd sip-pbx
python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

**출력 예시**:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
✅ Routers registered: call_history, calls
```

### Step 2: API 테스트

```bash
# Health Check
curl http://localhost:8000/health

# 통화 이력 조회
curl http://localhost:8000/api/call-history?page=1&limit=20

# 특정 통화의 Transcript 조회
curl http://localhost:8000/api/calls/0IBsHSliVK/transcript

# 녹음 파일 다운로드
curl http://localhost:8000/api/calls/0IBsHSliVK/recording -o recording.wav
```

### Step 3: Frontend 연동 확인

1. Frontend 서버 시작:
   ```bash
   cd frontend
   npm run dev
   ```

2. 통화 이력 페이지 접속:
   ```
   http://localhost:3000/call-history
   ```

3. 통화 행 클릭 (roll down)

4. ✅ 대화 내용 표시 확인:
   ```
   💬 대화 내용
   
   🤖 AI
   안녕하세요 기 상 청 ai 통합 비 서 입니다...
   
   👤 사용자
   오늘의
   
   🤖 AI
   수 있어요 어떤 것이 궁금하신 가요...
   ```

---

## 📊 예상 결과

### Before (구현 전)

```
통화 이력
┌─────────────────────────────────────────────┐
│ 통화 ID: 0IBsHSliVK                         │
│ ▼ 대화 내용                                 │
│   대화 내용이 없습니다                       │
│   (call_id: 0IBsHSliVK, has_recording: Yes) │
└─────────────────────────────────────────────┘
```

### After (구현 후)

```
통화 이력
┌─────────────────────────────────────────────┐
│ 통화 ID: 0IBsHSliVK                         │
│ ▼ 대화 내용                                 │
│                                             │
│   🤖 AI                                     │
│   안녕하세요 기 상 청 ai 통합 비 서 입니다  │
│   무엇을 도와 드릴 까요 저는 날씨 예 보...  │
│                                             │
│   👤 사용자                                 │
│   오늘의                                    │
│                                             │
│   🤖 AI                                     │
│   수 있어요 어떤 것이 궁금하신 가요...       │
│                                             │
│   👤 사용자                                 │
│   날씨                                      │
│                                             │
│   (총 10개 메시지)                          │
└─────────────────────────────────────────────┘
```

---

## 📁 생성된 파일 목록

```
sip-pbx/
├── src/
│   └── api/
│       ├── main.py (수정)
│       ├── routers/
│       │   ├── __init__.py (생성)
│       │   ├── calls.py (생성)
│       │   └── call_history.py (생성)
│       └── utils/
│           ├── __init__.py (생성)
│           └── transcript_parser.py (생성)
├── test_api.py (생성)
└── docs/
    └── reports/
        ├── CALL_HISTORY_TRANSCRIPT_DISPLAY_ISSUE.md (생성)
        └── CALL_HISTORY_TRANSCRIPT_IMPLEMENTATION.md (이 파일)
```

---

## 🔧 기술 스택

- **Backend**: FastAPI, Python 3.8+
- **Frontend**: Next.js, React, TypeScript
- **Data Format**: JSON
- **File I/O**: pathlib, json
- **API Protocol**: REST

---

## 🎯 핵심 기능

### 1. Transcript 파싱

```python
# 착신자/발신자 → assistant/user 변환
if line.startswith('착신자:'):
    messages.append({
        "role": "assistant",
        "content": line.replace('착신자:', '').strip()
    })
elif line.startswith('발신자:'):
    messages.append({
        "role": "user",
        "content": line.replace('발신자:', '').strip()
    })
```

### 2. Call ID 기반 검색

```python
# metadata.json에서 call_id로 디렉토리 찾기
for dir_path in recordings_path.glob("*"):
    metadata = json.load(open(dir_path / "metadata.json"))
    if metadata.get("call_id") == call_id:
        return parse_transcript_file(dir_path / "transcript.txt")
```

### 3. Frontend 호환성

```typescript
// Frontend에서 두 가지 방식 모두 지원
const messages = transcripts[row.call_id] || row.transcripts || [];

// API는 두 필드 모두 반환
{
  "messages": [...],  // 새 방식
  "transcripts": [...] // 레거시 지원
}
```

---

## 🧪 테스트 결과

### 자동 테스트 (`test_api.py`)

```bash
$ python sip-pbx/test_api.py

============================================================
API 테스트 시작
============================================================

=== 1. Health Check ===
Status: 200
Response: {'status': 'ok'}

=== 2. Call History ===
Status: 200
Total: 1
Items: 1

첫 번째 항목:
  Call ID: 0IBsHSliVK
  Caller: 1003
  Callee: 1004
  Has Transcript: True
  Transcripts Count: 10

  대화 내용 (처음 3개):
    1. 🤖 AI: 안녕하세요 기 상 청 ai 통합 비 서 입니다 무엇을 도와...
    2. 👤 사용자: 오늘의
    3. 🤖 AI: 수 있어요 어떤 것이 궁금하신 가요 실시간 오늘의...

=== 3. Transcript for 0IBsHSliVK ===
Status: 200
Call ID: 0IBsHSliVK
Message Count: 10

대화 내용 (전체 10개):
  1. 🤖 AI: 안녕하세요 기 상 청 ai 통합 비 서 입니다...
  2. 👤 사용자: 오늘의
  3. 🤖 AI: 수 있어요 어떤 것이 궁금하신 가요...
  4. 👤 사용자: 날씨
  5. 🤖 AI: w
  6. 👤 사용자: 를 알려
  7. 🤖 AI: w
  8. 👤 사용자: 주세요
  9. 🤖 AI: . k m a . 고 . k r 나 날씨 누 리 앱 에서...
  10. 👤 사용자: 오늘의 날씨 를 알려 주세요...

=== 4. Recording for 0IBsHSliVK ===
Status: 200
✅ 녹음 파일 존재
Content-Type: audio/wav

============================================================
테스트 결과 요약
============================================================
✅ PASS - Health Check
✅ PASS - Call History
✅ PASS - Transcript
✅ PASS - Recording

총 4개 중 4개 성공
```

---

## 📝 추가 개선 사항 (향후)

### 1. Transcript 품질 개선

**현재**:
```
착신자: 안녕하세요 기 상 청 ai 통합 비 서 입니다
```

**개선 방안**:
- STT 결과 공백 정규화
- 문장 단위로 merge
- 문장 부호 추가

### 2. Timestamp 추가

```python
{
  "role": "assistant",
  "content": "안녕하세요...",
  "timestamp": "2026-03-10T17:40:35.123"  # ✅ 추가
}
```

### 3. 페이지네이션 최적화

- 대용량 통화 이력 처리
- DB 인덱싱 (SQLite/PostgreSQL)
- 캐싱 추가

### 4. 검색 기능

- 대화 내용 full-text search
- 날짜 범위 필터
- AI/사용자 발화 필터

---

## 🎉 완료 체크리스트

- [x] `transcript_parser.py` 유틸리티 작성
- [x] `/api/calls/{call_id}/transcript` 엔드포인트 구현
- [x] `/api/call-history` 엔드포인트에 `transcripts` 필드 추가
- [x] `main.py` 라우터 등록
- [x] 테스트 스크립트 작성
- [x] 문서화 (분석 보고서, 구현 완료 보고서)

---

## 📌 결론

### 달성한 목표

1. ✅ **API 백엔드 구현 완료**: transcript 데이터를 Frontend에 전달
2. ✅ **Transcript 파싱 로직 구현**: transcript.txt → TranscriptMessage[] 변환
3. ✅ **Frontend 호환성 확보**: 기존 Frontend 코드 수정 없이 동작
4. ✅ **테스트 자동화**: `test_api.py`로 4가지 엔드포인트 검증

### 예상 효과

- ✅ 통화 이력에서 대화 내용 정상 표시
- ✅ AI와 사용자 발화 구분 표시
- ✅ 고객 문의 분석 가능
- ✅ 서비스 품질 개선 가능

---

**작성자**: AI Assistant  
**구현 일시**: 2026-03-11  
**상태**: ✅ 완료  

**관련 문서**:  
- [CALL_HISTORY_TRANSCRIPT_DISPLAY_ISSUE.md](CALL_HISTORY_TRANSCRIPT_DISPLAY_ISSUE.md) - 문제 분석 보고서  
- [frontend-architecture.md](../../architecture/frontend-architecture.md) - Frontend 아키텍처  
- [SYSTEM_OVERVIEW.md](../../SYSTEM_OVERVIEW.md) - 시스템 개요  

---

*최종 업데이트: 2026-03-11*
