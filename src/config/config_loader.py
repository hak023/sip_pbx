"""설정 로더 모듈

YAML 파일 로드 및 환경 변수 오버라이드 지원
"""

import os
from pathlib import Path
from typing import Optional, Any, Dict
import yaml
from pydantic import ValidationError

from .models import Config


class ConfigLoader:
    """설정 로더 클래스"""

    def __init__(self, config_path: Optional[str] = None):
        """초기화
        
        Args:
            config_path: 설정 파일 경로. None인 경우 기본 경로 사용
        """
        self.config_path = config_path or self._get_default_config_path()
        self._config: Optional[Config] = None

    @staticmethod
    def _get_default_config_path() -> str:
        """기본 설정 파일 경로 반환"""
        # 환경 변수로 오버라이드 가능
        env_path = os.getenv("SIP_PBX_CONFIG_PATH")
        if env_path:
            return env_path
        
        # 프로젝트 루트/config/config.yaml
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        return str(project_root / "config" / "config.yaml")

    def load(self) -> Config:
        """설정 파일 로드 및 검증
        
        Returns:
            Config: 검증된 설정 객체
            
        Raises:
            FileNotFoundError: 설정 파일이 없는 경우
            ValidationError: 설정 검증 실패 시
            yaml.YAMLError: YAML 파싱 실패 시
        """
        if not Path(self.config_path).exists():
            raise FileNotFoundError(
                f"설정 파일을 찾을 수 없습니다: {self.config_path}\n"
                f"config/config.example.yaml을 복사하여 config/config.yaml을 생성하세요."
            )

        # YAML 파일 로드
        with open(self.config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        if raw_config is None:
            raw_config = {}

        # 환경 변수로 오버라이드
        raw_config = self._apply_env_overrides(raw_config)

        # Pydantic 검증
        try:
            self._config = Config(**raw_config)
            return self._config
        except ValidationError as e:
            error_msg = self._format_validation_error(e)
            # ValidationError를 다시 raise (메시지만 수정)
            raise

    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """환경 변수로 설정 오버라이드
        
        환경 변수 형식: SIP_PBX_<SECTION>_<KEY>
        예: SIP_PBX_SIP_LISTEN_PORT=5061
        
        Args:
            config: 원본 설정 딕셔너리
            
        Returns:
            Dict: 환경 변수가 적용된 설정
        """
        env_prefix = "SIP_PBX_"
        
        for env_key, env_value in os.environ.items():
            if not env_key.startswith(env_prefix):
                continue
            
            # SIP_PBX_SIP_LISTEN_PORT -> ['sip', 'listen_port']
            # 첫 번째는 section, 나머지는 key path
            parts = env_key[len(env_prefix):].lower().split('_')
            
            if len(parts) < 2:
                continue
            
            section = parts[0]
            key_path = '_'.join(parts[1:])
            
            # Section이 존재하지 않으면 생성
            if section not in config:
                config[section] = {}
            
            # 값 변환 (문자열 → 적절한 타입)
            config[section][key_path] = self._convert_env_value(env_value)
        
        return config

    @staticmethod
    def _convert_env_value(value: str) -> Any:
        """환경 변수 값을 적절한 타입으로 변환"""
        # Boolean
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False
        
        # Integer
        try:
            return int(value)
        except ValueError:
            pass
        
        # Float
        try:
            return float(value)
        except ValueError:
            pass
        
        # String (기본값)
        return value

    @staticmethod
    def _format_validation_error(error: ValidationError) -> str:
        """ValidationError를 사용자 친화적인 메시지로 변환"""
        errors = []
        for err in error.errors():
            loc = " → ".join(str(l) for l in err['loc'])
            msg = err['msg']
            errors.append(f"  • {loc}: {msg}")
        
        return "설정 검증 오류:\n" + "\n".join(errors)

    def reload(self) -> Config:
        """설정 파일 재로드
        
        Returns:
            Config: 재로드된 설정 객체
        """
        return self.load()

    @property
    def config(self) -> Config:
        """현재 로드된 설정 반환
        
        Returns:
            Config: 설정 객체
            
        Raises:
            RuntimeError: 설정이 아직 로드되지 않은 경우
        """
        if self._config is None:
            raise RuntimeError(
                "설정이 로드되지 않았습니다. load() 메서드를 먼저 호출하세요."
            )
        return self._config


def load_config(config_path: Optional[str] = None) -> Config:
    """설정 파일 로드 편의 함수
    
    Args:
        config_path: 설정 파일 경로
        
    Returns:
        Config: 검증된 설정 객체
    """
    loader = ConfigLoader(config_path)
    return loader.load()

