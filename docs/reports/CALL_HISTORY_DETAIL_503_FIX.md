# 통화 이력 상세 조회 503 에러 수정 완료

**날짜**: 2026-01-08  
**작업**: Call History 상세 조회 API 503 에러 해결

---

## 🔍 발견된 문제

### Backend 로그:
```
INFO:     127.0.0.1:65362 - "GET /api/call-history?page=1&limit=50 HTTP/1.1" 200 OK
INFO:     127.0.0.1:53993 - "GET /api/call-history/test-call-1000 HTTP/1.1" 503 Service Unavailable
INFO:     127.0.0.1:53993 - "GET /api/call-history/test-call-1001 HTTP/1.1" 503 Service Unavailable
INFO:     127.0.0.1:53993 - "GET /api/call-history/test-call-1002 HTTP/1.1" 503 Service Unavailable
```

**현상**:
- ✅ 통화 이력 목록 조회 (`GET /api/call-history`) → 200 OK
- ❌ 통화 상세 조회 (`GET /api/call-history/{call_id}`) → 503 Service Unavailable

---

## 🐛 문제 원인

### `get_call_detail` 함수 (수정 전):
```python
@router.get("/{call_id}")
async def get_call_detail(
    call_id: str,
    db=Depends(get_db),  # ❌ 데이터베이스 의존성
    current_user=Depends(get_current_operator)
):
    try:
        if not db:
            raise HTTPException(status_code=503, detail="Database not available")  # ❌ 여기서 에러 발생
        
        # 데이터베이스 쿼리 (실행 안 됨)
        call_info_query = """
            SELECT ch.*, uhr.*
            FROM call_history ch
            LEFT JOIN unresolved_hitl_requests uhr ON ch.call_id = uhr.call_id
            WHERE ch.call_id = :call_id
        """
        call_info = await db.fetch_one(call_info_query, {"call_id": call_id})
        ...
```

**원인**:
1. `get_db()` 함수가 항상 `None` 반환
2. `if not db:` 체크에서 503 에러 발생
3. 데이터베이스가 없어서 실행 불가

---

## ✅ 수정 내용

### 1. `get_call_detail` - CDR 파일 기반으로 재작성

```python
@router.get("/{call_id}", response_model=CallDetailResponse)
async def get_call_detail(
    call_id: str,
    current_user=Depends(get_current_operator)  # ✅ db 의존성 제거
):
    """통화 상세 정보 조회 (CDR 파일 + Recording 파일 기반)"""
    try:
        # ✅ CDR 파일에서 통화 정보 찾기
        all_cdrs = read_cdr_files()
        
        call_info_dict = None
        for cdr in all_cdrs:
            if cdr.get("call_id") == call_id:
                call_info_dict = cdr.copy()
                break
        
        if not call_info_dict:
            raise HTTPException(status_code=404, detail="Call not found")
        
        # ✅ 녹음 파일 경로
        recording_path = Path(f"./recordings/{call_id}")
        has_recording = recording_path.exists() and (recording_path / "mixed.wav").exists()
        
        # ✅ Transcript 읽기
        transcripts = []
        if has_recording:
            transcript_file = recording_path / "transcript.txt"
            if transcript_file.exists():
                try:
                    with open(transcript_file, 'r', encoding='utf-8') as f:
                        transcript_text = f.read()
                    
                    # JSON 형식 시도
                    try:
                        transcript_data = json.loads(transcript_text)
                        if isinstance(transcript_data, list):
                            for item in transcript_data:
                                transcripts.append(CallTranscript(
                                    speaker=item.get("speaker", "unknown"),
                                    text=item.get("text", ""),
                                    timestamp=datetime.fromisoformat(item.get("timestamp"))
                                ))
                    except json.JSONDecodeError:
                        # 일반 텍스트 형식
                        transcripts.append(CallTranscript(
                            speaker="user",
                            text=transcript_text,
                            timestamp=datetime.fromisoformat(call_info_dict.get("start_time"))
                        ))
                except Exception as e:
                    logger.warning("Failed to read transcript", error=str(e))
        
        # ✅ Metadata 읽기
        if has_recording:
            metadata_file = recording_path / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    call_info_dict.update(metadata)
                except Exception as e:
                    logger.warning("Failed to read metadata", error=str(e))
        
        # ✅ 녹음 정보 추가
        call_info_dict["has_recording"] = has_recording
        call_info_dict["recording_path"] = str(recording_path) if has_recording else None
        
        # ✅ Frontend 호환성을 위해 필드 이름 변환
        call_info_dict["caller_id"] = call_info_dict.get("caller", "Unknown")
        call_info_dict["callee_id"] = call_info_dict.get("callee", "Unknown")
        
        return CallDetailResponse(
            call_info=call_info_dict,
            transcripts=transcripts,
            hitl_request=None
        )
```

---

### 2. `add_call_note` - 파일 기반으로 수정

```python
@router.post("/{call_id}/note", response_model=CallNoteResponse)
async def add_call_note(
    call_id: str,
    note: CallNoteCreate,
    current_user=Depends(get_current_operator)  # ✅ db 의존성 제거
):
    """통화 이력에 운영자 메모 추가 (파일 기반)"""
    try:
        operator_id = current_user["id"]
        
        # ✅ 메모를 파일로 저장
        notes_dir = Path("./call_notes")
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        note_file = notes_dir / f"{call_id}.json"
        note_data = {
            "call_id": call_id,
            "operator_note": note.operator_note,
            "follow_up_required": note.follow_up_required,
            "follow_up_phone": note.follow_up_phone,
            "status": "noted",
            "noted_at": datetime.now().isoformat(),
            "noted_by": operator_id
        }
        
        with open(note_file, 'w', encoding='utf-8') as f:
            json.dump(note_data, f, ensure_ascii=False, indent=2)
        
        return CallNoteResponse(
            call_id=call_id,
            operator_note=note.operator_note,
            follow_up_required=note.follow_up_required,
            status="noted"
        )
```

---

### 3. `resolve_hitl_request` - 파일 기반으로 수정

```python
@router.put("/{call_id}/resolve", response_model=ResolveResponse)
async def resolve_hitl_request(
    call_id: str,
    current_user=Depends(get_current_operator)  # ✅ db 의존성 제거
):
    """미처리 HITL 요청 해결 처리 (파일 기반)"""
    try:
        operator_id = current_user["id"]
        resolved_at = datetime.now()
        
        # ✅ 메모 파일이 있으면 업데이트
        notes_dir = Path("./call_notes")
        notes_dir.mkdir(parents=True, exist_ok=True)
        
        note_file = notes_dir / f"{call_id}.json"
        
        if note_file.exists():
            with open(note_file, 'r', encoding='utf-8') as f:
                note_data = json.load(f)
            
            note_data["status"] = "resolved"
            note_data["resolved_at"] = resolved_at.isoformat()
            note_data["resolved_by"] = operator_id
        else:
            # 메모 없이 바로 해결 처리
            note_data = {
                "call_id": call_id,
                "status": "resolved",
                "resolved_at": resolved_at.isoformat(),
                "resolved_by": operator_id
            }
        
        with open(note_file, 'w', encoding='utf-8') as f:
            json.dump(note_data, f, ensure_ascii=False, indent=2)
        
        return ResolveResponse(
            call_id=call_id,
            status="resolved",
            resolved_at=resolved_at
        )
```

---

## 📁 파일 구조

수정 후 데이터 저장 방식:

```
sip-pbx/
├── cdr/                        # CDR (Call Detail Records)
│   └── cdr-2026-01-08.jsonl   # 통화 이력 (JSON Lines)
│
├── recordings/                 # 녹음 파일
│   └── {call_id}/
│       ├── mixed.wav          # 믹스된 오디오
│       ├── caller.wav         # 발신자 오디오
│       ├── callee.wav         # 수신자 오디오
│       ├── metadata.json      # 녹음 메타데이터
│       └── transcript.txt     # STT 결과
│
└── call_notes/                 # 운영자 메모 (신규)
    └── {call_id}.json         # 메모 + 상태
```

---

## 🧪 검증

### 테스트 1: 통화 이력 목록 조회
```bash
$ curl http://localhost:8000/api/call-history?page=1&limit=50

# 응답: 200 OK
{
  "items": [
    {
      "call_id": "test-call-1000",
      "caller_id": "sip:1000@localhost",
      "callee_id": "sip:2000@localhost",
      ...
    }
  ],
  "total": 5,
  "page": 1,
  "limit": 50
}
```

### 테스트 2: 통화 상세 조회
```bash
$ curl http://localhost:8000/api/call-history/test-call-1000

# 응답: 200 OK (이전에는 503 에러)
{
  "call_info": {
    "call_id": "test-call-1000",
    "caller": "sip:1000@localhost",
    "callee": "sip:2000@localhost",
    "duration": 300,
    "has_recording": false,
    ...
  },
  "transcripts": [],
  "hitl_request": null
}
```

### 테스트 3: 메모 추가
```bash
$ curl -X POST http://localhost:8000/api/call-history/test-call-1000/note \
  -H "Content-Type: application/json" \
  -d '{"operator_note": "Test note", "follow_up_required": false}'

# 응답: 200 OK
# 파일 생성: ./call_notes/test-call-1000.json
```

---

## 📊 수정 전후 비교

| API 엔드포인트 | 수정 전 | 수정 후 |
|---------------|--------|--------|
| `GET /api/call-history` | ✅ 200 OK | ✅ 200 OK |
| `GET /api/call-history/{call_id}` | ❌ 503 Service Unavailable | ✅ 200 OK |
| `POST /api/call-history/{call_id}/note` | ❌ 503 Service Unavailable | ✅ 200 OK (파일 저장) |
| `PUT /api/call-history/{call_id}/resolve` | ❌ 503 Service Unavailable | ✅ 200 OK (파일 저장) |

---

## ✨ 핵심 개선사항

1. ✅ **데이터베이스 의존성 제거**: 모든 엔드포인트에서 `db=Depends(get_db)` 제거
2. ✅ **CDR 파일 기반 조회**: `read_cdr_files()` 함수로 통화 이력 조회
3. ✅ **Recording 파일 통합**: transcript와 metadata를 파일에서 읽기
4. ✅ **파일 기반 메모 저장**: `./call_notes/` 디렉토리에 JSON 형식으로 저장
5. ✅ **Frontend 호환성**: `caller_id`, `callee_id` 필드 자동 변환

---

## 🚀 다음 단계

### Frontend에서 테스트:
1. http://localhost:3000/call-history 접속
2. 통화 이력 목록 확인
3. "상세보기" 버튼 클릭
4. ✅ 통화 상세 정보가 정상적으로 표시되어야 함

### Backend 로그 확인:
```bash
# Backend 서버 로그에서 200 OK 확인
$ cat logs/app.log | findstr "call-history"

# 예상 출력:
# INFO: "GET /api/call-history?page=1&limit=50 HTTP/1.1" 200 OK
# INFO: "GET /api/call-history/test-call-1000 HTTP/1.1" 200 OK
```

---

## 📝 참고사항

- **데이터베이스 없이 동작**: 모든 데이터는 파일 기반 (CDR, Recording, Notes)
- **추후 데이터베이스 추가 시**: `read_cdr_files()` 대신 데이터베이스 쿼리로 변경 가능
- **메모 파일 위치**: `./call_notes/{call_id}.json`
- **녹음 파일 위치**: `./recordings/{call_id}/`

---

## 🎯 수정 파일

- ✅ `sip-pbx/src/api/routers/call_history.py`
  - `get_call_detail()` - CDR 파일 기반으로 재작성
  - `add_call_note()` - 파일 기반 메모 저장
  - `resolve_hitl_request()` - 파일 기반 상태 업데이트

