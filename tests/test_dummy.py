"""더미 테스트

프로젝트 구조 및 pytest가 정상 동작하는지 확인하기 위한 초기 테스트
"""

def test_dummy_success():
    """기본 테스트 성공"""
    assert True


def test_simple_math():
    """간단한 계산 테스트"""
    assert 2 + 2 == 4


def test_string_concatenation():
    """문자열 연결 테스트"""
    result = "Hello" + " " + "World"
    assert result == "Hello World"

