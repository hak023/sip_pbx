"""설정 로더 단위 테스트"""

import os
import pytest
from pathlib import Path
from pydantic import ValidationError

from src.config.config_loader import ConfigLoader, load_config
from src.config.models import Config, MediaMode, LogLevel


class TestConfigLoader:
    """ConfigLoader 테스트"""

    def test_load_valid_config(self, temp_config_file):
        """정상 설정 파일 로드 테스트"""
        loader = ConfigLoader(temp_config_file)
        config = loader.load()
        
        assert isinstance(config, Config)
        assert config.sip.listen_port == 5060
        assert config.media.mode == MediaMode.REFLECTING
        assert config.ai.enabled is True

    def test_load_nonexistent_file(self):
        """존재하지 않는 파일 로드 시 에러 테스트"""
        loader = ConfigLoader("/nonexistent/config.yaml")
        
        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load()
        
        assert "설정 파일을 찾을 수 없습니다" in str(exc_info.value)

    def test_load_invalid_config(self, invalid_config_file):
        """잘못된 설정 검증 테스트"""
        loader = ConfigLoader(invalid_config_file)
        
        with pytest.raises(ValidationError):
            loader.load()

    def test_env_override_simple(self, temp_config_file, monkeypatch):
        """환경 변수로 설정 오버라이드 테스트 (단순 값)"""
        monkeypatch.setenv("SIP_PBX_SIP_LISTEN_PORT", "5061")
        
        loader = ConfigLoader(temp_config_file)
        config = loader.load()
        
        assert config.sip.listen_port == 5061

    def test_env_override_boolean(self, temp_config_file, monkeypatch):
        """환경 변수 Boolean 변환 테스트"""
        monkeypatch.setenv("SIP_PBX_AI_ENABLED", "false")
        
        loader = ConfigLoader(temp_config_file)
        config = loader.load()
        
        assert config.ai.enabled is False

    @pytest.mark.skip(reason="중첩 설정 환경 변수 오버라이드는 향후 구현 예정")
    def test_env_override_float(self, temp_config_file, monkeypatch):
        """환경 변수 Float 변환 테스트"""
        monkeypatch.setenv("SIP_PBX_AI_EMOTION_THRESHOLD", "0.85")
        
        loader = ConfigLoader(temp_config_file)
        config = loader.load()
        
        assert config.ai.emotion.threshold == 0.85

    def test_reload(self, temp_config_file):
        """설정 재로드 테스트"""
        loader = ConfigLoader(temp_config_file)
        config1 = loader.load()
        config2 = loader.reload()
        
        assert config1.sip.listen_port == config2.sip.listen_port

    def test_config_property_before_load(self):
        """로드 전 config 프로퍼티 접근 시 에러 테스트"""
        loader = ConfigLoader()
        
        with pytest.raises(RuntimeError) as exc_info:
            _ = loader.config
        
        assert "설정이 로드되지 않았습니다" in str(exc_info.value)

    def test_config_property_after_load(self, temp_config_file):
        """로드 후 config 프로퍼티 접근 테스트"""
        loader = ConfigLoader(temp_config_file)
        loader.load()
        
        config = loader.config
        assert isinstance(config, Config)

    def test_load_config_convenience_function(self, temp_config_file):
        """load_config 편의 함수 테스트"""
        config = load_config(temp_config_file)
        
        assert isinstance(config, Config)
        assert config.sip.listen_port == 5060


class TestConfigValidation:
    """설정 검증 테스트"""

    def test_port_range_validation(self):
        """포트 범위 검증 테스트"""
        with pytest.raises(ValidationError) as exc_info:
            Config(
                media={
                    "port_pool": {
                        "start": 20000,
                        "end": 10000  # end < start (잘못된 범위)
                    }
                }
            )
        
        assert "end port" in str(exc_info.value).lower()

    def test_port_number_limits(self):
        """포트 번호 범위 검증 테스트"""
        with pytest.raises(ValidationError):
            Config(sip={"listen_port": 99999})  # 65535 초과

    def test_threshold_range_validation(self):
        """임계치 범위 검증 테스트 (0.0 - 1.0)"""
        with pytest.raises(ValidationError):
            Config(ai={"emotion": {"threshold": 1.5}})  # > 1.0

    def test_negative_values_rejection(self):
        """음수 값 거부 테스트"""
        with pytest.raises(ValidationError):
            Config(media={"rtp_timeout": -10})

    def test_enum_validation(self):
        """Enum 검증 테스트"""
        # 유효한 값
        config = Config(media={"mode": "bypass"})
        assert config.media.mode == MediaMode.BYPASS
        
        # 잘못된 값
        with pytest.raises(ValidationError):
            Config(media={"mode": "invalid_mode"})


class TestDefaultValues:
    """기본값 테스트"""

    def test_default_config_creation(self):
        """기본 설정으로 Config 생성 테스트"""
        config = Config()
        
        assert config.sip.listen_ip == "0.0.0.0"
        assert config.sip.listen_port == 5060
        assert config.media.mode == MediaMode.REFLECTING
        assert config.ai.enabled is True
        assert config.logging.level == LogLevel.INFO

    def test_partial_config_with_defaults(self):
        """일부 설정만 제공 시 나머지 기본값 사용 테스트"""
        config = Config(sip={"listen_port": 5061})
        
        assert config.sip.listen_port == 5061  # 제공된 값
        assert config.sip.listen_ip == "0.0.0.0"  # 기본값
        assert config.media.mode == MediaMode.REFLECTING  # 기본값

