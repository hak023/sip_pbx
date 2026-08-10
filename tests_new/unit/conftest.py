"""
tests_new/unit 공통 픽스처.

Epic 2 Story 2.2에서 `settings_catalog.py`가 DB(Story 2.1) 활성 버전을 우선 사용하도록
바뀌었다. 개발 DB(`data/booking.db`)에는 마이그레이션 스크립트로 이미 카탈로그 설정이
시드되어 있을 수 있으므로, 별도로 DB 동적 로딩 자체를 검증하는 테스트가 아닌 한
`catalog_config_loader.get_cached_config()`가 항상 None을 반환하도록 강제해 기존 단위
테스트들이 하드코딩 폴백(`_CATALOG`)을 대상으로 동작하도록 격리한다(IV1: 리팩터링 전후
외부 동작 무변경 검증이 실제 개발 DB 상태에 좌우되지 않도록 하기 위함).

DB 동적 로딩 자체를 검증하는 테스트는 이 오토유즈 픽스처를
`monkeypatch.setattr(catalog_config_loader, "get_cached_config", ...)`로 개별 재정의한다.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_dynamic_catalog_loader(monkeypatch):
    from src.ai_voicebot.self_service import catalog_config_loader

    monkeypatch.setattr(catalog_config_loader, "get_cached_config", lambda config_kind, owner="": None)
    yield
