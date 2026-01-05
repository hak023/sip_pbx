"""pytest 설정 파일

공통 fixtures 및 테스트 설정
"""

import pytest
import tempfile
import yaml
from pathlib import Path


@pytest.fixture
def temp_config_file():
    """임시 설정 파일 fixture"""
    config_data = {
        "sip": {
            "listen_ip": "0.0.0.0",
            "listen_port": 5060,
            "transport": "udp",
            "max_concurrent_calls": 100,
        },
        "media": {
            "mode": "reflecting",
            "port_pool": {"start": 10000, "end": 20000},
            "rtp_timeout": 60,
        },
        "ai": {
            "enabled": True,
            "stt": {"model": "faster-whisper-large-v3", "device": "cuda"},
        },
        "events": {
            "webhook_urls": ["http://localhost:5000/webhook"],
            "webhook_timeout": 10,
        },
        "logging": {
            "level": "INFO",
            "format": "json",
        },
    }
    
    # 임시 파일 생성
    with tempfile.NamedTemporaryFile(
        mode='w', 
        suffix='.yaml', 
        delete=False,
        encoding='utf-8'
    ) as f:
        yaml.dump(config_data, f)
        temp_path = f.name
    
    yield temp_path
    
    # 정리
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def invalid_config_file():
    """잘못된 설정 파일 fixture"""
    config_data = {
        "sip": {
            "listen_port": 99999,  # 잘못된 포트 (65535 초과)
        },
        "media": {
            "port_pool": {
                "start": 20000,
                "end": 10000,  # end < start (잘못된 범위)
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.yaml',
        delete=False,
        encoding='utf-8'
    ) as f:
        yaml.dump(config_data, f)
        temp_path = f.name
    
    yield temp_path
    
    Path(temp_path).unlink(missing_ok=True)

