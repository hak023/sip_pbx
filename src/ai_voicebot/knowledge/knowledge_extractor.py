"""
Knowledge Extractor

통화 녹음에서 지식정보를 정제(추출·분류)하여 Vector DB에 저장.
§7 PII 파이프라인: contains_pii인 항목은 검토 대기열에만 적재(선택).
"""

from typing import List, Dict, Optional
import asyncio
from pathlib import Path
import json
import structlog

logger = structlog.get_logger(__name__)


class KnowledgeExtractor:
    """
    통화 녹음에서 지식정보를 정제(추출·분류)하여 Vector DB에 저장.

    워크플로우:
    1. 녹음 파일 로드
    2. 전사 텍스트 로드
    3. LLM 지식 정제 (통화에서 저장할 지식 단위 추출·분류)
    4. 텍스트 청킹
    5. 임베딩 생성
    6. Vector DB 저장 (contains_pii이고 pii_review_queue_enabled이면 검토 대기열에만 저장)
    """
    
    def __init__(
        self,
        llm_client,      # LLMClient 인스턴스
        embedder,        # TextEmbedder 인스턴스
        vector_db,       # VectorDB 인스턴스
        min_confidence: float = 0.7,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_text_length: int = 10,  # ✅ 50 → 10 (짧은 대화도 저장)
        pii_review_queue_enabled: bool = False,
        extraction_pending_file: Optional[str] = None,
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
        self.pii_review_queue_enabled = pii_review_queue_enabled
        self._pending_store = None
        if pii_review_queue_enabled:
            from src.services.extraction_review_store import get_extraction_review_store
            self._pending_store = get_extraction_review_store(extraction_pending_file)
        
        # 통계
        self.total_extractions = 0
        self.total_chunks_stored = 0
        
        logger.info("KnowledgeExtractor initialized",
                   min_confidence=min_confidence,
                   chunk_size=chunk_size,
                   pii_review_queue_enabled=pii_review_queue_enabled)
    
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
            logger.info("🔄 [VectorDB Flow] Step 1/6: Knowledge extraction started",
                       call_id=call_id,
                       owner_id=owner_id,
                       speaker=speaker,
                       transcript_path=transcript_path)
            
            # 1. 전사 텍스트 로드
            logger.info("🔄 [VectorDB Flow] Step 2/6: Loading transcript", 
                       call_id=call_id,
                       path=transcript_path)
            
            transcript = await self._load_transcript(transcript_path)
            if not transcript:
                logger.warning("❌ [VectorDB Flow] Empty transcript - Aborting", call_id=call_id)
                return {"success": False, "extracted_count": 0, "confidence": 0.0}
            
            logger.info("✅ [VectorDB Flow] Transcript loaded", 
                       call_id=call_id,
                       transcript_length=len(transcript),
                       preview=transcript[:100] + "..." if len(transcript) > 100 else transcript)
            
            # 2. 화자 필터링 (또는 전체 대화 사용)
            logger.info("🔄 [VectorDB Flow] Step 3/6: Filtering by speaker",
                       call_id=call_id,
                       target_speaker=speaker)
            
            if speaker == "both" or speaker == "all":
                # 발신자+착신자 모두 사용
                speaker_text = transcript
                logger.info("✅ [VectorDB Flow] Using full conversation (both speakers)",
                           call_id=call_id,
                           text_length=len(speaker_text))
            else:
                # 특정 화자만 필터링
                speaker_text = self._filter_by_speaker(transcript, speaker)
            if not speaker_text or len(speaker_text) < self.min_text_length:
                logger.warning("❌ [VectorDB Flow] Insufficient text from target speaker - Aborting", 
                          call_id=call_id, 
                          speaker=speaker,
                          text_length=len(speaker_text) if speaker_text else 0,
                          min_required=self.min_text_length)
                return {"success": False, "extracted_count": 0, "confidence": 0.0}
            
            logger.info("✅ [VectorDB Flow] Speaker text filtered",
                       call_id=call_id,
                       filtered_length=len(speaker_text),
                       preview=speaker_text[:100] + "..." if len(speaker_text) > 100 else speaker_text)
            
            # 3. LLM 지식 정제 — 설계서: 맥락 파악을 위해 전체 전사(발신자+착신자) 전달, 저장 후보는 착신자만
            logger.info("🔄 [VectorDB Flow] Step 4/6: LLM refining knowledge (full transcript for context)",
                       call_id=call_id)
            
            judgment = await self.llm.judge_usefulness(
                transcript=transcript,
                speaker=speaker,
                call_id=call_id,
            )
            
            logger.info("✅ [VectorDB Flow] LLM knowledge refinement completed",
                       call_id=call_id,
                       is_useful=judgment["is_useful"],
                       confidence=judgment.get("confidence", 0.0),
                       reason=judgment.get("reason", "N/A"))
            
            if not judgment["is_useful"]:
                logger.info("❌ [VectorDB Flow] Content not useful - Skipping storage", 
                          call_id=call_id,
                          reason=judgment.get("reason", "N/A"))
                return {
                    "success": True, 
                    "extracted_count": 0, 
                    "confidence": judgment.get("confidence", 0.0)
                }
            
            if judgment["confidence"] < self.min_confidence:
                logger.info("❌ [VectorDB Flow] Low confidence - Skipping storage", 
                          call_id=call_id,
                          confidence=judgment["confidence"],
                          min_required=self.min_confidence)
                return {
                    "success": True, 
                    "extracted_count": 0, 
                    "confidence": judgment["confidence"]
                }
            
            # 4. 유용한 정보 추출
            extracted_info = judgment.get("extracted_info", [])
            if not extracted_info:
                # LLM이 구체적 정보를 추출하지 못한 경우, 전체 텍스트 청킹
                logger.info("🔄 [VectorDB Flow] No specific info extracted, using full text",
                           call_id=call_id)
                extracted_info = [
                    {
                        "text": speaker_text,
                        "category": "기타",
                        "keywords": []
                    }
                ]
            else:
                logger.info("🔄 [VectorDB Flow] Extracted specific info",
                           call_id=call_id,
                           info_count=len(extracted_info))
            
            # 5. 청킹 및 임베딩
            logger.info("🔄 [VectorDB Flow] Step 5/6: Chunking and embedding",
                       call_id=call_id,
                       chunk_size=self.chunk_size,
                       chunk_overlap=self.chunk_overlap)
            
            stored_count = 0
            for idx, info in enumerate(extracted_info):
                text = info["text"]
                chunks = self._chunk_text(text)
                contains_pii = info.get("contains_pii", False)
                category = info.get("category", "기타")
                keywords = info.get("keywords", [])
                
                logger.info(f"  📄 Processing info block {idx + 1}/{len(extracted_info)}",
                           call_id=call_id,
                           chunks_count=len(chunks),
                           category=category,
                           contains_pii=contains_pii)
                
                # §7 PII 파이프라인: contains_pii이고 검토 대기열 사용 시 VectorDB 건너뛰고 대기열에만 적재
                if contains_pii and self.pii_review_queue_enabled and self._pending_store:
                    for chunk_idx, chunk in enumerate(chunks):
                        await self._pending_store.add(
                            call_id=call_id,
                            owner=owner_id,
                            speaker=speaker,
                            text=chunk,
                            category=category,
                            keywords=keywords if isinstance(keywords, list) else (keywords.split(",") if isinstance(keywords, str) else []),
                            contains_pii=True,
                            confidence=float(judgment.get("confidence", 0)),
                            chunk_index=chunk_idx,
                        )
                        stored_count += 1
                    continue
                
                for chunk_idx, chunk in enumerate(chunks):
                    # 임베딩 생성
                    logger.debug(f"    🔢 Generating embedding for chunk {chunk_idx + 1}/{len(chunks)}",
                                call_id=call_id,
                                chunk_preview=chunk[:50] + "...")
                    
                    embedding = await self.embedder.embed(chunk)
                    
                    # Vector DB 저장
                    doc_id = f"{call_id}_chunk_{idx}_{chunk_idx}"
                    metadata = {
                        "call_id": call_id,
                        "owner": owner_id,
                        "speaker": speaker,
                        "category": category,
                        "keywords": keywords,
                        "chunk_index": chunk_idx,
                        "confidence": judgment["confidence"],
                        "contains_pii": contains_pii,
                        "extraction_source": "call",
                    }
                    
                    logger.info(f"🔄 [VectorDB Flow] Step 6/6: Storing chunk {stored_count + 1} to VectorDB",
                               call_id=call_id,
                               doc_id=doc_id,
                               embedding_dim=len(embedding) if embedding else 0,
                               metadata_keys=list(metadata.keys()))
                    
                    await self.vector_db.upsert(
                        doc_id=doc_id,
                        embedding=embedding,
                        text=chunk,
                        metadata=metadata
                    )
                    
                    stored_count += 1
                    
                    logger.info(f"  ✅ Chunk {stored_count} stored successfully",
                               call_id=call_id,
                               doc_id=doc_id)
            
            self.total_extractions += 1
            self.total_chunks_stored += stored_count
            
            logger.info("🎉 [VectorDB Flow] ✅ Knowledge extraction COMPLETED!",
                       call_id=call_id,
                       total_chunks_stored=stored_count,
                       confidence=judgment["confidence"],
                       owner_id=owner_id)
            
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

