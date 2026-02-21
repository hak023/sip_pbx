"""
SIP Core Unit Tests - CDR (Call Detail Records)

통화 상세 기록 생성 및 처리 테스트
"""

import pytest
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import shutil

from src.events.cdr import CDR, TerminationReason, CDRWriter


class TestCDR:
    """CDR 모델 단위 테스트"""
    
    def test_create_cdr_with_required_fields(self):
        """
        Given: 필수 필드만으로 CDR 생성
        When: CDR 인스턴스화
        Then: CDR 객체가 생성되고 기본값 설정됨
        """
        # Given
        call_id = "test-call-123"
        caller = "sip:alice@example.com"
        callee = "sip:bob@example.com"
        start_time = datetime.utcnow()
        
        # When
        cdr = CDR(
            call_id=call_id,
            caller=caller,
            callee=callee,
            start_time=start_time
        )
        
        # Then
        assert cdr.call_id == call_id
        assert cdr.caller == caller
        assert cdr.callee == callee
        assert cdr.start_time == start_time
        assert cdr.termination_reason == TerminationReason.NORMAL
        assert cdr.duration == 0.0
    
    def test_cdr_to_dict_converts_datetime_to_string(self):
        """
        Given: datetime 필드가 있는 CDR
        When: to_dict() 호출
        Then: datetime이 ISO 형식 문자열로 변환됨
        """
        # Given
        start_time = datetime(2026, 1, 8, 12, 0, 0)
        cdr = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=start_time
        )
        
        # When
        cdr_dict = cdr.to_dict()
        
        # Then
        assert isinstance(cdr_dict['start_time'], str)
        assert cdr_dict['start_time'] == "2026-01-08T12:00:00"
        assert cdr_dict['termination_reason'] == "normal"
    
    def test_cdr_to_json_returns_valid_json(self):
        """
        Given: CDR 인스턴스
        When: to_json() 호출
        Then: 유효한 JSON 문자열 반환
        """
        # Given
        cdr = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
            duration=120.5
        )
        
        # When
        json_str = cdr.to_json()
        
        # Then
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed['call_id'] == "test-123"
        assert parsed['duration'] == 120.5
    
    def test_cdr_from_dict_creates_instance(self):
        """
        Given: CDR 딕셔너리 데이터
        When: from_dict() 호출
        Then: CDR 인스턴스가 생성되고 datetime 필드가 복원됨
        """
        # Given
        data = {
            "call_id": "test-123",
            "caller": "sip:alice@example.com",
            "callee": "sip:bob@example.com",
            "start_time": "2026-01-08T12:00:00",
            "answer_time": "2026-01-08T12:00:05",
            "end_time": "2026-01-08T12:02:00",
            "duration": 115.0,
            "termination_reason": "normal"
        }
        
        # When
        cdr = CDR.from_dict(data)
        
        # Then
        assert cdr.call_id == "test-123"
        assert isinstance(cdr.start_time, datetime)
        assert isinstance(cdr.answer_time, datetime)
        assert cdr.duration == 115.0
        assert cdr.termination_reason == TerminationReason.NORMAL
    
    def test_cdr_with_recording_metadata(self):
        """
        Given: 녹음 메타데이터가 포함된 CDR
        When: CDR 생성 및 직렬화
        Then: 녹음 정보가 올바르게 저장되고 변환됨
        """
        # Given
        cdr = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
            has_recording=True,
            recording_path="recordings/test-123/mixed.wav",
            recording_duration=120.0,
            recording_type="sip_call"
        )
        
        # When
        cdr_dict = cdr.to_dict()
        
        # Then
        assert cdr_dict['has_recording'] is True
        assert cdr_dict['recording_path'] == "recordings/test-123/mixed.wav"
        assert cdr_dict['recording_duration'] == 120.0
        assert cdr_dict['recording_type'] == "sip_call"
    
    def test_cdr_metadata_field(self):
        """
        Given: 사용자 정의 메타데이터를 포함하는 CDR
        When: metadata 필드에 데이터 추가
        Then: 메타데이터가 올바르게 저장되고 직렬화됨
        """
        # Given
        cdr = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow(),
            metadata={"custom_field": "value", "another_field": 42}
        )
        
        # When
        cdr_dict = cdr.to_dict()
        
        # Then
        assert cdr_dict['metadata']['custom_field'] == "value"
        assert cdr_dict['metadata']['another_field'] == 42


class TestCDRWriter:
    """CDRWriter 단위 테스트"""
    
    @pytest.fixture
    def temp_cdr_dir(self):
        """임시 CDR 디렉토리 생성"""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # 테스트 후 정리
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    
    def test_cdr_writer_creates_directory(self, temp_cdr_dir):
        """
        Given: 존재하지 않는 CDR 디렉토리 경로
        When: CDRWriter 인스턴스화
        Then: 디렉토리가 자동으로 생성됨
        """
        # Given
        cdr_path = temp_cdr_dir / "cdr_logs"
        assert not cdr_path.exists()
        
        # When
        writer = CDRWriter(str(cdr_path))
        
        # Then
        assert cdr_path.exists()
    
    def test_write_cdr_creates_file(self, temp_cdr_dir):
        """
        Given: CDR 인스턴스
        When: write() 호출
        Then: CDR 파일이 생성되고 JSON Lines 형식으로 저장됨
        """
        # Given
        writer = CDRWriter(str(temp_cdr_dir))
        cdr = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow()
        )
        
        # When
        writer.write_cdr(cdr)
        
        # Then
        cdr_files = list(temp_cdr_dir.glob("cdr-*.jsonl"))
        assert len(cdr_files) >= 1
        
        # 파일 내용 검증
        with open(cdr_files[0], 'r', encoding='utf-8') as f:
            lines = f.readlines()
            assert len(lines) >= 1
            cdr_data = json.loads(lines[0])
            assert cdr_data['call_id'] == "test-123"
    
    def test_write_multiple_cdrs_to_same_file(self, temp_cdr_dir):
        """
        Given: 여러 CDR 인스턴스
        When: 순차적으로 write() 호출
        Then: 모든 CDR이 같은 날짜의 파일에 JSON Lines로 추가됨
        """
        # Given
        writer = CDRWriter(str(temp_cdr_dir))
        cdr1 = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime.utcnow()
        )
        cdr2 = CDR(
            call_id="test-456",
            caller="sip:charlie@example.com",
            callee="sip:dave@example.com",
            start_time=datetime.utcnow()
        )
        
        # When
        writer.write_cdr(cdr1)
        writer.write_cdr(cdr2)
        
        # Then
        cdr_files = list(temp_cdr_dir.glob("cdr-*.jsonl"))
        assert len(cdr_files) >= 1
        
        with open(cdr_files[0], 'r', encoding='utf-8') as f:
            lines = f.readlines()
            assert len(lines) >= 2
            
            cdr1_data = json.loads(lines[0])
            cdr2_data = json.loads(lines[1])
            
            assert cdr1_data['call_id'] == "test-123"
            assert cdr2_data['call_id'] == "test-456"
    
    def test_cdr_roundtrip_serialization(self):
        """
        Given: CDR 인스턴스
        When: to_dict() → from_dict() 변환
        Then: 모든 필드가 정확히 복원됨
        """
        # Given
        original = CDR(
            call_id="test-123",
            caller="sip:alice@example.com",
            callee="sip:bob@example.com",
            start_time=datetime(2026, 1, 8, 12, 0, 0),
            answer_time=datetime(2026, 1, 8, 12, 0, 5),
            end_time=datetime(2026, 1, 8, 12, 2, 0),
            duration=115.0,
            termination_reason=TerminationReason.NORMAL,
            has_recording=True,
            recording_path="recordings/test-123/mixed.wav"
        )
        
        # When
        cdr_dict = original.to_dict()
        restored = CDR.from_dict(cdr_dict)
        
        # Then
        assert restored.call_id == original.call_id
        assert restored.caller == original.caller
        assert restored.callee == original.callee
        assert restored.duration == original.duration
        assert restored.termination_reason == original.termination_reason
        assert restored.has_recording == original.has_recording
        assert restored.recording_path == original.recording_path

