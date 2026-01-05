"""CDR 테스트"""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from src.events.cdr import (
    CDR,
    TerminationReason,
    CDRWriter,
    CDRManager,
)
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def temp_cdr_dir():
    """임시 CDR 디렉토리"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def cdr_writer(temp_cdr_dir):
    """CDR 작성기"""
    return CDRWriter(output_dir=temp_cdr_dir)


@pytest.fixture
def cdr_manager(cdr_writer):
    """CDR 관리자"""
    return CDRManager(cdr_writer=cdr_writer)


@pytest.fixture
def sample_cdr():
    """샘플 CDR"""
    return CDR(
        call_id="call-123",
        caller="sip:alice@example.com",
        callee="sip:bob@example.com",
        start_time=datetime.utcnow(),
        media_mode="bypass",
    )


class TestCDRModel:
    """CDR 모델 테스트"""
    
    def test_cdr_creation(self):
        """CDR 생성"""
        cdr = CDR(
            call_id="test-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
        )
        
        assert cdr.call_id == "test-call"
        assert cdr.caller == "sip:alice@example.com"
        assert cdr.callee == "sip:bob@example.com"
        assert cdr.duration == 0.0
    
    def test_cdr_to_dict(self, sample_cdr):
        """CDR → 딕셔너리 변환"""
        data = sample_cdr.to_dict()
        
        assert data["call_id"] == "call-123"
        assert data["caller"] == "sip:alice@example.com"
        assert "start_time" in data
        assert isinstance(data["start_time"], str)
    
    def test_cdr_to_json(self, sample_cdr):
        """CDR → JSON 변환"""
        json_str = sample_cdr.to_json()
        
        assert isinstance(json_str, str)
        
        # JSON 파싱 가능한지 확인
        data = json.loads(json_str)
        assert data["call_id"] == "call-123"
    
    def test_cdr_from_dict(self, sample_cdr):
        """딕셔너리 → CDR 변환"""
        data = sample_cdr.to_dict()
        
        restored_cdr = CDR.from_dict(data)
        
        assert restored_cdr.call_id == sample_cdr.call_id
        assert restored_cdr.caller == sample_cdr.caller
        assert restored_cdr.callee == sample_cdr.callee
    
    def test_cdr_with_answer_time(self):
        """응답 시간이 있는 CDR"""
        start = datetime.utcnow()
        answer = start + timedelta(seconds=2)
        
        cdr = CDR(
            call_id="answered-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=start,
            answer_time=answer,
        )
        
        assert cdr.answer_time is not None
    
    def test_cdr_with_events(self):
        """이벤트가 있는 CDR"""
        cdr = CDR(
            call_id="event-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
            events_count=5,
            profanity_count=2,
            anger_events=3,
        )
        
        assert cdr.events_count == 5
        assert cdr.profanity_count == 2
        assert cdr.anger_events == 3
    
    def test_termination_reason(self):
        """종료 사유"""
        cdr = CDR(
            call_id="terminated-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
            termination_reason=TerminationReason.TIMEOUT,
        )
        
        assert cdr.termination_reason == TerminationReason.TIMEOUT


class TestCDRWriter:
    """CDR Writer 테스트"""
    
    def test_writer_creation(self, temp_cdr_dir):
        """작성기 생성"""
        writer = CDRWriter(output_dir=temp_cdr_dir)
        
        assert writer.output_dir == Path(temp_cdr_dir)
        assert writer.output_dir.exists()
    
    def test_write_cdr(self, cdr_writer, sample_cdr, temp_cdr_dir):
        """CDR 작성"""
        success = cdr_writer.write_cdr(sample_cdr)
        
        assert success is True
        assert cdr_writer.stats["total_written"] == 1
        
        # 파일 생성 확인
        files = list(Path(temp_cdr_dir).glob("*.jsonl"))
        assert len(files) > 0
    
    def test_write_multiple_cdrs(self, cdr_writer, temp_cdr_dir):
        """여러 CDR 작성"""
        for i in range(5):
            cdr = CDR(
                call_id=f"call-{i}",
                caller=f"sip:user{i}@example.com",
                callee="sip:bob@example.com",
                start_time=datetime.utcnow(),
            )
            cdr_writer.write_cdr(cdr)
        
        assert cdr_writer.stats["total_written"] == 5
        
        # 파일 내용 확인
        files = list(Path(temp_cdr_dir).glob("*.jsonl"))
        assert len(files) > 0
        
        with open(files[0], 'r', encoding='utf-8') as f:
            lines = f.readlines()
            assert len(lines) == 5
    
    def test_jsonl_format(self, cdr_writer, sample_cdr, temp_cdr_dir):
        """JSON Lines 형식 확인"""
        cdr_writer.write_cdr(sample_cdr)
        
        files = list(Path(temp_cdr_dir).glob("*.jsonl"))
        
        with open(files[0], 'r', encoding='utf-8') as f:
            line = f.readline().strip()
            
            # JSON 파싱 가능한지 확인
            data = json.loads(line)
            assert data["call_id"] == "call-123"
    
    def test_get_stats(self, cdr_writer):
        """통계 조회"""
        stats = cdr_writer.get_stats()
        
        assert "total_written" in stats
        assert "write_errors" in stats


class TestCDRManager:
    """CDR Manager 테스트"""
    
    def test_manager_creation(self, cdr_manager):
        """관리자 생성"""
        assert cdr_manager.cdr_writer is not None
        assert cdr_manager.get_active_call_count() == 0
    
    def test_start_call(self, cdr_manager):
        """통화 시작"""
        cdr = cdr_manager.start_call(
            call_id="new-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            media_mode="bypass"
        )
        
        assert cdr is not None
        assert cdr.call_id == "new-call"
        assert cdr.start_time is not None
        assert cdr_manager.get_active_call_count() == 1
    
    def test_answer_call(self, cdr_manager):
        """통화 응답"""
        cdr_manager.start_call(
            call_id="answer-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com"
        )
        
        cdr_manager.answer_call("answer-call")
        
        cdr = cdr_manager.get_cdr("answer-call")
        assert cdr.answer_time is not None
        assert cdr.setup_time is not None
        assert cdr.setup_time >= 0
    
    def test_end_call(self, cdr_manager):
        """통화 종료"""
        cdr_manager.start_call(
            call_id="end-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com"
        )
        
        cdr_manager.answer_call("end-call")
        
        initial_count = cdr_manager.get_active_call_count()
        
        cdr_manager.end_call("end-call", TerminationReason.NORMAL)
        
        # 활성 통화에서 제거됨
        assert cdr_manager.get_active_call_count() == initial_count - 1
        assert cdr_manager.get_cdr("end-call") is None
    
    def test_update_media_info(self, cdr_manager):
        """미디어 정보 업데이트"""
        cdr_manager.start_call(
            call_id="media-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com"
        )
        
        cdr_manager.update_media_info(
            call_id="media-call",
            caller_ip="192.168.1.10",
            callee_ip="192.168.1.20",
            codec="PCMU"
        )
        
        cdr = cdr_manager.get_cdr("media-call")
        assert cdr.caller_ip == "192.168.1.10"
        assert cdr.callee_ip == "192.168.1.20"
        assert cdr.codec == "PCMU"
    
    def test_add_event(self, cdr_manager):
        """이벤트 추가"""
        cdr_manager.start_call(
            call_id="event-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com"
        )
        
        # 이벤트 추가
        cdr_manager.add_event("event-call", "profanity_detected")
        cdr_manager.add_event("event-call", "anger_detected")
        cdr_manager.add_event("event-call", "threatening_language")
        
        cdr = cdr_manager.get_cdr("event-call")
        assert cdr.events_count == 3
        assert cdr.profanity_count == 1
        assert cdr.anger_events == 1
        assert cdr.threatening_events == 1
    
    def test_get_stats(self, cdr_manager):
        """통계 조회"""
        stats = cdr_manager.get_stats()
        
        assert "total_calls" in stats
        assert "completed_calls" in stats
        assert "active_calls" in stats
        assert "writer_stats" in stats
    
    def test_call_lifecycle(self, cdr_manager, temp_cdr_dir):
        """통화 전체 라이프사이클"""
        # 1. 통화 시작
        cdr_manager.start_call(
            call_id="lifecycle-call",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            media_mode="reflecting"
        )
        
        # 2. 미디어 정보 업데이트
        cdr_manager.update_media_info(
            call_id="lifecycle-call",
            caller_ip="10.0.0.1",
            callee_ip="10.0.0.2",
            codec="OPUS"
        )
        
        # 3. 통화 응답
        cdr_manager.answer_call("lifecycle-call")
        
        # 4. 이벤트 발생
        cdr_manager.add_event("lifecycle-call", "profanity_detected")
        cdr_manager.add_event("lifecycle-call", "anger_detected")
        
        # 5. 통화 종료
        cdr_manager.end_call("lifecycle-call", TerminationReason.NORMAL)
        
        # 6. CDR 파일 확인
        files = list(Path(temp_cdr_dir).glob("*.jsonl"))
        assert len(files) > 0
        
        with open(files[0], 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                if data["call_id"] == "lifecycle-call":
                    assert data["caller"] == "sip:alice@example.com"
                    assert data["callee"] == "sip:bob@example.com"
                    assert data["media_mode"] == "reflecting"
                    assert data["codec"] == "OPUS"
                    assert data["events_count"] == 2
                    assert data["termination_reason"] == "normal"
                    break

