# 📊 일반 통화 지식 추출 검토 및 구현 보고서

## 📋 검토 일자
**2026-01-07**

---

## ✅ 설계서 확인 결과

### 1. 설계서에 명시됨 (`docs/ai-voicebot-architecture.md` 섹션 4.4)

**지식 추출 워크플로우**:
```
통화 종료 → 전체 텍스트 로드 → 화자별 발화 분리 → 착신자 발화만 추출
                                                            ↓
                                         LLM 유용성 판단 (신뢰도 0.7 이상)
                                                            ↓
                                    유용함 → 텍스트 청킹 → 임베딩 → VectorDB 저장
```

**LLM 유용성 판단 기준**:
- ✅ 약속 일정
- ✅ 연락처 정보
- ✅ 업무 지시사항
- ✅ 자주 묻는 질문에 대한 답변
- ✅ 개인 선호도

**출력 형식**:
```json
{
  "is_useful": true/false,
  "confidence": 0.0-1.0,
  "reason": "판단 이유",
  "extracted_info": [
    {
      "text": "추출할 텍스트",
      "category": "약속|정보|지시|기타",
      "keywords": ["키워드1", "키워드2"]
    }
  ]
}
```

---

## ✅ 구현 상태 검토

### 1. KnowledgeExtractor ✅ (완전 구현)
**파일**: `src/ai_voicebot/knowledge/knowledge_extractor.py` (308 lines)

**구현된 기능**:
- ✅ `extract_from_call()` - 메인 추출 메서드
- ✅ `_load_transcript()` - 전사 텍스트 로드
- ✅ `_filter_by_speaker()` - 화자별 필터링 (caller/callee)
- ✅ `_chunk_text()` - 텍스트 청킹 (오버랩 포함)
- ✅ LLM 유용성 판단 통합
- ✅ 임베딩 생성 및 VectorDB 저장
- ✅ 메타데이터 관리
- ✅ 통계 추적

**설정 가능한 파라미터**:
- `min_confidence`: 최소 신뢰도 (기본값: 0.7)
- `chunk_size`: 청크 크기 (기본값: 500자)
- `chunk_overlap`: 청크 오버랩 (기본값: 50자)
- `min_text_length`: 최소 텍스트 길이 (기본값: 50자)

**워크플로우**:
```python
async def extract_from_call(call_id, transcript_path, owner_id, speaker):
    # 1. 전사 텍스트 로드
    transcript = await self._load_transcript(transcript_path)
    
    # 2. 화자 필터링 (착신자 발화만)
    speaker_text = self._filter_by_speaker(transcript, speaker)
    
    # 3. LLM 유용성 판단
    judgment = await self.llm.judge_usefulness(
        transcript=speaker_text,
        speaker=speaker
    )
    
    # 4. 신뢰도 확인 (0.7 이상)
    if judgment["confidence"] < self.min_confidence:
        return  # 지식 추출 안 함
    
    # 5. 텍스트 청킹
    chunks = self._chunk_text(text)
    
    # 6. 임베딩 + VectorDB 저장
    for chunk in chunks:
        embedding = await self.embedder.embed(chunk)
        await self.vector_db.upsert(doc_id, embedding, chunk, metadata)
```

---

### 2. LLMClient.judge_usefulness() ✅ (완전 구현)
**파일**: `src/ai_voicebot/ai_pipeline/llm_client.py`

**구현 확인**:
```python
async def judge_usefulness(
    self, 
    transcript: str, 
    speaker: str = "callee"
) -> Dict:
    """
    통화 내용의 유용성 판단 (VectorDB 저장 가치)
    
    Returns:
        {
            "is_useful": bool,
            "confidence": float,
            "reason": str,
            "extracted_info": List[Dict]
        }
    """
```

**프롬프트**:
```python
prompt = f"""
다음 통화 내용을 분석하여 향후 AI 비서가 활용할 수 있는 
유용한 정보가 있는지 판단하세요.

유용한 정보 예시:
- 약속 일정
- 연락처 정보
- 업무 지시사항
- 자주 묻는 질문에 대한 답변
- 개인 선호도

통화 내용:
{transcript}

출력 형식 (JSON):
{{
  "is_useful": true/false,
  "confidence": 0.0-1.0,
  "reason": "판단 이유",
  "extracted_info": [...]
}}
"""
```

---

### 3. AI 통화 지식 추출 ✅ (작동 중)
**파일**: `src/ai_voicebot/orchestrator.py`

**구현 위치**: `AIOrchestrator.end_call()`

```python
async def end_call(self):
    # ... 녹음 저장 ...
    
    # 지식 추출 (비동기, 백그라운드)
    if transcript:
        asyncio.create_task(
            self.extractor.extract_from_call(
                call_id=self.call_id,
                transcript_path=metadata.get("files", {}).get("transcript", ""),
                owner_id=self.callee,
                speaker="callee"  # 착신자 발화만 추출
            )
        )
```

**상태**: ✅ **작동 중**

---

### 4. 일반 SIP 통화 지식 추출 ✅ (구현 완료)
**파일**: `src/sip_core/call_manager.py`

**이전 상태**: ❌ 미구현

**신규 구현**: ✅ 완료

#### 4.1 CallManager 초기화 수정
```python
def __init__(
    self,
    # ... 기존 파라미터 ...
    knowledge_extractor = None,  # 신규 파라미터
):
    # ...
    self.knowledge_extractor = knowledge_extractor
    if knowledge_extractor:
        logger.info("Knowledge extraction enabled for regular calls")
```

#### 4.2 trigger_knowledge_extraction() 메서드 (신규)
**위치**: `src/sip_core/call_manager.py` (line 701-763)

**호출 경로**:
```
SIPEndpoint._cleanup_call()
    ↓
CallManager.trigger_knowledge_extraction()
    ↓ (5초 delay)
KnowledgeExtractor.extract_from_call()
```

**구현 내용**:
```python
async def trigger_knowledge_extraction(
    self,
    call_id: str,
    recording_dir_name: str,
    callee_username: str
) -> None:
    """Knowledge Extraction 트리거 (SIP Endpoint에서 호출)
    
    Args:
        call_id: 호 ID
        recording_dir_name: 녹음 디렉토리명
        callee_username: 착신자 사용자명
    """
    if not self.knowledge_extractor or not self.recording_enabled:
        return
    
    transcript_path = Path(f"./recordings/{recording_dir_name}/transcript.txt")
    callee_id = f"sip:{callee_username}@unknown"
    
    # STT 완료를 기다린 후 지식 추출 실행 (5초 delay)
    async def delayed_extraction():
        await asyncio.sleep(5)  # STT 완료 대기
        
        if not transcript_path.exists():
            logger.warning("Transcript file not found after delay")
            return
        
        await self.knowledge_extractor.extract_from_call(
            call_id=call_id,
            transcript_path=str(transcript_path),
            owner_id=callee_id,
            speaker="callee"  # 착신자 발화만 추출
        )
    
    asyncio.create_task(delayed_extraction())
```

**특징**:
- ✅ **5초 지연**: STT 후처리 완료 대기
- ✅ **비동기 실행**: 통화 종료를 블로킹하지 않음
- ✅ **에러 핸들링**: transcript 파일 없을 경우 안전하게 처리

#### 4.3 SIPEndpoint._cleanup_call()에서 호출
**위치**: `src/sip_core/sip_endpoint.py` (line 1682-1704)

**플로우**:
```python
async def _cleanup_call(self, call_id: str) -> None:
    # ... 녹음 종료 ...
    
    # ✅ Knowledge Extraction 트리거 (CallManager에 위임)
    if self._call_manager and recording_metadata:
        recording_dir_name = recording_metadata.get('dir_name')
        is_ai_call = call_info.get('is_ai_call', False)
        
        if recording_dir_name and not is_ai_call:
            # 일반 SIP 통화만 Knowledge Extraction 수행
            await self._call_manager.trigger_knowledge_extraction(
                call_id=original_call_id,
                recording_dir_name=recording_dir_name,
                callee_username=call_info.get('callee_username', 'unknown')
            )
```

**조건**:
- ✅ `recording_dir_name`이 존재해야 함
- ✅ `has_transcript` (transcript 존재)
- ✅ `is_ai_call == False` — AI 통화는 제외 (CallManager.ai_enabled_calls 또는 call_info.ai_mode_activated/is_ai_call로 판단)
- ✅ `knowledge_extractor`가 초기화되어 있어야 함
- ✅ `recording_enabled == True`

### 5. Knowledge extraction scope (human-only + HITL)

**Extraction runs only for**:
1. **Human-to-human calls**: caller ↔ callee; when the call ends, `_cleanup_call` runs and triggers extraction only when the call is not AI-handled (`is_ai_call` is false).
2. **HITL results**: When operators enter a response in the frontend and choose to save to the knowledge base, that is the only knowledge path for AI-handled calls.
   - **Flow**: Frontend → WebSocket `submit_hitl_response` or API → `HITLService.submit_response()` → when `save_to_kb=True` → `KnowledgeService.add_from_hitl(question, answer, ...)` → vector DB.

**AI-to-caller calls are excluded** from call-based extraction (no transcript → knowledge extraction from that call).

---

## ⚠️ 제한 사항 및 전제 조건

### 1. Transcript 생성 필요

**일반 SIP 통화에서 지식 추출이 작동하려면**:
- ✅ **전제 조건**: `transcript.txt` 파일이 존재해야 함
- ❌ **현재 문제**: SIPCallRecorder가 transcript를 생성하지 않음

**이유**:
- 일반 SIP 통화는 AI Orchestrator가 없음
- STT(Speech-to-Text)가 실행되지 않음
- RTP 패킷은 녹음되지만, 텍스트로 변환되지 않음

### 2. 해결 방안

#### 옵션 1: 후처리 STT (권장)
```python
# SIPCallRecorder에서 통화 종료 시 후처리 STT 실행
async def stop_recording(self, call_id):
    # ... WAV 파일 저장 ...
    
    # 후처리 STT (선택적)
    if self.stt_enabled:
        transcript = await self._transcribe_audio(
            audio_path=mixed_wav_path
        )
        
        # transcript.txt 저장
        transcript_path = call_dir / "transcript.txt"
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(transcript)
```

**장점**:
- ✅ 실시간 STT 부담 없음
- ✅ 녹음 파일을 이용하여 고품질 전사 가능
- ✅ Google Speech-to-Text API 사용 가능

**단점**:
- ❌ 추가 API 비용
- ❌ 처리 시간 지연 (몇 초 ~ 몇 분)

#### 옵션 2: 실시간 STT (고급)
```python
# RTP Relay에서 실시간 STT 실행
class RTPRelayWorker:
    def on_packet_received(self, socket_type, data, addr):
        # ... 녹음 패킷 전달 ...
        
        # 실시간 STT (선택적)
        if self.stt_enabled and not self.ai_mode:
            asyncio.create_task(
                self.stt_client.process_audio(
                    audio_data=data,
                    call_id=self.call_id
                )
            )
```

**장점**:
- ✅ 실시간 전사
- ✅ 즉시 지식 추출 가능

**단점**:
- ❌ 실시간 처리 부담
- ❌ 네트워크 대역폭 사용
- ❌ 구현 복잡도 높음

#### 옵션 3: 수동 업로드 (간단)
```python
# Frontend에서 수동으로 transcript 업로드
POST /api/calls/{call_id}/transcript
{
    "transcript": "발신자: 안녕하세요\n착신자: 네 안녕하세요..."
}

# 업로드 후 수동으로 지식 추출 트리거
POST /api/calls/{call_id}/extract-knowledge
```

**장점**:
- ✅ 가장 간단한 구현
- ✅ API 비용 없음
- ✅ 사용자가 직접 확인 가능

**단점**:
- ❌ 수동 작업 필요
- ❌ 확장성 낮음

---

## 📊 현재 구현 완성도

### 전체 시스템
| 구성 요소 | 상태 | 완성도 |
|-----------|------|--------|
| **KnowledgeExtractor** | ✅ 완전 구현 | 100% |
| **LLMClient.judge_usefulness** | ✅ 완전 구현 | 100% |
| **AI 통화 지식 추출** | ✅ 작동 중 | 100% |
| **일반 통화 지식 추출 트리거** | ✅ 완료 | 100% |
| **trigger_knowledge_extraction()** | ✅ 완료 | 100% |
| **SIPEndpoint._cleanup_call() 통합** | ✅ 완료 | 100% |
| **일반 통화 Transcript 생성** | ⚠️ 후처리 STT 필요 | 0% |

### 작동 시나리오

#### ✅ 시나리오 1: AI 통화 (AI 응대 모드)
```
1. User A가 User B에게 전화
2. User B 부재 → AI 응대 시작
   - 타이머 기반: no_answer_timeout (10초) 경과
   - 수동 설정: 웹에서 "부재중" 상태 설정
3. AI Orchestrator가 실시간 STT 실행
   └─> transcript.txt 생성 (실시간)
4. 통화 종료
5. AIOrchestrator.end_call() 호출
6. KnowledgeExtractor.extract_from_call() 즉시 호출
7. LLM 유용성 판단 (신뢰도 0.7 이상)
8. 텍스트 청킹 및 임베딩
9. VectorDB 저장 ✅
```

**AI 응대 모드 특징**:
- ✅ **실시간 STT**: 통화 중 실시간 전사
- ✅ **즉시 추출**: 통화 종료 후 바로 지식 추출 (지연 없음)
- ✅ **화자 분리**: STT Diarization으로 caller/callee 구분

#### ✅ 시나리오 2: 일반 SIP 통화 + 후처리 STT
```
1. User A가 User B에게 전화
2. User B가 직접 응답
3. SIPCallRecorder가 RTP 패킷 녹음
   └─> caller.wav, callee.wav, mixed.wav 생성
4. 통화 종료
5. SIPEndpoint._cleanup_call() 호출
6. SIPCallRecorder가 후처리 STT 실행
   └─> transcript.txt 생성 ✅
7. CallManager.trigger_knowledge_extraction() 호출
   └─> 5초 delay (STT 완료 대기)
8. KnowledgeExtractor.extract_from_call() 실행
9. LLM 유용성 판단
10. VectorDB 저장 ✅
```

**일반 SIP 통화 특징**:
- ✅ **후처리 STT**: 통화 종료 후 전사
- ✅ **5초 지연**: STT 완료 대기 후 추출
- ✅ **비동기 처리**: 통화 종료를 블로킹하지 않음

#### ⚠️ 시나리오 3: 일반 SIP 통화 (STT 미구현 시)
```
1. User A가 User B에게 전화
2. User B가 직접 응답
3. SIPCallRecorder가 RTP 패킷 녹음
   └─> caller.wav, callee.wav, mixed.wav 생성
   └─> ❌ transcript.txt 미생성
4. 통화 종료
5. CallManager.trigger_knowledge_extraction() 호출
6. 5초 delay 후 transcript.txt 확인
7. ❌ transcript.txt가 없어서 지식 추출 스킵
   └─> 로그: "Transcript file not found after delay"
```

---

## 🔧 추가 구현 필요 사항

### 1. SIPCallRecorder에 후처리 STT 추가
**파일**: `src/sip_core/sip_call_recorder.py`

**추가 메서드**:
```python
async def _transcribe_audio(
    self, 
    audio_path: Path,
    language: str = "ko-KR"
) -> str:
    """
    녹음 파일을 STT로 전사
    
    Args:
        audio_path: WAV 파일 경로
        language: 언어 코드
        
    Returns:
        전사 텍스트
    """
    # Google Speech-to-Text API 사용
    from google.cloud import speech
    
    client = speech.SpeechClient()
    
    with open(audio_path, 'rb') as f:
        audio = speech.RecognitionAudio(content=f.read())
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code=language,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=False
    )
    
    response = client.recognize(config=config, audio=audio)
    
    # 결과 조합
    transcript_lines = []
    for result in response.results:
        transcript_lines.append(result.alternatives[0].transcript)
    
    return '\n'.join(transcript_lines)
```

**stop_recording() 수정**:
```python
async def stop_recording(self, call_id: str) -> dict:
    # ... WAV 파일 저장 ...
    
    # 후처리 STT (선택적)
    if hasattr(self, 'stt_enabled') and self.stt_enabled:
        try:
            # Mixed audio에서 전사
            transcript = await self._transcribe_audio(mixed_path)
            
            # transcript.txt 저장
            transcript_path = call_dir / "transcript.txt"
            with open(transcript_path, 'w', encoding='utf-8') as f:
                # 형식: "화자: 텍스트"
                # 실제로는 화자 분리(diarization) 필요
                f.write(f"통화 내용:\n{transcript}")
            
            logger.info("Transcript generated",
                       call_id=call_id,
                       transcript_length=len(transcript))
        except Exception as e:
            logger.error("Transcription error",
                        call_id=call_id,
                        error=str(e))
    
    return metadata
```

### 2. CallManager 초기화 시 KnowledgeExtractor 전달
**파일**: `src/main.py` 또는 SIP PBX 초기화 코드

```python
# KnowledgeExtractor 생성
knowledge_extractor = KnowledgeExtractor(
    llm_client=llm_client,
    embedder=embedder,
    vector_db=vector_db,
    min_confidence=0.7
)

# CallManager 생성 시 전달
call_manager = CallManager(
    call_repository=call_repository,
    media_session_manager=media_session_manager,
    ai_orchestrator=ai_orchestrator,
    knowledge_extractor=knowledge_extractor,  # 신규
    recording_enabled=True
)
```

---

## 📈 예상 효과

### 1. 지식 베이스 자동 확장
- ✅ AI 통화뿐만 아니라 일반 통화에서도 지식 수집
- ✅ 더 많은 데이터로 RAG 품질 향상
- ✅ 사용자별 맞춤형 지식 베이스 구축

### 2. AI 응답 품질 향상
- ✅ 실제 통화 내용 기반 학습
- ✅ 자주 묻는 질문 자동 수집
- ✅ 개인 선호도 파악

### 3. 운영 효율성
- ✅ 수동 지식 입력 불필요
- ✅ 자동으로 최신 정보 유지
- ✅ 통화 이력 활용도 증가

---

## 🧪 테스트 시나리오

### 테스트 케이스 1: AI Attendant Timer Test
**목적**: 타이머 기반 AI 응대 모드에서 Knowledge Extraction 검증

**Given**:
- `no_answer_timeout = 10초`
- AI Orchestrator 초기화 완료
- KnowledgeExtractor 설정 완료

**When**:
- 발신자가 착신자에게 전화
- 착신자가 10초간 무응답

**Then**:
- AI가 자동으로 응답 시작
- 실시간 STT 실행 → `transcript.txt` 생성
- 통화 종료 후 `AIOrchestrator.end_call()` 호출
- `KnowledgeExtractor.extract_from_call()` 즉시 실행
- LLM 유용성 판단 수행
- VectorDB에 지식 저장

**검증 방법**:
```bash
# 로그 확인
grep "knowledge_extraction\|VectorDB Flow" logs/app.log

# VectorDB 확인
# ChromaDB 또는 Pinecone에서 해당 call_id로 검색
```

---

### 테스트 케이스 2: Manual Away Status Test
**목적**: 수동 부재중 설정 시 즉시 AI 응답 및 Knowledge Extraction 검증

**Given**:
- 웹에서 "부재중" 상태 설정
- `/api/operator/status` API 호출 완료

**When**:
- 전화 수신

**Then**:
- 즉시 AI가 응답 (타이머 대기 없음)
- 실시간 STT 실행
- 통화 종료 후 Knowledge Extraction 실행

**검증 방법**:
```bash
# 부재중 상태 확인
curl -X GET http://localhost:8000/api/operator/status

# 로그 확인
grep "callee_is_away\|ai_mode_activated" logs/app.log
```

---

### 테스트 케이스 3: Knowledge Extraction Test (일반 SIP 통화)
**목적**: 일반 SIP 통화에서 후처리 STT 및 Knowledge Extraction 검증

**Given**:
- 일반 SIP 통화 (AI 모드 아님)
- 후처리 STT 설정 완료
- `recording_enabled = True`

**When**:
- 통화 종료
- STT 후처리 완료 (약 3-5초 소요)

**Then**:
- `SIPEndpoint._cleanup_call()` 호출
- `CallManager.trigger_knowledge_extraction()` 호출
- 5초 delay 후 `transcript.txt` 확인
- `KnowledgeExtractor.extract_from_call()` 실행
- LLM 유용성 판단 및 VectorDB 저장

**검증 방법**:
```bash
# transcript 파일 확인
ls -la recordings/{call_id}/transcript.txt

# 로그 확인
grep "trigger_knowledge_extraction\|Knowledge Flow" logs/app.log

# VectorDB 확인
# 저장된 지식 검색
```

---

### 테스트 케이스 4: Knowledge Extraction 실패 케이스
**목적**: transcript 파일이 없을 때 안전한 처리 검증

**Given**:
- 일반 SIP 통화
- 후처리 STT 미설정 또는 실패

**When**:
- 통화 종료
- `trigger_knowledge_extraction()` 호출
- 5초 delay 후 `transcript.txt` 확인

**Then**:
- `transcript.txt` 파일 없음 감지
- 지식 추출 스킵 (에러 없음)
- 경고 로그 출력: "Transcript file not found after delay"

**검증 방법**:
```bash
# 로그 확인
grep "Transcript file not found" logs/app.log
```

---

## 📝 결론

### 현재 상태
- ✅ **설계서**: 명시되어 있음 (섹션 4.4)
- ✅ **KnowledgeExtractor**: 완전 구현 (100%)
- ✅ **LLM 유용성 판단**: 완전 구현 (100%)
- ✅ **AI 통화 지식 추출**: 작동 중 (100%)
- ✅ **일반 통화 트리거**: 구현 완료 (100%)
- ✅ **trigger_knowledge_extraction()**: 구현 완료 (100%)
- ✅ **SIPEndpoint._cleanup_call() 통합**: 완료 (100%)
- ⚠️ **일반 통화 Transcript 생성**: 후처리 STT 필요 (0%)

### AI 응대 모드 통합
- ✅ **타이머 기반**: `no_answer_timeout` 경과 시 자동 AI 응답
- ✅ **수동 설정**: 웹 API로 부재중 상태 설정 시 즉시 AI 응답
- ✅ **실시간 STT**: AI 응대 모드에서 실시간 전사
- ✅ **즉시 추출**: AI 통화 종료 후 지연 없이 지식 추출

### 권장 사항
1. **즉시**: 후처리 STT를 SIPCallRecorder에 추가
2. **단기**: CallManager 초기화 시 KnowledgeExtractor 주입 확인
3. **장기**: 실시간 STT + 화자 분리(diarization) 구현

### 다음 단계
1. SIPCallRecorder에 후처리 STT 추가
2. 테스트 시나리오 실행 및 검증
3. 성능 최적화 (병렬 처리)
4. 모니터링 및 메트릭 추가

---

**작성자**: Winston (Developer)  
**일자**: 2026-02-05  
**상태**: 분석 완료 + 트리거 구현 완료 + AI 응대 모드 통합 완료  
**다음**: Transcript 생성 구현 필요

