"""
시간 표현 정규화 테스트

TemporalExpressionNormalizer 클래스의 모든 기능을 테스트합니다.
"""

import pytest
from datetime import datetime, timedelta
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ai_voicebot.temporal.normalizer import TemporalExpressionNormalizer


class TestBasicRelativeDates:
    """기본 상대 날짜 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        """테스트용 normalizer (기준: 2026-03-10 17:30)"""
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_today(self, normalizer):
        """오늘"""
        result = normalizer.rewrite_query("오늘 날씨")
        assert result == "2026년 03월 10일 날씨"
    
    def test_tomorrow(self, normalizer):
        """내일"""
        result = normalizer.rewrite_query("내일 날씨")
        assert result == "2026년 03월 11일 날씨"
    
    def test_day_after_tomorrow(self, normalizer):
        """모레"""
        result = normalizer.rewrite_query("모레 날씨")
        assert result == "2026년 03월 12일 날씨"
    
    def test_yesterday(self, normalizer):
        """어제"""
        result = normalizer.rewrite_query("어제 날씨")
        assert result == "2026년 03월 09일 날씨"
    
    def test_day_before_yesterday(self, normalizer):
        """그제/그저께"""
        result1 = normalizer.rewrite_query("그제 날씨")
        result2 = normalizer.rewrite_query("그저께 날씨")
        assert result1 == "2026년 03월 08일 날씨"
        assert result2 == "2026년 03월 08일 날씨"


class TestDayOffset:
    """N일 전/후 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_days_after(self, normalizer):
        """N일 후"""
        assert normalizer.rewrite_query("3일 후 날씨") == "2026년 03월 13일 날씨"
        assert normalizer.rewrite_query("5일 후 예보") == "2026년 03월 15일 예보"
        assert normalizer.rewrite_query("10일 후") == "2026년 03월 20일"
    
    def test_days_before(self, normalizer):
        """N일 전"""
        assert normalizer.rewrite_query("3일 전 날씨") == "2026년 03월 07일 날씨"
        assert normalizer.rewrite_query("7일 전 기온") == "2026년 03월 03일 기온"
    
    def test_week_offset(self, normalizer):
        """N주 전/후"""
        assert normalizer.rewrite_query("2주 후 날씨") == "2026년 03월 24일 날씨"
        assert normalizer.rewrite_query("1주 전 날씨") == "2026년 03월 03일 날씨"
        assert normalizer.rewrite_query("일주일 후 날씨") == "2026년 03월 17일 날씨"


class TestWeekExpressions:
    """주간 표현 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        # 2026-03-10은 화요일
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_this_week(self, normalizer):
        """이번주"""
        result = normalizer.rewrite_query("이번주 날씨")
        # 이번주 월요일 = 2026-03-09
        assert result == "2026년 03월 09일 날씨"
    
    def test_next_week(self, normalizer):
        """다음주"""
        result = normalizer.rewrite_query("다음주 날씨")
        # 다음주 월요일 = 2026-03-16
        assert result == "2026년 03월 16일 날씨"
    
    def test_last_week(self, normalizer):
        """지난주"""
        result = normalizer.rewrite_query("지난주 날씨")
        # 지난주 월요일 = 2026-03-02
        assert result == "2026년 03월 02일 날씨"
    
    def test_week_with_weekday(self, normalizer):
        """이번주/다음주/지난주 + 요일"""
        # 이번주 월요일 = 2026-03-09
        assert normalizer.rewrite_query("이번주 월요일") == "2026년 03월 09일"
        
        # 다음주 수요일 = 2026-03-18
        assert normalizer.rewrite_query("다음주 수요일") == "2026년 03월 18일"
        
        # 지난주 금요일 = 2026-03-06
        assert normalizer.rewrite_query("지난주 금요일") == "2026년 03월 06일"


class TestMonthExpressions:
    """월간 표현 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_this_month(self, normalizer):
        """이번달"""
        result = normalizer.rewrite_query("이번달 날씨")
        assert result == "2026년 03월 01일 날씨"
    
    def test_next_month(self, normalizer):
        """다음달"""
        result = normalizer.rewrite_query("다음달 날씨")
        assert result == "2026년 04월 01일 날씨"
    
    def test_last_month(self, normalizer):
        """지난달"""
        result = normalizer.rewrite_query("지난달 날씨")
        assert result == "2026년 02월 01일 날씨"


class TestYearExpressions:
    """연간 표현 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_this_year(self, normalizer):
        """올해"""
        result = normalizer.rewrite_query("올해 기후")
        assert result == "2026년 01월 01일 기후"
    
    def test_next_year(self, normalizer):
        """내년"""
        result = normalizer.rewrite_query("내년 전망")
        assert result == "2027년 01월 01일 전망"
    
    def test_last_year(self, normalizer):
        """작년"""
        result = normalizer.rewrite_query("작년 데이터")
        assert result == "2025년 01월 01일 데이터"


class TestComplexExpressions:
    """복합 표현 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_multiple_expressions(self, normalizer):
        """여러 시간 표현 포함"""
        result = normalizer.rewrite_query("오늘과 내일 날씨")
        assert result == "2026년 03월 10일과 2026년 03월 11일 날씨"
    
    def test_mixed_expressions(self, normalizer):
        """다양한 시간 표현 혼합"""
        result = normalizer.rewrite_query("어제와 오늘, 내일 비교")
        assert result == "2026년 03월 09일와 2026년 03월 10일, 2026년 03월 11일 비교"
    
    def test_expression_in_sentence(self, normalizer):
        """문장 중간에 시간 표현"""
        result = normalizer.rewrite_query("서울의 내일 날씨를 알려줘")
        assert result == "서울의 2026년 03월 11일 날씨를 알려줘"


class TestNoTemporalExpression:
    """시간 표현 없는 경우 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_no_expression(self, normalizer):
        """시간 표현 없음 - 원본 그대로 반환"""
        original = "서울 날씨 알려줘"
        result = normalizer.rewrite_query(original)
        assert result == original
    
    def test_only_location(self, normalizer):
        """장소만 포함"""
        original = "부산 기온"
        result = normalizer.rewrite_query(original)
        assert result == original


class TestEdgeCases:
    """엣지 케이스 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_empty_string(self, normalizer):
        """빈 문자열"""
        result = normalizer.rewrite_query("")
        assert result == ""
    
    def test_whitespace_variations(self, normalizer):
        """공백 변형"""
        # 공백 있음
        assert "2026년 03월 11일" in normalizer.rewrite_query("내일  날씨")
        # 공백 여러 개
        assert "2026년 03월 11일" in normalizer.rewrite_query("내일   날씨")
    
    def test_priority_order(self, normalizer):
        """우선순위 테스트 - "모레"가 "내일"보다 먼저 매칭되어야 함"""
        result = normalizer.rewrite_query("모레 날씨")
        # "모레"가 "내일"로 잘못 매칭되지 않아야 함
        assert "12일" in result
        assert "11일" not in result


class TestExtractAndNormalize:
    """extract_and_normalize 메서드 테스트"""
    
    @pytest.fixture
    def normalizer(self):
        base_time = datetime(2026, 3, 10, 17, 30, 0)
        return TemporalExpressionNormalizer(base_time=base_time)
    
    def test_extract_single(self, normalizer):
        """단일 표현 추출"""
        results = normalizer.extract_and_normalize("내일 날씨")
        assert len(results) == 1
        assert results[0][0] == "내일"
        assert results[0][2] == "2026년 03월 11일"
    
    def test_extract_multiple(self, normalizer):
        """여러 표현 추출"""
        results = normalizer.extract_and_normalize("오늘과 내일 날씨")
        assert len(results) == 2
        assert results[0][0] == "오늘"
        assert results[1][0] == "내일"


if __name__ == "__main__":
    # pytest 실행
    pytest.main([__file__, "-v", "--tb=short"])
