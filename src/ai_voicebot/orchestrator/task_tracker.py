"""Task Tracker

아웃바운드 콜의 확인 사항 진행 상태를 추적합니다.
LLM이 보고한 태스크 상태 JSON을 파싱하여 업데이트합니다.
"""

import json
import re
from typing import List, Dict, Optional

from src.sip_core.models.outbound import QuestionAnswer
from src.common.logger import get_async_logger

logger = get_async_logger(__name__)


class TaskTracker:
    """아웃바운드 콜의 확인 사항 진행 상태 추적"""
    
    def __init__(self, questions: List[str]):
        """
        Args:
            questions: 확인해야 할 질문 목록
        """
        self.questions: Dict[str, dict] = {}
        for i, q in enumerate(questions):
            qid = f"q{i + 1}"
            self.questions[qid] = {
                "id": qid,
                "text": q,
                "status": "pending",      # pending | answered | unclear | refused
                "answer": None,
                "confidence": 0.0,
            }
        
        self.purpose_stated = False
        self.should_end_call = False
        self._total = len(questions)
        
        logger.info("task_tracker_created", question_count=self._total)
    
    def update(self, task_state: dict):
        """LLM이 보고한 태스크 상태로 업데이트
        
        Args:
            task_state: [TASK_STATE] 태그에서 파싱된 딕셔너리
        """
        for q_update in task_state.get("questions", []):
            qid = q_update.get("id")
            if qid and qid in self.questions:
                if "status" in q_update:
                    self.questions[qid]["status"] = q_update["status"]
                if "answer" in q_update and q_update["answer"]:
                    self.questions[qid]["answer"] = q_update["answer"]
                if "confidence" in q_update:
                    self.questions[qid]["confidence"] = q_update["confidence"]
        
        if "all_completed" in task_state:
            # LLM이 명시적으로 완료 보고
            pass
        
        if task_state.get("should_end_call", False):
            self.should_end_call = True
        
        logger.debug("task_tracker_updated",
                     progress=self.get_progress(),
                     should_end=self.should_end_call)
    
    def is_all_completed(self) -> bool:
        """모든 확인 사항이 완료(answered/refused)되었는지"""
        if self.should_end_call:
            return True
        return all(
            q["status"] in ("answered", "refused")
            for q in self.questions.values()
        )
    
    def get_progress(self) -> dict:
        """진행률 반환"""
        done = sum(
            1 for q in self.questions.values()
            if q["status"] in ("answered", "refused")
        )
        return {
            "total": self._total,
            "completed": done,
            "progress": round(done / self._total, 2) if self._total > 0 else 0,
        }
    
    def to_answers(self) -> List[QuestionAnswer]:
        """QuestionAnswer 리스트로 변환"""
        return [
            QuestionAnswer(
                question_id=q["id"],
                question_text=q["text"],
                status=q["status"],
                answer_text=q.get("answer"),
                answer_summary=q.get("answer"),
                confidence=q.get("confidence", 0.0),
            )
            for q in self.questions.values()
        ]
    
    @staticmethod
    def parse_task_state(response: str) -> Optional[dict]:
        """LLM 응답에서 [TASK_STATE] 태그 파싱
        
        Args:
            response: LLM 전체 응답 텍스트
            
        Returns:
            파싱된 task_state dict 또는 None
        """
        match = re.search(r'\[TASK_STATE\](.*?)\[/TASK_STATE\]', response, re.DOTALL)
        if not match:
            return None
        
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError as e:
            logger.warning("task_state_parse_error",
                          error=str(e),
                          raw=match.group(1).strip()[:200])
            return None
    
    @staticmethod
    def strip_task_tags(response: str) -> str:
        """응답에서 [TASK_STATE] 태그 제거 (TTS용)"""
        return re.sub(r'\[TASK_STATE\].*?\[/TASK_STATE\]', '', response, flags=re.DOTALL).strip()
