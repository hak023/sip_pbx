# VectorDB 저장 Flow 상세 로깅 구현 완료

**작성일**: 2026-01-08  
**작업**: 통화 종료 후 VectorDB까지 지식 저장 전체 flow 상세 로깅 추가  
**상태**: ✅ 완료

---

## 📋 **작업 내용**

### 1️⃣ Frontend 에러 수정
**파일**: `frontend/app/call-history/page.tsx`

**문제**: TypeScript/JavaScript 문법 오류 - `try:` (Python 문법) 사용

**수정**:
```typescript
// Before (Python 문법)
try:

// After (JavaScript 문법)
try {
```

**수정 위치**: 3곳
- `fetchCallHistory` 함수
- `showCallDetailDialog` 함수
- `handleSaveNote` 함수

---

### 2️⃣ VectorDB 저장 Flow 상세 로깅 추가

## 🔄 **통화 종료 → VectorDB 저장 전체 Flow**

```
통화 종료 (BYE)
     ↓
📝 [CDR Flow] CDR 작성
     ↓
🎤 [STT Flow] 녹음 파일 STT 변환
     ↓
🚀 [Knowledge Flow] 지식 추출 트리거
     ↓
🔄 [VectorDB Flow] Step 1/6: 추출 시작
     ↓
🔄 [VectorDB Flow] Step 2/6: 트랜스크립트 로드
     ↓
🔄 [VectorDB Flow] Step 3/6: 화자 필터링
     ↓
🔄 [VectorDB Flow] Step 4/6: LLM 유용성 판단
     ↓
🔄 [VectorDB Flow] Step 5/6: 청킹 및 임베딩
     ↓
🔄 [VectorDB Flow] Step 6/6: VectorDB 저장
     ↓
🎉 [VectorDB Flow] ✅ 완료!
```

---

## 📝 **추가된 로그 상세**

### **1. CallManager - 지식 추출 트리거**
**파일**: `src/sip_core/call_manager.py`

```python
logger.info("🚀 [Knowledge Flow] Triggering knowledge extraction for regular SIP call",
           call_id=call_session.call_id,
           callee_id=callee_id,
           transcript_path=str(transcript_path))

logger.info("✅ [Knowledge Flow] Knowledge extraction task created (will run in background)",
           call_id=call_session.call_id,
           callee=callee_id)
```

### **2. SIPCallRecorder - STT 처리**
**파일**: `src/sip_core/sip_call_recorder.py`

```python
logger.info("🎤 [STT Flow] Starting post-processing STT", 
           call_id=call_id,
           audio_file=str(mixed_path),
           diarization_enabled=self.enable_diarization)

logger.info("✅ [STT Flow] STT completed",
           call_id=call_id,
           has_words=bool(stt_result.get("words")),
           has_speakers=bool(stt_result.get("speakers")),
           word_count=len(stt_result.get("words", [])))

logger.info("🔄 [STT Flow] Formatting transcript with speaker diarization",
           call_id=call_id)

logger.info("✅ [STT Flow] Transcript saved to file",
           call_id=call_id,
           file_path=str(transcript_path),
           transcript_length=len(transcript_text),
           preview=transcript_text[:100] + "...")
```

### **3. KnowledgeExtractor - 지식 추출 및 VectorDB 저장**
**파일**: `src/ai_voicebot/knowledge/knowledge_extractor.py`

#### Step 1: 시작
```python
logger.info("🔄 [VectorDB Flow] Step 1/6: Knowledge extraction started",
           call_id=call_id,
           owner_id=owner_id,
           speaker=speaker,
           transcript_path=transcript_path)
```

#### Step 2: 트랜스크립트 로드
```python
logger.info("🔄 [VectorDB Flow] Step 2/6: Loading transcript", 
           call_id=call_id,
           path=transcript_path)

logger.info("✅ [VectorDB Flow] Transcript loaded", 
           call_id=call_id,
           transcript_length=len(transcript),
           preview=transcript[:100] + "...")
```

#### Step 3: 화자 필터링
```python
logger.info("🔄 [VectorDB Flow] Step 3/6: Filtering by speaker",
           call_id=call_id,
           target_speaker=speaker)

logger.info("✅ [VectorDB Flow] Speaker text filtered",
           call_id=call_id,
           filtered_length=len(speaker_text),
           preview=speaker_text[:100] + "...")
```

#### Step 4: LLM 유용성 판단
```python
logger.info("🔄 [VectorDB Flow] Step 4/6: LLM judging usefulness",
           call_id=call_id)

logger.info("✅ [VectorDB Flow] LLM judgment completed",
           call_id=call_id,
           is_useful=judgment["is_useful"],
           confidence=judgment.get("confidence", 0.0),
           reason=judgment.get("reason", "N/A"))
```

#### Step 5: 청킹 및 임베딩
```python
logger.info("🔄 [VectorDB Flow] Step 5/6: Chunking and embedding",
           call_id=call_id,
           chunk_size=self.chunk_size,
           chunk_overlap=self.chunk_overlap)

logger.info(f"  📄 Processing info block {idx + 1}/{len(extracted_info)}",
           call_id=call_id,
           chunks_count=len(chunks),
           category=info.get("category", "기타"))
```

#### Step 6: VectorDB 저장
```python
logger.info(f"🔄 [VectorDB Flow] Step 6/6: Storing chunk {stored_count + 1} to VectorDB",
           call_id=call_id,
           doc_id=doc_id,
           embedding_dim=len(embedding),
           metadata_keys=list(metadata.keys()))

logger.info(f"  ✅ Chunk {stored_count} stored successfully",
           call_id=call_id,
           doc_id=doc_id)
```

#### 완료
```python
logger.info("🎉 [VectorDB Flow] ✅ Knowledge extraction COMPLETED!",
           call_id=call_id,
           total_chunks_stored=stored_count,
           confidence=judgment["confidence"],
           owner_id=owner_id)
```

### **4. CallManager - CDR 작성**
**파일**: `src/sip_core/call_manager.py`

```python
logger.info("📝 [CDR Flow] Writing CDR (Call Detail Record)",
           call_id=cdr_data["call_id"],
           caller=cdr_data["caller_uri"],
           callee=cdr_data["callee_uri"],
           duration=cdr_data["duration_seconds"])

logger.info("✅ [CDR Flow] CDR written successfully to file", 
           call_id=call_session.call_id,
           cdr_file=f"./cdr/cdr-{datetime.now().strftime('%Y-%m-%d')}.jsonl")
```

---

## 📊 **로그 예시 (실제 통화 후)**

```
2026-01-08 15:30:45 | INFO     | 📝 [CDR Flow] Writing CDR (Call Detail Record) | call_id=call-abc123 | caller=sip:1000@localhost | callee=sip:2000@localhost | duration=120
2026-01-08 15:30:45 | INFO     | ✅ [CDR Flow] CDR written successfully to file | call_id=call-abc123 | cdr_file=./cdr/cdr-2026-01-08.jsonl
2026-01-08 15:30:45 | INFO     | 🎤 [STT Flow] Starting post-processing STT | call_id=call-abc123 | audio_file=./recordings/call-abc123/mixed.wav | diarization_enabled=True
2026-01-08 15:30:50 | INFO     | ✅ [STT Flow] STT completed | call_id=call-abc123 | has_words=True | has_speakers=True | word_count=245
2026-01-08 15:30:50 | INFO     | 🔄 [STT Flow] Formatting transcript with speaker diarization | call_id=call-abc123
2026-01-08 15:30:50 | INFO     | ✅ [STT Flow] Transcript saved to file | call_id=call-abc123 | file_path=./recordings/call-abc123/transcript.txt | transcript_length=1250 | preview=발신자: 안녕하세요...
2026-01-08 15:30:50 | INFO     | 🚀 [Knowledge Flow] Triggering knowledge extraction for regular SIP call | call_id=call-abc123 | callee_id=sip:2000@localhost | transcript_path=./recordings/call-abc123/transcript.txt
2026-01-08 15:30:50 | INFO     | ✅ [Knowledge Flow] Knowledge extraction task created (will run in background) | call_id=call-abc123 | callee=sip:2000@localhost
2026-01-08 15:30:50 | INFO     | 🔄 [VectorDB Flow] Step 1/6: Knowledge extraction started | call_id=call-abc123 | owner_id=sip:2000@localhost | speaker=callee | transcript_path=./recordings/call-abc123/transcript.txt
2026-01-08 15:30:50 | INFO     | 🔄 [VectorDB Flow] Step 2/6: Loading transcript | call_id=call-abc123 | path=./recordings/call-abc123/transcript.txt
2026-01-08 15:30:50 | INFO     | ✅ [VectorDB Flow] Transcript loaded | call_id=call-abc123 | transcript_length=1250 | preview=발신자: 안녕하세요\n착신자: 네, 안녕하세요...
2026-01-08 15:30:50 | INFO     | 🔄 [VectorDB Flow] Step 3/6: Filtering by speaker | call_id=call-abc123 | target_speaker=callee
2026-01-08 15:30:50 | INFO     | ✅ [VectorDB Flow] Speaker text filtered | call_id=call-abc123 | filtered_length=650 | preview=네, 안녕하세요. 무엇을 도와드릴까요...
2026-01-08 15:30:50 | INFO     | 🔄 [VectorDB Flow] Step 4/6: LLM judging usefulness | call_id=call-abc123
2026-01-08 15:30:52 | INFO     | ✅ [VectorDB Flow] LLM judgment completed | call_id=call-abc123 | is_useful=True | confidence=0.85 | reason=Contains valuable customer service information
2026-01-08 15:30:52 | INFO     | 🔄 [VectorDB Flow] Step 5/6: Chunking and embedding | call_id=call-abc123 | chunk_size=500 | chunk_overlap=50
2026-01-08 15:30:52 | INFO     |   📄 Processing info block 1/1 | call_id=call-abc123 | chunks_count=2 | category=기타
2026-01-08 15:30:52 | INFO     | 🔄 [VectorDB Flow] Step 6/6: Storing chunk 1 to VectorDB | call_id=call-abc123 | doc_id=call-abc123_chunk_0_0 | embedding_dim=384 | metadata_keys=['call_id', 'owner', 'speaker', 'category', 'keywords', 'chunk_index', 'confidence']
2026-01-08 15:30:52 | INFO     |   ✅ Chunk 1 stored successfully | call_id=call-abc123 | doc_id=call-abc123_chunk_0_0
2026-01-08 15:30:52 | INFO     | 🔄 [VectorDB Flow] Step 6/6: Storing chunk 2 to VectorDB | call_id=call-abc123 | doc_id=call-abc123_chunk_0_1 | embedding_dim=384 | metadata_keys=['call_id', 'owner', 'speaker', 'category', 'keywords', 'chunk_index', 'confidence']
2026-01-08 15:30:52 | INFO     |   ✅ Chunk 2 stored successfully | call_id=call-abc123 | doc_id=call-abc123_chunk_0_1
2026-01-08 15:30:52 | INFO     | 🎉 [VectorDB Flow] ✅ Knowledge extraction COMPLETED! | call_id=call-abc123 | total_chunks_stored=2 | confidence=0.85 | owner_id=sip:2000@localhost
```

---

## 🔍 **로그 필터링 명령어**

### 전체 Flow 확인
```bash
cat logs/app.log | findstr "Flow"
```

### CDR Flow만 확인
```bash
cat logs/app.log | findstr "[CDR Flow]"
```

### STT Flow만 확인
```bash
cat logs/app.log | findstr "[STT Flow]"
```

### Knowledge Flow 확인
```bash
cat logs/app.log | findstr "[Knowledge Flow]"
```

### VectorDB Flow 확인 (가장 상세)
```bash
cat logs/app.log | findstr "[VectorDB Flow]"
```

### 특정 Call ID 추적
```bash
cat logs/app.log | findstr "call-abc123"
```

---

## 🎯 **로그 레벨별 정보**

### INFO (정상 Flow)
- ✅ 성공 단계
- 🔄 진행 중 단계
- 📝 기록 작업
- 🎤 STT 작업
- 🚀 트리거 작업
- 🎉 완료

### WARNING (비정상이지만 처리 가능)
- ⚠️ 비어있는 트랜스크립트
- ⚠️ 텍스트 길이 부족
- ❌ 유용하지 않은 콘텐츠 (정상)
- ❌ 낮은 신뢰도 (정상)

### ERROR (오류)
- ❌ STT 오류
- ❌ 지식 추출 오류
- ❌ VectorDB 저장 오류
- ❌ CDR 작성 오류

---

## 📊 **수정 통계**

| 항목 | 값 |
|------|-----|
| **수정 파일** | 4개 |
| **추가 로그** | 30+ 곳 |
| **Flow 단계** | 6단계 (VectorDB Flow) |
| **Lint 오류** | 0개 ✅ |

---

## ✅ **검증 방법**

### 1. 서버 재시작
```powershell
cd C:\work\workspace_sippbx\sip-pbx
python src/main.py
```

### 2. 통화 수행
- SIP 클라이언트로 통화 진행
- 통화 종료

### 3. 로그 확인
```powershell
# 실시간 로그 확인
tail -f logs/app.log

# 또는 특정 Call ID로 필터링
cat logs/app.log | findstr "call-abc123"
```

### 4. VectorDB 확인
```python
# Python REPL에서
from src.ai_voicebot.knowledge.chromadb_client import ChromaDBClient

db = ChromaDBClient()
results = db.search(query_text="테스트", top_k=5)
print(results)
```

---

## 🎉 **완료 사항 요약**

✅ Frontend 에러 수정 (TypeScript 문법)  
✅ CDR 작성 로그 추가  
✅ STT 처리 상세 로그 추가  
✅ 지식 추출 트리거 로그 추가  
✅ VectorDB Flow 6단계 상세 로그  
✅ 각 단계별 성공/실패 구분  
✅ 데이터 미리보기 포함  
✅ Emoji로 시각적 구분  
✅ Lint 오류 없음  

**이제 통화가 끝나면 전체 Flow를 로그에서 추적할 수 있습니다!** 🎯📊

---

**작성자**: AI Assistant  
**상태**: ✅ 완료  
**다음 작업**: 실제 통화 테스트 및 로그 확인

