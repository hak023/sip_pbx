"""SIP 서버 통합 테스트

SIP 서버 시작, 종료, 상태 확인 테스트
"""

import pytest
import time
from src.config.models import Config
from src.sip_core.sip_endpoint import create_sip_endpoint, MockSIPEndpoint
from src.common.logger import setup_logging


@pytest.fixture(scope="module")
def test_config():
    """테스트용 설정"""
    return Config(
        sip={
            "listen_ip": "127.0.0.1",
            "listen_port": 15060,  # 테스트용 비표준 포트
            "transport": "udp",
        },
        logging={
            "level": "DEBUG",
            "format": "json",
        }
    )


@pytest.fixture(scope="module", autouse=True)
def setup_test_logging():
    """테스트용 로깅 설정"""
    setup_logging(level="DEBUG", format_type="text")


@pytest.mark.integration
class TestSIPServerLifecycle:
    """SIP 서버 생명주기 테스트"""
    
    def test_create_sip_endpoint(self, test_config):
        """SIP Endpoint 생성 테스트"""
        endpoint = create_sip_endpoint(test_config)
        
        assert endpoint is not None
        assert isinstance(endpoint, MockSIPEndpoint)  # PJSIP 없으므로 Mock
        assert not endpoint.is_running()
    
    def test_start_sip_server(self, test_config):
        """SIP 서버 시작 테스트"""
        endpoint = create_sip_endpoint(test_config)
        
        # 시작 전
        assert not endpoint.is_running()
        
        # 시작
        endpoint.start()
        
        # 시작 후
        assert endpoint.is_running()
        
        # 정리
        endpoint.stop()
    
    def test_stop_sip_server(self, test_config):
        """SIP 서버 종료 테스트"""
        endpoint = create_sip_endpoint(test_config)
        endpoint.start()
        
        # 실행 중
        assert endpoint.is_running()
        
        # 종료
        endpoint.stop()
        
        # 종료 후
        assert not endpoint.is_running()
    
    def test_start_stop_multiple_times(self, test_config):
        """SIP 서버 여러 번 시작/종료 테스트"""
        endpoint = create_sip_endpoint(test_config)
        
        for _ in range(3):
            assert not endpoint.is_running()
            
            endpoint.start()
            assert endpoint.is_running()
            
            endpoint.stop()
            assert not endpoint.is_running()
    
    def test_stop_without_start(self, test_config):
        """시작하지 않은 서버 종료 시도 (에러 없어야 함)"""
        endpoint = create_sip_endpoint(test_config)
        
        # 시작하지 않고 종료 시도
        endpoint.stop()  # Should not raise
        
        assert not endpoint.is_running()
    
    def test_server_running_for_duration(self, test_config):
        """서버가 일정 시간 동안 실행 유지 테스트"""
        endpoint = create_sip_endpoint(test_config)
        endpoint.start()
        
        # 2초 동안 실행
        for _ in range(4):
            time.sleep(0.5)
            assert endpoint.is_running()
        
        endpoint.stop()
        assert not endpoint.is_running()


@pytest.mark.integration
class TestSIPServerConfiguration:
    """SIP 서버 설정 테스트"""
    
    def test_custom_port(self):
        """커스텀 포트 설정 테스트"""
        config = Config(sip={"listen_port": 15061})
        endpoint = create_sip_endpoint(config)
        
        assert endpoint.config.sip.listen_port == 15061
    
    def test_custom_ip(self):
        """커스텀 IP 설정 테스트"""
        config = Config(sip={"listen_ip": "127.0.0.1"})
        endpoint = create_sip_endpoint(config)
        
        assert endpoint.config.sip.listen_ip == "127.0.0.1"
    
    def test_transport_type(self):
        """Transport 타입 설정 테스트"""
        for transport in ["udp", "tcp"]:
            config = Config(sip={"transport": transport})
            endpoint = create_sip_endpoint(config)
            
            assert endpoint.config.sip.transport == transport

