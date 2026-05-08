# AI 컴포넌트 구현 가이드 Part 2
> **클러스터 안내**: 세부·히스토리 설계 문서입니다. 통합 관점·경계는 아래 대표 문서를 우선 참고하세요.
> 
> **대표 문서**: [`ai-implementation-guide.md`](ai-implementation-guide.md)
>
---


이 문서는 Part 1의 연속입니다.

**Part 1 컴포넌트:** Audio Buffer, VAD, STT Client, TTS Client ✅
**Part 2 컴포넌트:** LLM Client, RAG Engine, Call Recorder, Knowledge Extractor

---

## 5. LLM Client (Gemini) 🆕

### 5.1 완전한 구현

파일 위치: `src/ai_voicebot/ai_pipeline/llm_client.py`

```python
import google.generativeai as genai
import asyncio
from typing import List, Dict, Optional
import structlog

logger = structlog.get_logger(__name__)


class LLMClient:
    """
    Google Gemini LLM Client
    
    대화 생성 및 지식 유용성 판단을 제공합니다.
    """
    
    def __init__(self, config: dict, api_key: str):
        """
        Args:
            config: LLM 설정
                - model: "gemini-2.5-flash"
                - temperature: 0.7
                - max_tokens: 200
            api_key: Google API 키
        """
        self.config = config
        
        # Gemini 설정
        genai.configure(api_key=api_key)
        
        self.model = genai.GenerativeModel(
            model_name=config.get("model", "gemini-2.5-flash")
        )
        
        self.generation_config = genai.types.GenerationConfig(
            temperature=config.get("temperature", 0.7),
            top_p=config.get("top_p", 0.8),
            top_k=config.get("top_k", 40),
            max_output_tokens=config.get("max_tokens", 200),
        )
        
        # 대화 히스토리
        self.conversation_history: List[Dict[str, str]] = []
        
        logger.info("LLMClient initialized", 
                   model=config.get("model"))
    
    async def generate_response(
        self, 
        user_text: str, 
        context_docs: List[str],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        사용자 입력에 대한 답변 생성
        
        Args:
            user_text: 사용자 질문
            context_docs: RAG 검색 결과 (관련 문서)
            system_prompt: 시스템 프롬프트 (선택)
            
        Returns:
            생성된 답변 텍스트
        """
        try:
            # 프롬프트 조립
            prompt = self._build_conversation_prompt(
                user_text, 
                context_docs, 
                system_prompt
            )
            
            # Gemini API 호출 (비동기)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=self.generation_config
                )
            )
            
            # 응답 텍스트 추출
            answer = response.text.strip()
            
            # 대화 히스토리 업데이트
            self.conversation_history.append({
                "role": "user",
                "content": user_text
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": answer
            })
            
            # 히스토리 제한 (최근 10턴)
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]
            
            logger.info("LLM response generated",
                       user_text_length=len(user_text),
                       response_length=len(answer))
            
            return answer
            
        except Exception as e:
            logger.error("LLM generation error", error=str(e))
            return "죄송합니다, 답변을 생성하는 중 오류가 발생했습니다."
    
    def _build_conversation_prompt(
        self, 
        user_text: str, 
        context_docs: List[str],
        system_prompt: Optional[str] = None
    ) -> str:
        """대화 프롬프트 조립"""
        # 기본 시스템 프롬프트
        if not system_prompt:
            system_prompt = (
                "당신은 친절하고 정확한 AI 비서입니다. "
                "제공된 정보를 기반으로 답변하고, "
                "모르는 내용은 솔직히 모른다고 답변하세요. "
                "답변은 1-2문장으로 간결하게 해주세요."
            )
        
        # 컨텍스트 문서
        context_str = ""
        if context_docs:
            context_str = "\n\n**참고 정보:**\n" + "\n".join([
                f"- {doc}" for doc in context_docs
            ])
        
        # 대화 히스토리
        history_str = ""
        if self.conversation_history:
            recent_history = self.conversation_history[-10:]  # 최근 5턴
            history_str = "\n\n**이전 대화:**\n" + "\n".join([
                f"{'사용자' if msg['role'] == 'user' else 'AI'}: {msg['content']}"
                for msg in recent_history
            ])
        
        # 전체 프롬프트
        prompt = f"""{system_prompt}
{context_str}
{history_str}

**현재 질문:**
사용자: {user_text}

AI:"""
        
        return prompt
    
    async def judge_usefulness(
        self, 
        transcript: str, 
        speaker: str = "callee"
    ) -> Dict[str, any]:
        """
        통화 내용의 유용성 판단 (지식 추출용)
        
        Args:
            transcript: 통화 전체 텍스트
            speaker: 화자 (caller/callee)
            
        Returns:
            {
                "is_useful": bool,
                "confidence": float,
                "reason": str,
                "extracted_info": List[Dict]
            }
        """
        try:
            prompt = f"""다음 통화 내용을 분석하여 향후 AI 비서가 활용할 수 있는 
유용한 정보가 있는지 판단하세요.

**유용한 정보 예시:**
- 약속 일정 (시간, 장소)
- 연락처 정보
- 업무 지시사항
- 자주 묻는 질문에 대한 답변
- 개인 선호도 (좋아하는 음식, 취미 등)

**통화 내용 ({speaker}):**
{transcript}

**출력 형식 (JSON):**
{{
  "is_useful": true/false,
  "confidence": 0.0-1.0,
  "reason": "판단 이유",
  "extracted_info": [
    {{
      "text": "추출할 텍스트",
      "category": "약속|정보|지시|선호도|기타",
      "keywords": ["키워드1", "키워드2"]
    }}
  ]
}}

JSON:"""
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,  # 더 결정론적
                        max_output_tokens=500
                    )
                )
            )
            
            # JSON 파싱
            import json
            result_text = response.text.strip()
            
            # JSON 추출 (```json ... ``` 제거)
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            
            logger.info("Usefulness judgment completed",
                       is_useful=result.get("is_useful"),
                       confidence=result.get("confidence"))
            
            return result
            
        except Exception as e:
            logger.error("Usefulness judgment error", error=str(e))
            return {
                "is_useful": False,
                "confidence": 0.0,
                "reason": f"Error: {str(e)}",
                "extracted_info": []
            }
    
    def clear_history(self):
        """대화 히스토리 초기화"""
        self.conversation_history.clear()
        logger.info("LLM conversation history cleared")
    
    def get_history(self) -> List[Dict[str, str]]:
        """대화 히스토리 반환"""
        return self.conversation_history.copy()


# 사용 예시
async def example_usage():
    """LLMClient 사용 예시"""
    import os
    
    config = {
        "model": "gemini-2.5-flash",
        "temperature": 0.7,
        "max_tokens": 200
    }
    
    api_key = os.getenv("GEMINI_API_KEY")
    llm = LLMClient(config, api_key)
    
    # 답변 생성
    context_docs = [
        "다음 주 월요일 오전 10시에 회의가 있습니다.",
        "회의 장소는 본사 3층 회의실입니다."
    ]
    
    answer = await llm.generate_response(
        user_text="다음 주 회의 시간이 언제인가요?",
        context_docs=context_docs
    )
    print(f"AI: {answer}")
    
    # 유용성 판단
    transcript = """
    발신자: 다음 주 월요일 오전 10시에 회의 있죠?
    착신자: 네, 맞습니다. 본사 3층 회의실에서 뵙겠습니다.
    """
    
    judgment = await llm.judge_usefulness(transcript, speaker="callee")
    if judgment["is_useful"]:
        print(f"유용한 정보: {judgment['extracted_info']}")
```

---

## 6. RAG Engine 🆕

### 6.1 완전한 구현

파일 위치: `src/ai_voicebot/ai_pipeline/rag_engine.py`

```python
from typing import List, Dict, Optional
from dataclasses import dataclass
import asyncio
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Document:
    """검색된 문서"""
    id: str
    text: str
    score: float
    metadata: Dict


class RAGEngine:
    """
    RAG (Retrieval-Augmented Generation) Engine
    
    Vector DB 검색 및 컨텍스트 재순위화를 제공합니다.
    """
    
    def __init__(
        self, 
        vector_db,  # VectorDB 인스턴스
        embedder,   # TextEmbedder 인스턴스
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        reranking_enabled: bool = False
    ):
        """
        Args:
            vector_db: Vector DB 클라이언트
            embedder: Text Embedder 인스턴스
            top_k: 검색할 문서 수
            similarity_threshold: 유사도 임계값
            reranking_enabled: 재순위화 활성화
        """
        self.vector_db = vector_db
        self.embedder = embedder
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.reranking_enabled = reranking_enabled
        
        logger.info("RAGEngine initialized", 
                   top_k=top_k,
                   threshold=similarity_threshold)
    
    async def search(
        self, 
        query: str, 
        owner_filter: Optional[str] = None
    ) -> List[Document]:
        """
        질문에 대한 관련 문서 검색
        
        Args:
            query: 검색 질문
            owner_filter: 사용자 ID 필터 (착신자 전용 지식)
            
        Returns:
            관련 문서 리스트 (상위 top_k개)
        """
        try:
            # 1. 질문 임베딩
            query_embedding = await self.embedder.embed(query)
            
            # 2. Vector DB 검색
            search_results = await self.vector_db.search(
                vector=query_embedding,
                top_k=self.top_k * 2,  # 재순위화를 위해 더 많이 검색
                filter={"owner": owner_filter} if owner_filter else None
            )
            
            # 3. Document 객체 변환
            documents = [
                Document(
                    id=result["id"],
                    text=result["text"],
                    score=result["score"],
                    metadata=result.get("metadata", {})
                )
                for result in search_results
            ]
            
            # 4. 유사도 필터링
            documents = [
                doc for doc in documents
                if doc.score >= self.similarity_threshold
            ]
            
            # 5. 재순위화 (선택)
            if self.reranking_enabled and documents:
                documents = await self._rerank(query, documents)
            
            # 6. Top-K 반환
            documents = documents[:self.top_k]
            
            logger.info("RAG search completed",
                       query_length=len(query),
                       results_count=len(documents))
            
            return documents
            
        except Exception as e:
            logger.error("RAG search error", error=str(e))
            return []
    
    async def _rerank(
        self, 
        query: str, 
        documents: List[Document]
    ) -> List[Document]:
        """
        검색 결과 재순위화
        
        단순 벡터 유사도가 아닌 실제 관련성 기반 재순위화
        (여기서는 간단히 길이와 키워드 매칭으로 구현)
        """
        try:
            # 질문의 주요 키워드 추출
            query_words = set(query.lower().split())
            
            # 각 문서의 재순위 점수 계산
            for doc in documents:
                doc_words = set(doc.text.lower().split())
                
                # 키워드 매칭 비율
                overlap = len(query_words & doc_words)
                keyword_score = overlap / len(query_words) if query_words else 0
                
                # 문서 길이 패널티 (너무 길면 감점)
                length_score = 1.0 if len(doc.text) < 300 else 0.8
                
                # 최종 점수 (원래 점수 70% + 키워드 20% + 길이 10%)
                doc.score = (
                    doc.score * 0.7 +
                    keyword_score * 0.2 +
                    length_score * 0.1
                )
            
            # 재정렬
            documents.sort(key=lambda d: d.score, reverse=True)
            
            logger.debug("Reranking completed", count=len(documents))
            return documents
            
        except Exception as e:
            logger.error("Reranking error", error=str(e))
            return documents
    
    async def search_with_expansion(
        self, 
        query: str, 
        owner_filter: Optional[str] = None
    ) -> List[Document]:
        """
        쿼리 확장을 사용한 검색 (고급)
        
        원본 쿼리 + 확장된 쿼리로 검색하여 더 많은 결과 확보
        """
        # 원본 검색
        original_results = await self.search(query, owner_filter)
        
        # 쿼리 확장 (동의어, 관련어)
        expanded_query = await self._expand_query(query)
        
        if expanded_query != query:
            # 확장된 쿼리로 검색
            expanded_results = await self.search(expanded_query, owner_filter)
            
            # 결과 병합 (중복 제거)
            seen_ids = {doc.id for doc in original_results}
            for doc in expanded_results:
                if doc.id not in seen_ids:
                    original_results.append(doc)
                    seen_ids.add(doc.id)
            
            # 재정렬
            original_results.sort(key=lambda d: d.score, reverse=True)
            original_results = original_results[:self.top_k]
        
        return original_results
    
    async def _expand_query(self, query: str) -> str:
        """
        쿼리 확장 (간단한 동의어 치환)
        
        실제로는 LLM을 사용하거나 한국어 동의어 사전 활용 가능
        """
        # 간단한 동의어 매핑
        synonyms = {
            "회의": ["미팅", "회의", "모임"],
            "시간": ["시간", "시각", "타임"],
            "장소": ["장소", "위치", "곳"],
        }
        
        expanded = query
        for word, syns in synonyms.items():
            if word in query:
                # 첫 번째 동의어로 치환
                expanded = query.replace(word, syns[0])
                break
        
        return expanded


# 사용 예시
async def example_usage():
    """RAGEngine 사용 예시"""
    from src.ai_voicebot.knowledge.vector_db import ChromaDBClient
    from src.ai_voicebot.knowledge.embedder import TextEmbedder
    
    # 초기화
    vector_db = ChromaDBClient()
    embedder = TextEmbedder()
    
    rag = RAGEngine(
        vector_db=vector_db,
        embedder=embedder,
        top_k=3,
        similarity_threshold=0.7
    )
    
    # 검색
    query = "다음 주 회의 시간이 언제인가요?"
    documents = await rag.search(
        query=query,
        owner_filter="user_1004"  # 착신자 전용
    )
    
    # 결과 출력
    for i, doc in enumerate(documents, 1):
        print(f"{i}. (점수: {doc.score:.2f}) {doc.text}")
    
    # LLM에 전달
    context_docs = [doc.text for doc in documents]
    answer = await llm.generate_response(query, context_docs)
```

---

## 7. Call Recorder 🆕

### 7.1 완전한 구현

파일 위치: `src/ai_voicebot/recording/recorder.py`

```python
import asyncio
import wave
import os
from pathlib import Path
from typing import Optional
from datetime import datetime
import json
import structlog

logger = structlog.get_logger(__name__)


class CallRecorder:
    """
    통화 녹음 및 저장
    
    - 양방향 RTP 스트림 녹음
    - 화자 분리 (caller/callee 별도 WAV)
    - 믹싱 (단일 WAV)
    - 메타데이터 저장
    """
    
    def __init__(
        self,
        output_dir: str = "./recordings",
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2  # 16-bit
    ):
        """
        Args:
            output_dir: 녹음 파일 저장 디렉토리
            sample_rate: 샘플레이트 (Hz)
            channels: 채널 수 (1=mono)
            sample_width: 샘플 너비 (bytes, 2=16-bit)
        """
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        
        # 녹음 버퍼
        self.caller_buffer: list[bytes] = []
        self.callee_buffer: list[bytes] = []
        self.mixed_buffer: list[bytes] = []
        
        # 녹음 상태
        self.is_recording = False
        self.call_id: Optional[str] = None
        self.start_time: Optional[datetime] = None
        
        # 출력 디렉토리 생성
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("CallRecorder initialized", 
                   output_dir=str(self.output_dir))
    
    def start_recording(self, call_id: str):
        """녹음 시작"""
        if self.is_recording:
            logger.warning("Already recording", call_id=self.call_id)
            return
        
        self.is_recording = True
        self.call_id = call_id
        self.start_time = datetime.now()
        
        # 버퍼 초기화
        self.caller_buffer.clear()
        self.callee_buffer.clear()
        self.mixed_buffer.clear()
        
        logger.info("Recording started", call_id=call_id)
    
    def add_caller_audio(self, audio_data: bytes):
        """발신자 오디오 추가"""
        if not self.is_recording:
            return
        
        self.caller_buffer.append(audio_data)
        
        # 믹싱 버퍼에도 추가 (caller 채널)
        self._add_to_mixed(audio_data, is_caller=True)
    
    def add_callee_audio(self, audio_data: bytes):
        """착신자 오디오 추가"""
        if not self.is_recording:
            return
        
        self.callee_buffer.append(audio_data)
        
        # 믹싱 버퍼에도 추가 (callee 채널)
        self._add_to_mixed(audio_data, is_caller=False)
    
    def _add_to_mixed(self, audio_data: bytes, is_caller: bool):
        """믹싱 버퍼에 오디오 추가"""
        # 간단한 믹싱: 그냥 append (실제로는 시간 동기화 필요)
        # TODO: 타임스탬프 기반 동기화
        self.mixed_buffer.append(audio_data)
    
    async def stop_recording(self) -> dict:
        """
        녹음 중지 및 파일 저장
        
        Returns:
            저장된 파일 정보 dict
        """
        if not self.is_recording:
            logger.warning("Not recording")
            return {}
        
        self.is_recording = False
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        
        # 저장 디렉토리 생성 (call_id별)
        call_dir = self.output_dir / self.call_id
        call_dir.mkdir(parents=True, exist_ok=True)
        
        # 파일 경로
        caller_path = call_dir / "caller.wav"
        callee_path = call_dir / "callee.wav"
        mixed_path = call_dir / "mixed.wav"
        metadata_path = call_dir / "metadata.json"
        
        # WAV 파일 저장
        await asyncio.gather(
            self._save_wav(caller_path, self.caller_buffer),
            self._save_wav(callee_path, self.callee_buffer),
            self._save_wav(mixed_path, self.mixed_buffer)
        )
        
        # 메타데이터 저장
        metadata = {
            "call_id": self.call_id,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "files": {
                "caller": str(caller_path),
                "callee": str(callee_path),
                "mixed": str(mixed_path)
            }
        }
        
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        logger.info("Recording saved",
                   call_id=self.call_id,
                   duration=duration,
                   caller_frames=len(self.caller_buffer),
                   callee_frames=len(self.callee_buffer))
        
        # 버퍼 정리
        self.caller_buffer.clear()
        self.callee_buffer.clear()
        self.mixed_buffer.clear()
        
        return metadata
    
    async def _save_wav(self, filepath: Path, audio_buffer: list[bytes]):
        """WAV 파일 저장"""
        try:
            # 비동기 파일 쓰기
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._write_wav_file,
                filepath,
                audio_buffer
            )
            
            logger.debug("WAV file saved", path=str(filepath))
            
        except Exception as e:
            logger.error("WAV save error", path=str(filepath), error=str(e))
    
    def _write_wav_file(self, filepath: Path, audio_buffer: list[bytes]):
        """WAV 파일 쓰기 (동기)"""
        with wave.open(str(filepath), 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            
            # 모든 오디오 데이터 쓰기
            for audio_data in audio_buffer:
                wav_file.writeframes(audio_data)


# 사용 예시
async def example_usage():
    """CallRecorder 사용 예시"""
    recorder = CallRecorder(output_dir="./recordings")
    
    # 녹음 시작
    recorder.start_recording(call_id="call_123")
    
    # 통화 중 오디오 추가
    while in_call:
        # RTP 패킷 수신
        caller_audio = await receive_caller_rtp()
        callee_audio = await receive_callee_rtp()
        
        recorder.add_caller_audio(caller_audio)
        recorder.add_callee_audio(callee_audio)
    
    # 녹음 중지 및 저장
    metadata = await recorder.stop_recording()
    print(f"Saved: {metadata['files']}")
```

---

## 8. Knowledge Extractor 🆕

### 8.1 완전한 구현

파일 위치: `src/ai_voicebot/knowledge/knowledge_extractor.py`

```python
from typing import List, Dict
import asyncio
from pathlib import Path
import json
import structlog

logger = structlog.get_logger(__name__)


class KnowledgeExtractor:
    """
    통화 녹음에서 유용한 지식을 추출하여 Vector DB에 저장
    
    워크플로우:
    1. 녹음 파일 로드
    2. 전사 텍스트 로드
    3. LLM 유용성 판단
    4. 텍스트 청킹
    5. 임베딩 생성
    6. Vector DB 저장
    """
    
    def __init__(
        self,
        llm_client,      # LLMClient 인스턴스
        embedder,        # TextEmbedder 인스턴스
        vector_db,       # VectorDB 인스턴스
        min_confidence: float = 0.7,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        """
        Args:
            llm_client: LLM 클라이언트
            embedder: 텍스트 임베더
            vector_db: Vector DB 클라이언트
            min_confidence: 최소 신뢰도 (유용성 판단)
            chunk_size: 청크 크기 (문자)
            chunk_overlap: 청크 오버랩 (문자)
        """
        self.llm = llm_client
        self.embedder = embedder
        self.vector_db = vector_db
        self.min_confidence = min_confidence
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        logger.info("KnowledgeExtractor initialized",
                   min_confidence=min_confidence)
    
    async def extract_from_call(
        self, 
        call_id: str,
        transcript_path: str,
        owner_id: str,
        speaker: str = "callee"
    ) -> Dict:
        """
        통화에서 지식 추출
        
        Args:
            call_id: 통화 ID
            transcript_path: 전사 텍스트 파일 경로
            owner_id: 소유자 ID (착신자 ID)
            speaker: 추출 대상 화자 (caller/callee)
            
        Returns:
            {
                "success": bool,
                "extracted_count": int,
                "confidence": float
            }
        """
        try:
            # 1. 전사 텍스트 로드
            transcript = await self._load_transcript(transcript_path)
            if not transcript:
                logger.warning("Empty transcript", call_id=call_id)
                return {"success": False, "extracted_count": 0}
            
            # 2. 화자 필터링 (callee 발화만)
            speaker_text = self._filter_by_speaker(transcript, speaker)
            if not speaker_text:
                logger.info("No text from target speaker", 
                          call_id=call_id, 
                          speaker=speaker)
                return {"success": False, "extracted_count": 0}
            
            # 3. LLM 유용성 판단
            judgment = await self.llm.judge_usefulness(
                transcript=speaker_text,
                speaker=speaker
            )
            
            if not judgment["is_useful"]:
                logger.info("Not useful content", 
                          call_id=call_id,
                          reason=judgment["reason"])
                return {"success": True, "extracted_count": 0}
            
            if judgment["confidence"] < self.min_confidence:
                logger.info("Low confidence", 
                          call_id=call_id,
                          confidence=judgment["confidence"])
                return {"success": True, "extracted_count": 0}
            
            # 4. 유용한 정보 추출
            extracted_info = judgment.get("extracted_info", [])
            if not extracted_info:
                # LLM이 구체적 정보를 추출하지 못한 경우, 전체 텍스트 청킹
                extracted_info = [
                    {
                        "text": speaker_text,
                        "category": "기타",
                        "keywords": []
                    }
                ]
            
            # 5. 청킹 및 임베딩
            stored_count = 0
            for idx, info in enumerate(extracted_info):
                text = info["text"]
                chunks = self._chunk_text(text)
                
                for chunk_idx, chunk in enumerate(chunks):
                    # 임베딩 생성
                    embedding = await self.embedder.embed(chunk)
                    
                    # Vector DB 저장
                    doc_id = f"{call_id}_chunk_{idx}_{chunk_idx}"
                    metadata = {
                        "call_id": call_id,
                        "owner": owner_id,
                        "speaker": speaker,
                        "category": info.get("category", "기타"),
                        "keywords": info.get("keywords", []),
                        "chunk_index": chunk_idx,
                        "confidence": judgment["confidence"]
                    }
                    
                    await self.vector_db.upsert(
                        doc_id=doc_id,
                        embedding=embedding,
                        text=chunk,
                        metadata=metadata
                    )
                    
                    stored_count += 1
            
            logger.info("Knowledge extracted and stored",
                       call_id=call_id,
                       chunks_stored=stored_count,
                       confidence=judgment["confidence"])
            
            return {
                "success": True,
                "extracted_count": stored_count,
                "confidence": judgment["confidence"]
            }
            
        except Exception as e:
            logger.error("Knowledge extraction error", 
                        call_id=call_id, 
                        error=str(e))
            return {"success": False, "extracted_count": 0}
    
    async def _load_transcript(self, path: str) -> str:
        """전사 텍스트 로드"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error("Transcript load error", path=path, error=str(e))
            return ""
    
    def _filter_by_speaker(self, transcript: str, speaker: str) -> str:
        """화자별 발화 필터링"""
        # 간단한 파싱 (형식: "화자: 텍스트")
        lines = transcript.split('\n')
        speaker_lines = []
        
        speaker_label = "착신자" if speaker == "callee" else "발신자"
        
        for line in lines:
            if line.startswith(f"{speaker_label}:"):
                text = line.split(':', 1)[1].strip()
                speaker_lines.append(text)
        
        return ' '.join(speaker_lines)
    
    def _chunk_text(self, text: str) -> List[str]:
        """텍스트 청킹 (오버랩 포함)"""
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            
            # 문장 경계에서 자르기 (마침표, 느낌표, 물음표)
            if end < len(text):
                last_period = max(
                    chunk.rfind('.'),
                    chunk.rfind('!'),
                    chunk.rfind('?')
                )
                if last_period > 0:
                    chunk = chunk[:last_period + 1]
                    end = start + last_period + 1
            
            chunks.append(chunk.strip())
            
            # 다음 시작점 (오버랩 적용)
            start = end - self.chunk_overlap
        
        return chunks


# 사용 예시
async def example_usage():
    """KnowledgeExtractor 사용 예시"""
    from src.ai_voicebot.ai_pipeline.llm_client import LLMClient
    from src.ai_voicebot.knowledge.embedder import TextEmbedder
    from src.ai_voicebot.knowledge.vector_db import ChromaDBClient
    
    # 초기화
    llm = LLMClient(config, api_key)
    embedder = TextEmbedder()
    vector_db = ChromaDBClient()
    
    extractor = KnowledgeExtractor(
        llm_client=llm,
        embedder=embedder,
        vector_db=vector_db,
        min_confidence=0.7
    )
    
    # 통화에서 지식 추출
    result = await extractor.extract_from_call(
        call_id="call_123",
        transcript_path="./recordings/call_123/transcript.txt",
        owner_id="user_1004",
        speaker="callee"
    )
    
    if result["success"]:
        print(f"Extracted {result['extracted_count']} knowledge chunks")
```

---

## 9. 통합 예시

### 9.1 전체 흐름 통합

파일 위치: `src/ai_voicebot/orchestrator.py` 수정

```python
# AI Orchestrator에서 모든 컴포넌트 통합 사용

from .audio_buffer import AudioBuffer
from .vad_detector import VADDetector
from .ai_pipeline.stt_client import STTClient
from .ai_pipeline.tts_client import TTSClient
from .ai_pipeline.llm_client import LLMClient
from .ai_pipeline.rag_engine import RAGEngine
from .recording.recorder import CallRecorder
from .knowledge.knowledge_extractor import KnowledgeExtractor

class AIOrchestrator:
    def __init__(self, config):
        # 컴포넌트 초기화
        self.audio_buffer = AudioBuffer(config.audio_buffer)
        self.vad = VADDetector(config.vad)
        self.stt = STTClient(config.stt)
        self.tts = TTSClient(config.tts)
        self.llm = LLMClient(config.llm, api_key)
        self.rag = RAGEngine(vector_db, embedder, config.rag)
        self.recorder = CallRecorder(config.recording)
        self.extractor = KnowledgeExtractor(
            self.llm, embedder, vector_db, config.knowledge
        )
    
    async def handle_call(self, call_id, caller_info):
        # 녹음 시작
        self.recorder.start_recording(call_id)
        
        # 오디오 버퍼 시작
        await self.audio_buffer.start()
        
        # STT 스트리밍 시작
        await self.stt.start_stream(self.on_stt_result)
        
        # 인사말 재생
        await self.play_greeting()
    
    async def on_audio_packet(self, rtp_packet):
        # 녹음
        if rtp_packet.direction == "caller":
            self.recorder.add_caller_audio(rtp_packet.payload)
        
        # 버퍼링
        await self.audio_buffer.add_packet(rtp_packet)
        
        # 프레임 가져오기
        frame = await self.audio_buffer.get_frame()
        if frame:
            # VAD 검사
            is_speech = self.vad.detect(frame)
            
            # Barge-in 확인
            if self.vad.is_barge_in() and self.is_speaking:
                await self.stop_speaking()
            
            # STT로 전송
            await self.stt.send_audio(frame)
    
    async def generate_and_speak_response(self, user_text):
        # RAG 검색
        documents = await self.rag.search(user_text, owner_filter=self.callee_id)
        context_docs = [doc.text for doc in documents]
        
        # LLM 답변 생성
        response_text = await self.llm.generate_response(user_text, context_docs)
        
        # TTS 재생
        await self.speak(response_text)
    
    async def stop_call(self):
        # STT 중지
        await self.stt.stop_stream()
        
        # 오디오 버퍼 중지
        await self.audio_buffer.stop()
        
        # 녹음 저장
        metadata = await self.recorder.stop_recording()
        
        # 지식 추출 (비동기, 백그라운드)
        asyncio.create_task(
            self.extractor.extract_from_call(
                call_id=self.call_id,
                transcript_path=metadata["transcript_path"],
                owner_id=self.callee_id
            )
        )
```

---

## 10. 테스트 가이드

### 10.1 통합 테스트

```python
# tests/integration/test_ai_workflow.py

@pytest.mark.asyncio
async def test_full_ai_conversation_flow():
    """전체 AI 대화 흐름 통합 테스트"""
    
    # 1. 컴포넌트 초기화
    config = load_test_config()
    orchestrator = AIOrchestrator(config)
    
    # 2. 통화 시작
    await orchestrator.handle_call(
        call_id="test_call_001",
        caller_info={"caller": "1004", "callee": "1008"}
    )
    
    # 3. 오디오 전송 시뮬레이션
    test_audio = load_test_audio("test_question.wav")
    await orchestrator.on_audio_packet(test_audio)
    
    # 4. 응답 대기
    await asyncio.sleep(5)
    
    # 5. 녹음 확인
    recordings = list(Path("./recordings/test_call_001").glob("*.wav"))
    assert len(recordings) == 3  # caller, callee, mixed
    
    # 6. 통화 종료
    await orchestrator.stop_call()
```

---

**구현 가이드 완료! 🎉**

이제 모든 8개 컴포넌트의 상세 구현이 완료되었습니다.

