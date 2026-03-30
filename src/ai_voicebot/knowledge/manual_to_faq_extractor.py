"""
Manual to FAQ Extractor

TXT 매뉴얼 파일을 LLM으로 분석하여 Q&A 쌍으로 변환.

설계:
1. TXT 청킹 (4-8KB, 자연스러운 구분자 기준)
2. 각 청크 → LLM → Q&A JSON 추출
3. FAQ 중복 제거 및 병합
4. ChromaDB 저장
"""

import re
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class ManualToFAQExtractor:
    """매뉴얼 TXT → FAQ 변환 서비스"""
    
    # 청킹 파라미터
    CHUNK_MIN_SIZE = 2000  # 2KB
    CHUNK_MAX_SIZE = 8000  # 8KB
    CHUNK_OVERLAP = 100    # 100자 오버랩
    
    # LLM 프롬프트
    EXTRACTION_PROMPT = """당신은 조직 매뉴얼을 분석하여 FAQ를 추출하는 전문가입니다.

주어진 매뉴얼 텍스트에서 사용자가 전화로 물을 법한 질문과 답변을 추출하세요.

**중요 규칙:**
1. 질문은 자연스러운 구어체로 작성 (예: "영업 시간이 어떻게 되나요?", "주차 가능한가요?")
2. 답변은 간결하고 정확하게 (2-3문장 이내, 통화 응답용)
3. 명확한 사실 정보만 추출 (추측이나 해석 금지)
4. 관련된 정보는 하나의 Q&A로 통합
5. 모호하거나 불완전한 정보는 제외

**출력 형식 (JSON):**
```json
[
  {{
    "question": "영업 시간이 어떻게 되나요?",
    "answer": "평일은 오전 11시 30분부터 밤 10시까지, 주말은 오전 10시부터 밤 11시까지 운영합니다.",
    "category": "운영시간"
  }},
  {{
    "question": "주차가 가능한가요?",
    "answer": "건물 지하 1층에 30대 규모의 무료 주차장을 운영하고 있습니다. 발레파킹 서비스도 제공합니다.",
    "category": "주차"
  }}
]
```

**매뉴얼 텍스트:**
{manual_text}

**JSON 출력 (위 형식 준수):**"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM 클라이언트 (LLMClient)
        """
        self._llm = llm_client
    
    def chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """
        TXT를 청크로 분할 (자연스러운 구분자 우선)
        
        Args:
            text: 원본 텍스트
            
        Returns:
            [{"chunk_id": 0, "text": "...", "start_pos": 0, "end_pos": 2000}, ...]
        """
        text = text.strip()
        if not text:
            return []
        
        chunks = []
        pos = 0
        chunk_id = 0
        
        while pos < len(text):
            # 청크 끝 위치 계산
            end_pos = min(pos + self.CHUNK_MAX_SIZE, len(text))
            
            # 자연스러운 구분자 찾기 (우선순위: \n\n > \n > 마침표 > 공백)
            if end_pos < len(text):
                # 뒤에서부터 구분자 찾기
                search_start = max(pos + self.CHUNK_MIN_SIZE, end_pos - 500)
                chunk_text = text[search_start:end_pos]
                
                # 1순위: 빈 줄 (단락 구분)
                double_newline = chunk_text.rfind('\n\n')
                if double_newline != -1:
                    end_pos = search_start + double_newline + 2
                # 2순위: 단일 줄바꿈
                elif '\n' in chunk_text:
                    newline = chunk_text.rfind('\n')
                    end_pos = search_start + newline + 1
                # 3순위: 마침표
                elif '.' in chunk_text or '。' in chunk_text:
                    period = max(chunk_text.rfind('.'), chunk_text.rfind('。'))
                    if period != -1:
                        end_pos = search_start + period + 1
                # 4순위: 공백
                elif ' ' in chunk_text:
                    space = chunk_text.rfind(' ')
                    end_pos = search_start + space + 1
            
            chunk_content = text[pos:end_pos].strip()
            if chunk_content:
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": chunk_content,
                    "start_pos": pos,
                    "end_pos": end_pos,
                    "size": len(chunk_content),
                })
                chunk_id += 1
            
            # 다음 청크 시작 (오버랩 적용)
            pos = max(end_pos - self.CHUNK_OVERLAP, end_pos)
        
        logger.info("manual_text_chunked",
                   total_size=len(text),
                   chunk_count=len(chunks),
                   avg_chunk_size=sum(c["size"] for c in chunks) // len(chunks) if chunks else 0,
                   note="매뉴얼 텍스트 청킹 완료")
        
        return chunks
    
    async def extract_faqs_from_chunk(self, chunk_text: str, chunk_id: int) -> List[Dict[str, str]]:
        """
        LLM으로 청크에서 Q&A 쌍 추출
        
        Args:
            chunk_text: 청크 텍스트
            chunk_id: 청크 ID
            
        Returns:
            [{"question": "...", "answer": "...", "category": "..."}, ...]
        """
        response_text = ""
        try:
            # EXTRACTION_PROMPT 예시 JSON의 {{ }} 는 str.format 리터럴 이스케이프(치환 필드 아님)
            prompt = self.EXTRACTION_PROMPT.format(manual_text=chunk_text)
            
            # LLM 호출 (generate_response는 RAG용이므로 generate_simple 사용)
            # ✅ generate_simple: 간단한 프롬프트 → 텍스트 응답
            response_text = await self._llm.generate_simple(
                prompt=prompt,
                max_tokens=4096,
                timeout_seconds=60.0,
            )
            
            if not response_text:
                logger.warning("chunk_faq_extraction_empty_response",
                              chunk_id=chunk_id,
                              chunk_size=len(chunk_text),
                              note="LLM 응답 없음")
                return []
            
            # JSON 파싱
            # JSON 블록 추출 (```json ... ``` 제거)
            json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # JSON 블록 없이 바로 배열 찾기
                array_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
                if array_match:
                    json_str = array_match.group(0)
                else:
                    json_str = response_text.strip()
            
            # JSON 파싱 전 로깅
            logger.info("chunk_faq_json_parse_attempt",
                       chunk_id=chunk_id,
                       json_str_preview=json_str[:300] if json_str else "",
                       json_str_length=len(json_str),
                       note="LLM 응답 JSON 파싱 시도")
            
            faqs = json.loads(json_str)
            
            # 유효성 검증
            valid_faqs = []
            for faq in faqs:
                if isinstance(faq, dict) and "question" in faq and "answer" in faq:
                    valid_faqs.append({
                        "question": faq["question"].strip(),
                        "answer": faq["answer"].strip(),
                        "category": faq.get("category", "일반").strip(),
                    })
            
            logger.info("chunk_faq_extraction_success",
                       chunk_id=chunk_id,
                       chunk_size=len(chunk_text),
                       faqs_extracted=len(valid_faqs),
                       note="청크에서 FAQ 추출 완료")
            
            return valid_faqs
            
        except json.JSONDecodeError as e:
            logger.error("chunk_faq_json_parse_error",
                        chunk_id=chunk_id,
                        error=str(e),
                        response_preview=response_text[:500] if response_text else "",
                        response_full=response_text if len(response_text) < 1000 else response_text[:1000] + "...",
                        note="LLM 응답 JSON 파싱 실패 — 형식 확인 필요")
            return []
        except Exception as e:
            logger.error("chunk_faq_extraction_error",
                        chunk_id=chunk_id,
                        error=str(e),
                        response_preview=response_text[:500] if response_text else "",
                        exc_info=True,
                        note="FAQ 추출 중 예외 발생")
            return []
    
    def deduplicate_faqs(self, faqs: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        중복 FAQ 제거 (질문 기준 유사도)
        
        간단한 구현: 질문 정규화 후 exact match
        향후 개선: Embedding 유사도 기반 중복 제거
        """
        seen_questions = set()
        unique_faqs = []
        
        for faq in faqs:
            # 질문 정규화 (공백 제거, 소문자 변환)
            normalized_q = re.sub(r'\s+', '', faq["question"]).lower()
            
            if normalized_q not in seen_questions:
                seen_questions.add(normalized_q)
                unique_faqs.append(faq)
        
        removed_count = len(faqs) - len(unique_faqs)
        if removed_count > 0:
            logger.info("faq_deduplication",
                       original_count=len(faqs),
                       unique_count=len(unique_faqs),
                       removed_count=removed_count,
                       note="중복 FAQ 제거")
        
        return unique_faqs
    
    async def extract_faqs_from_manual(
        self,
        text: str,
        source_filename: str = "manual.txt",
    ) -> Dict[str, Any]:
        """
        매뉴얼 텍스트에서 FAQ 추출 (전체 프로세스)
        
        Args:
            text: 매뉴얼 텍스트
            source_filename: 원본 파일명
            
        Returns:
            {
                "success": True,
                "faqs": [...],
                "total_faqs": 15,
                "chunks_processed": 3,
                "source_file": "manual.txt",
            }
        """
        start_time = datetime.now()
        
        logger.info("manual_faq_extraction_start",
                   source_file=source_filename,
                   text_size=len(text),
                   note="매뉴얼 → FAQ 추출 시작")
        
        # 1. 청킹
        chunks = self.chunk_text(text)
        if not chunks:
            return {
                "success": False,
                "error": "텍스트가 비어있거나 청킹 실패",
                "faqs": [],
            }
        
        # 2. 각 청크에서 FAQ 추출
        all_faqs = []
        for chunk in chunks:
            chunk_faqs = await self.extract_faqs_from_chunk(
                chunk["text"],
                chunk["chunk_id"]
            )
            all_faqs.extend(chunk_faqs)
        
        # 3. 중복 제거
        unique_faqs = self.deduplicate_faqs(all_faqs)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        logger.info("manual_faq_extraction_complete",
                   source_file=source_filename,
                   chunks_processed=len(chunks),
                   faqs_extracted=len(all_faqs),
                   faqs_unique=len(unique_faqs),
                   elapsed_sec=round(elapsed, 2),
                   note="매뉴얼 → FAQ 추출 완료")
        
        return {
            "success": True,
            "faqs": unique_faqs,
            "total_faqs": len(unique_faqs),
            "chunks_processed": len(chunks),
            "source_file": source_filename,
            "elapsed_sec": elapsed,
        }


async def extract_and_save_faqs_from_txt(
    text: str,
    owner: str,
    source_filename: str,
    llm_client,
    knowledge_service,
) -> Dict[str, Any]:
    """
    TXT 매뉴얼에서 FAQ 추출 후 ChromaDB 저장
    
    Args:
        text: 매뉴얼 텍스트
        owner: Owner ID
        source_filename: 원본 파일명
        llm_client: LLM 클라이언트
        knowledge_service: Knowledge 서비스
        
    Returns:
        {
            "success": True,
            "faqs_extracted": 15,
            "faqs_saved": 15,
            "source_file": "manual.txt",
        }
    """
    try:
        # 1. FAQ 추출
        extractor = ManualToFAQExtractor(llm_client)
        result = await extractor.extract_faqs_from_manual(text, source_filename)
        
        if not result["success"]:
            return result
        
        faqs = result["faqs"]
        
        # 2. ChromaDB 저장
        saved_count = 0
        for i, faq in enumerate(faqs):
            try:
                # FAQ 문서 생성
                doc_content = f"Q: {faq['question']}\nA: {faq['answer']}"
                
                # 프론트엔드 호환을 위해 category는 "question", doc_type은 "knowledge"로 통일
                # LLM이 추출한 원본 카테고리는 metadata.faq_category에 보관
                result = await knowledge_service.add_knowledge(
                    text=doc_content,
                    category="question",  # 프론트엔드 필터 호환
                    keywords=None,
                    metadata={
                        "owner": owner,
                        "doc_type": "knowledge",  # 프론트엔드 필터 호환 (faq → knowledge)
                        "source": "manual",  # 프론트엔드 KNOWLEDGE_SOURCES 호환
                        "question": faq["question"],
                        "answer": faq["answer"],
                        "faq_category": faq.get("category", "일반"),  # LLM 추출 원본 카테고리
                        "source_file": source_filename,
                        "faq_index": i,
                        "created_at": datetime.now().isoformat(),
                    }
                )
                
                if result and result.get("success"):
                    saved_count += 1
                    
            except Exception as e:
                logger.error("faq_save_error",
                            owner=owner,
                            faq_index=i,
                            question_preview=faq["question"][:50],
                            error=str(e))
        
        logger.info("manual_upload_complete",
                   owner=owner,
                   source_file=source_filename,
                   faqs_extracted=len(faqs),
                   faqs_saved=saved_count,
                   note="매뉴얼 업로드 완료")
        
        return {
            "success": True,
            "faqs_extracted": len(faqs),
            "faqs_saved": saved_count,
            "source_file": source_filename,
            "elapsed_sec": result.get("elapsed_sec", 0),
        }
        
    except Exception as e:
        logger.error("manual_to_faq_process_error",
                    owner=owner,
                    source_file=source_filename,
                    error=str(e),
                    exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "faqs_extracted": 0,
            "faqs_saved": 0,
        }
