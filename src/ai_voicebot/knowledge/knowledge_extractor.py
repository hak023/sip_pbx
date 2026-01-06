"""
Knowledge Extractor

통화 녹음에서 유용한 지식을 추출하여 Vector DB에 저장
"""

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
        chunk_overlap: int = 50,
        min_text_length: int = 50
    ):
        """
        Args:
            llm_client: LLM 클라이언트
            embedder: 텍스트 임베더
            vector_db: Vector DB 클라이언트
            min_confidence: 최소 신뢰도 (유용성 판단)
            chunk_size: 청크 크기 (문자)
            chunk_overlap: 청크 오버랩 (문자)
            min_text_length: 최소 텍스트 길이
        """
        self.llm = llm_client
        self.embedder = embedder
        self.vector_db = vector_db
        self.min_confidence = min_confidence
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_text_length = min_text_length
        
        # 통계
        self.total_extractions = 0
        self.total_chunks_stored = 0
        
        logger.info("KnowledgeExtractor initialized",
                   min_confidence=min_confidence,
                   chunk_size=chunk_size)
    
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
                return {"success": False, "extracted_count": 0, "confidence": 0.0}
            
            # 2. 화자 필터링
            speaker_text = self._filter_by_speaker(transcript, speaker)
            if not speaker_text or len(speaker_text) < self.min_text_length:
                logger.info("Insufficient text from target speaker", 
                          call_id=call_id, 
                          speaker=speaker,
                          text_length=len(speaker_text) if speaker_text else 0)
                return {"success": False, "extracted_count": 0, "confidence": 0.0}
            
            # 3. LLM 유용성 판단
            judgment = await self.llm.judge_usefulness(
                transcript=speaker_text,
                speaker=speaker
            )
            
            if not judgment["is_useful"]:
                logger.info("Not useful content", 
                          call_id=call_id,
                          reason=judgment.get("reason", "N/A"))
                return {
                    "success": True, 
                    "extracted_count": 0, 
                    "confidence": judgment.get("confidence", 0.0)
                }
            
            if judgment["confidence"] < self.min_confidence:
                logger.info("Low confidence", 
                          call_id=call_id,
                          confidence=judgment["confidence"])
                return {
                    "success": True, 
                    "extracted_count": 0, 
                    "confidence": judgment["confidence"]
                }
            
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
            
            self.total_extractions += 1
            self.total_chunks_stored += stored_count
            
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
                        error=str(e),
                        exc_info=True)
            return {"success": False, "extracted_count": 0, "confidence": 0.0}
    
    async def _load_transcript(self, path: str) -> str:
        """
        전사 텍스트 로드
        
        Args:
            path: 파일 경로
            
        Returns:
            전사 텍스트
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("Transcript file not found", path=path)
            return ""
        except Exception as e:
            logger.error("Transcript load error", path=path, error=str(e))
            return ""
    
    def _filter_by_speaker(self, transcript: str, speaker: str) -> str:
        """
        화자별 발화 필터링
        
        형식 예시:
        발신자: 안녕하세요
        착신자: 네, 안녕하세요
        
        Args:
            transcript: 전사 텍스트
            speaker: 화자 (caller/callee)
            
        Returns:
            필터링된 텍스트
        """
        lines = transcript.split('\n')
        speaker_lines = []
        
        speaker_label = "착신자" if speaker == "callee" else "발신자"
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2 and parts[0].strip() == speaker_label:
                    text = parts[1].strip()
                    if text:
                        speaker_lines.append(text)
        
        return ' '.join(speaker_lines)
    
    def _chunk_text(self, text: str) -> List[str]:
        """
        텍스트 청킹 (오버랩 포함)
        
        Args:
            text: 원본 텍스트
            
        Returns:
            청크 리스트
        """
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
                    chunk.rfind('?'),
                    chunk.rfind('。')  # 한국어 마침표
                )
                if last_period > 0:
                    chunk = chunk[:last_period + 1]
                    end = start + last_period + 1
            
            chunk = chunk.strip()
            if chunk:
                chunks.append(chunk)
            
            # 다음 시작점 (오버랩 적용)
            start = end - self.chunk_overlap
            
            # 무한 루프 방지
            if start <= 0 or start >= len(text):
                break
        
        return chunks
    
    def get_stats(self) -> dict:
        """지식 추출 통계 반환"""
        avg_chunks = (
            self.total_chunks_stored / self.total_extractions 
            if self.total_extractions > 0 else 0
        )
        
        return {
            "total_extractions": self.total_extractions,
            "total_chunks_stored": self.total_chunks_stored,
            "avg_chunks_per_extraction": avg_chunks,
            "min_confidence": self.min_confidence,
            "chunk_size": self.chunk_size,
        }

