"""Call Detail Record (CDR)

통화 상세 기록 생성 및 저장
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from enum import Enum
import threading

from src.common.logger import get_logger

logger = get_logger(__name__)


class TerminationReason(str, Enum):
    """통화 종료 사유"""
    NORMAL = "normal"  # 정상 종료 (BYE)
    TIMEOUT = "timeout"  # 타임아웃
    CANCEL = "cancel"  # CANCEL
    ERROR = "error"  # 에러
    REJECTED = "rejected"  # 거절


@dataclass
class CDR:
    """Call Detail Record"""
    call_id: str
    caller: str  # SIP URI
    callee: str  # SIP URI
    
    # 시간 정보
    start_time: datetime
    answer_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # 통화 정보
    duration: float = 0.0  # 통화 시간 (초)
    setup_time: Optional[float] = None  # 호 설정 시간 (초)
    
    # 미디어 정보
    media_mode: str = "bypass"  # bypass or reflecting
    caller_ip: Optional[str] = None
    callee_ip: Optional[str] = None
    codec: Optional[str] = None
    
    # 이벤트 정보
    events_count: int = 0
    profanity_count: int = 0
    anger_events: int = 0
    threatening_events: int = 0
    
    # 종료 정보
    termination_reason: TerminationReason = TerminationReason.NORMAL
    
    # 추가 메타데이터
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        data = asdict(self)
        
        # datetime을 ISO 형식 문자열로 변환
        if self.start_time:
            data['start_time'] = self.start_time.isoformat()
        
        if self.answer_time:
            data['answer_time'] = self.answer_time.isoformat()
        
        if self.end_time:
            data['end_time'] = self.end_time.isoformat()
        
        # Enum을 문자열로 변환
        data['termination_reason'] = self.termination_reason.value
        
        return data
    
    def to_json(self) -> str:
        """JSON 문자열로 변환"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CDR':
        """딕셔너리에서 생성"""
        # datetime 문자열을 객체로 변환
        if 'start_time' in data and isinstance(data['start_time'], str):
            data['start_time'] = datetime.fromisoformat(data['start_time'])
        
        if 'answer_time' in data and data['answer_time'] and isinstance(data['answer_time'], str):
            data['answer_time'] = datetime.fromisoformat(data['answer_time'])
        
        if 'end_time' in data and data['end_time'] and isinstance(data['end_time'], str):
            data['end_time'] = datetime.fromisoformat(data['end_time'])
        
        # TerminationReason 변환
        if 'termination_reason' in data and isinstance(data['termination_reason'], str):
            data['termination_reason'] = TerminationReason(data['termination_reason'])
        
        return cls(**data)


class CDRWriter:
    """CDR 파일 작성기
    
    JSON Lines 형식으로 CDR을 파일에 저장
    """
    
    def __init__(
        self,
        output_dir: str = "./cdr",
        filename_pattern: str = "cdr-%Y-%m-%d.jsonl",
    ):
        """초기화
        
        Args:
            output_dir: CDR 출력 디렉토리
            filename_pattern: 파일명 패턴 (strftime 형식)
        """
        self.output_dir = Path(output_dir)
        self.filename_pattern = filename_pattern
        
        # 디렉토리 생성
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Thread safety
        self._lock = threading.Lock()
        
        # 통계
        self.stats = {
            "total_written": 0,
            "write_errors": 0,
        }
        
        logger.info("cdr_writer_initialized",
                   output_dir=str(self.output_dir),
                   filename_pattern=filename_pattern)
    
    def write_cdr(self, cdr: CDR) -> bool:
        """CDR 작성
        
        Args:
            cdr: CDR 객체
            
        Returns:
            작성 성공 여부
        """
        with self._lock:
            try:
                # 파일 경로 결정 (일자별)
                filename = datetime.now().strftime(self.filename_pattern)
                filepath = self.output_dir / filename
                
                # JSON Lines 형식으로 추가
                with open(filepath, 'a', encoding='utf-8') as f:
                    f.write(cdr.to_json() + '\n')
                
                self.stats["total_written"] += 1
                
                logger.info("cdr_written",
                           call_id=cdr.call_id,
                           filepath=str(filepath))
                
                return True
            
            except Exception as e:
                self.stats["write_errors"] += 1
                logger.error("cdr_write_failed",
                            call_id=cdr.call_id,
                            error=str(e))
                return False
    
    def get_stats(self) -> dict:
        """통계 조회"""
        return self.stats.copy()


class CDRManager:
    """CDR 관리자
    
    통화별 CDR 생성 및 관리
    """
    
    def __init__(self, cdr_writer: Optional[CDRWriter] = None):
        """초기화
        
        Args:
            cdr_writer: CDR 작성기 (None이면 생성)
        """
        self.cdr_writer = cdr_writer or CDRWriter()
        
        # 진행 중인 CDR
        # Key: call_id, Value: CDR
        self._active_cdrs: Dict[str, CDR] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # 통계
        self.stats = {
            "total_calls": 0,
            "completed_calls": 0,
            "active_calls": 0,
        }
        
        logger.info("cdr_manager_initialized")
    
    def start_call(
        self,
        call_id: str,
        caller: str,
        callee: str,
        media_mode: str = "bypass"
    ) -> CDR:
        """통화 시작 (CDR 생성)
        
        Args:
            call_id: Call ID
            caller: 발신자 SIP URI
            callee: 수신자 SIP URI
            media_mode: 미디어 모드
            
        Returns:
            생성된 CDR
        """
        with self._lock:
            cdr = CDR(
                call_id=call_id,
                caller=caller,
                callee=callee,
                start_time=datetime.utcnow(),
                media_mode=media_mode,
            )
            
            self._active_cdrs[call_id] = cdr
            
            self.stats["total_calls"] += 1
            self.stats["active_calls"] += 1
            
            logger.debug("cdr_call_started",
                        call_id=call_id,
                        caller=caller,
                        callee=callee)
            
            return cdr
    
    def answer_call(self, call_id: str):
        """통화 응답 (200 OK)
        
        Args:
            call_id: Call ID
        """
        with self._lock:
            cdr = self._active_cdrs.get(call_id)
            
            if cdr is None:
                logger.warning("cdr_not_found_for_answer", call_id=call_id)
                return
            
            cdr.answer_time = datetime.utcnow()
            
            # 호 설정 시간 계산
            if cdr.start_time:
                cdr.setup_time = (cdr.answer_time - cdr.start_time).total_seconds()
            
            logger.debug("cdr_call_answered",
                        call_id=call_id,
                        setup_time=cdr.setup_time)
    
    def end_call(
        self,
        call_id: str,
        termination_reason: TerminationReason = TerminationReason.NORMAL
    ):
        """통화 종료
        
        Args:
            call_id: Call ID
            termination_reason: 종료 사유
        """
        with self._lock:
            cdr = self._active_cdrs.get(call_id)
            
            if cdr is None:
                logger.warning("cdr_not_found_for_end", call_id=call_id)
                return
            
            # 종료 시간 설정
            cdr.end_time = datetime.utcnow()
            cdr.termination_reason = termination_reason
            
            # 통화 시간 계산
            if cdr.answer_time:
                cdr.duration = (cdr.end_time - cdr.answer_time).total_seconds()
            
            # CDR 저장
            self.cdr_writer.write_cdr(cdr)
            
            # 활성 목록에서 제거
            del self._active_cdrs[call_id]
            
            self.stats["completed_calls"] += 1
            self.stats["active_calls"] -= 1
            
            logger.info("cdr_call_ended",
                       call_id=call_id,
                       duration=cdr.duration,
                       termination_reason=termination_reason.value)
    
    def update_media_info(
        self,
        call_id: str,
        caller_ip: Optional[str] = None,
        callee_ip: Optional[str] = None,
        codec: Optional[str] = None
    ):
        """미디어 정보 업데이트
        
        Args:
            call_id: Call ID
            caller_ip: 발신자 IP
            callee_ip: 수신자 IP
            codec: 코덱
        """
        with self._lock:
            cdr = self._active_cdrs.get(call_id)
            
            if cdr is None:
                return
            
            if caller_ip:
                cdr.caller_ip = caller_ip
            
            if callee_ip:
                cdr.callee_ip = callee_ip
            
            if codec:
                cdr.codec = codec
    
    def add_event(
        self,
        call_id: str,
        event_type: str,
    ):
        """이벤트 추가
        
        Args:
            call_id: Call ID
            event_type: 이벤트 타입
        """
        with self._lock:
            cdr = self._active_cdrs.get(call_id)
            
            if cdr is None:
                return
            
            cdr.events_count += 1
            
            # 이벤트 타입별 카운트
            if "profanity" in event_type.lower():
                cdr.profanity_count += 1
            
            if "anger" in event_type.lower():
                cdr.anger_events += 1
            
            if "threatening" in event_type.lower():
                cdr.threatening_events += 1
    
    def get_cdr(self, call_id: str) -> Optional[CDR]:
        """CDR 조회
        
        Args:
            call_id: Call ID
            
        Returns:
            CDR 또는 None
        """
        with self._lock:
            return self._active_cdrs.get(call_id)
    
    def get_active_call_count(self) -> int:
        """활성 통화 수 조회"""
        with self._lock:
            return len(self._active_cdrs)
    
    def get_stats(self) -> dict:
        """통계 조회"""
        with self._lock:
            return {
                **self.stats,
                "writer_stats": self.cdr_writer.get_stats(),
            }

