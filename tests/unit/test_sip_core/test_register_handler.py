"""REGISTER Handler 단위 테스트"""

import pytest
from src.sip_core.register_handler import RegisterHandler
from src.sip_core.models.enums import SIPResponseCode
from src.common.logger import setup_logging


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.fixture
def register_handler():
    """테스트용 Register Handler"""
    return RegisterHandler()


class TestRegisterHandler:
    """REGISTER Handler 기본 테스트"""
    
    def test_initialization(self, register_handler):
        """초기화 테스트"""
        assert register_handler is not None
    
    def test_handle_register_basic(self, register_handler):
        """기본 REGISTER 처리 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="sip:alice@example.com",
            to_uri="sip:alice@example.com",
            contact="sip:alice@192.168.1.100:5060",
            expires=3600,
            call_id="register-test-123",
        )
        
        # 검증
        assert response_code == SIPResponseCode.OK
        assert response_data is not None
        assert response_data["from_uri"] == "sip:alice@example.com"
        assert response_data["to_uri"] == "sip:alice@example.com"
        assert response_data["contact"] == "sip:alice@192.168.1.100:5060"
        assert response_data["expires"] == 3600
    
    def test_handle_register_default_expires(self, register_handler):
        """Expires 기본값 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="sip:bob@example.com",
            to_uri="sip:bob@example.com",
            contact="sip:bob@192.168.1.200:5060",
            expires=None,  # 기본값 사용
        )
        
        # 기본값 3600 확인
        assert response_code == SIPResponseCode.OK
        assert response_data["expires"] == 3600
    
    def test_handle_register_custom_expires(self, register_handler):
        """커스텀 Expires 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="sip:charlie@example.com",
            to_uri="sip:charlie@example.com",
            contact="sip:charlie@192.168.1.150:5060",
            expires=7200,  # 2시간
        )
        
        assert response_code == SIPResponseCode.OK
        assert response_data["expires"] == 7200
    
    def test_handle_register_unregister(self, register_handler):
        """등록 해제 (Expires=0) 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="sip:david@example.com",
            to_uri="sip:david@example.com",
            contact="sip:david@192.168.1.180:5060",
            expires=0,  # 등록 해제
        )
        
        # 0 값도 그대로 허용 (200 OK)
        assert response_code == SIPResponseCode.OK
        assert response_data["expires"] == 0
    
    def test_handle_register_no_contact(self, register_handler):
        """Contact 없는 REGISTER (조회) 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="sip:eve@example.com",
            to_uri="sip:eve@example.com",
            contact=None,  # Contact 없음
            expires=3600,
        )
        
        # Contact 없어도 200 OK
        assert response_code == SIPResponseCode.OK
        assert response_data["contact"] is None
    
    def test_parse_register_info_full(self, register_handler):
        """REGISTER 정보 파싱 테스트 (전체)"""
        info = register_handler.parse_register_info(
            from_uri="sip:alice@example.com",
            contact="sip:alice@192.168.1.100:5060"
        )
        
        assert info["user"] == "alice"
        assert info["domain"] == "example.com"
        assert info["contact_ip"] == "192.168.1.100"
        assert info["contact_port"] == 5060
    
    def test_parse_register_info_no_port(self, register_handler):
        """포트 없는 Contact 파싱 테스트"""
        info = register_handler.parse_register_info(
            from_uri="sip:bob@example.com",
            contact="sip:bob@192.168.1.200"
        )
        
        assert info["user"] == "bob"
        assert info["contact_ip"] == "192.168.1.200"
        assert info["contact_port"] == 5060  # 기본 포트
    
    def test_parse_register_info_domain_with_port(self, register_handler):
        """Domain에 포트 포함된 경우 파싱 테스트"""
        info = register_handler.parse_register_info(
            from_uri="sip:charlie@example.com:5070",
            contact="sip:charlie@192.168.1.150:6000"
        )
        
        assert info["user"] == "charlie"
        assert info["domain"] == "example.com"  # 포트 제외
        assert info["contact_ip"] == "192.168.1.150"
        assert info["contact_port"] == 6000
    
    def test_multiple_registers(self, register_handler):
        """여러 REGISTER 처리 테스트"""
        users = ["alice", "bob", "charlie", "david", "eve"]
        
        for user in users:
            response_code, response_data = register_handler.handle_register(
                from_uri=f"sip:{user}@example.com",
                to_uri=f"sip:{user}@example.com",
                contact=f"sip:{user}@192.168.1.{100 + users.index(user)}:5060",
                expires=3600,
            )
            
            assert response_code == SIPResponseCode.OK
            assert response_data["from_uri"] == f"sip:{user}@example.com"


class TestRegisterEdgeCases:
    """REGISTER 엣지 케이스 테스트"""
    
    def test_register_with_empty_strings(self, register_handler):
        """빈 문자열 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="",
            to_uri="",
            contact="",
            expires=3600,
        )
        
        # 빈 문자열도 허용 (200 OK)
        assert response_code == SIPResponseCode.OK
    
    def test_register_with_malformed_uri(self, register_handler):
        """잘못된 형식의 URI 테스트"""
        response_code, response_data = register_handler.handle_register(
            from_uri="not-a-valid-sip-uri",
            to_uri="also-not-valid",
            contact="malformed-contact",
            expires=1800,
        )
        
        # 검증 없이 200 OK
        assert response_code == SIPResponseCode.OK
    
    def test_parse_register_info_invalid(self, register_handler):
        """잘못된 정보 파싱 테스트"""
        info = register_handler.parse_register_info(
            from_uri="invalid-uri",
            contact="invalid-contact"
        )
        
        # 파싱 실패 시 None 값
        assert info["user"] is None
        assert info["domain"] is None
        assert info["contact_ip"] is None
        assert info["contact_port"] is None

