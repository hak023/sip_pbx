"""
시간 표현 정규화 (Temporal Expression Normalization)

사용자 발화의 상대적 시간 표현("오늘", "내일", "어제" 등)을
절대 날짜로 변환하여 RAG 검색 정확도를 향상시킵니다.

사용 예시:
    normalizer = TemporalExpressionNormalizer()
    result = normalizer.rewrite_query("내일 날씨 알려줘")
    # → "2026년 3월 11일 날씨 알려줘"
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)


class TemporalExpressionNormalizer:
    """한국어 시간 표현을 절대 날짜로 변환하는 클래스"""
    
    # 한국어 요일 매핑
    WEEKDAY_MAP = {
        '월': 0, '화': 1, '수': 2, '목': 3,
        '금': 4, '토': 5, '일': 6
    }
    
    def __init__(self, base_time: Optional[datetime] = None, timezone: str = "Asia/Seoul"):
        """
        Args:
            base_time: 기준 시간 (통화 시작 시간). None이면 현재 시간 사용
            timezone: 타임존 (기본: Asia/Seoul)
        """
        self.base_time = base_time or datetime.now()
        self.timezone = timezone
    
    def extract_expressions(self, text: str) -> List[Dict]:
        """
        텍스트에서 모든 시간 표현 추출
        
        Args:
            text: 사용자 발화 텍스트
        
        Returns:
            [
                {'text': '내일', 'start': 0, 'end': 2, 'type': 'relative_day'},
                {'text': '3일 후', 'start': 10, 'end': 14, 'type': 'day_offset'},
                ...
            ]
        """
        expressions = []
        
        # 패턴 정의 (우선순위 순서 - 길고 구체적인 것부터)
        patterns = [
            # 요일 포함 주간 표현 (가장 우선)
            (r'(이번|다음|지난)\s*주\s*(월|화|수|목|금|토|일)요일', 'week_with_day'),
            
            # N일/주/달 전/후
            (r'(\d+)\s*일\s*[전후]', 'day_offset'),
            (r'(\d+)\s*주\s*[전후]', 'week_offset'),
            (r'일주일\s*[전후]', 'week_offset'),
            (r'(\d+)\s*개?월\s*[전후]', 'month_offset'),
            
            # 주간 표현
            (r'이번\s*주', 'this_week'),
            (r'다음\s*주', 'next_week'),
            (r'지난\s*주', 'last_week'),
            
            # 월간 표현
            (r'이번\s*달', 'this_month'),
            (r'다음\s*달', 'next_month'),
            (r'지난\s*달', 'last_month'),
            
            # 연간 표현
            (r'올해', 'this_year'),
            (r'내년', 'next_year'),
            (r'작년', 'last_year'),
            
            # 기본 상대 날짜
            (r'모레', 'day_after_tomorrow'),  # "내일" 보다 먼저 체크
            (r'내일', 'tomorrow'),
            (r'오늘', 'today'),
            (r'그저께|그제', 'day_before_yesterday'),
            (r'어제', 'yesterday'),
            
            # 즉시성 표현
            (r'방금|아까|좀\s*전|조금\s*전', 'just_now'),
            (r'지금|현재', 'now'),
        ]
        
        for pattern, expr_type in patterns:
            for match in re.finditer(pattern, text):
                # 이미 추출된 범위와 겹치지 않는지 확인
                start, end = match.span()
                if not any(e['start'] <= start < e['end'] or e['start'] < end <= e['end'] 
                          for e in expressions):
                    expressions.append({
                        'text': match.group(),
                        'start': start,
                        'end': end,
                        'type': expr_type,
                        'match': match
                    })
        
        # 시작 위치 순으로 정렬
        expressions.sort(key=lambda x: x['start'])
        
        return expressions
    
    def normalize_expression(self, expression: Dict) -> Optional[datetime]:
        """
        시간 표현을 datetime 객체로 변환
        
        Args:
            expression: extract_expressions()가 반환한 딕셔너리
        
        Returns:
            변환된 datetime 객체 또는 None
        """
        text = expression['text']
        expr_type = expression['type']
        match = expression.get('match')
        
        # 기본 상대 날짜
        if expr_type == 'today':
            return self.base_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'tomorrow':
            return (self.base_time + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'day_after_tomorrow':
            return (self.base_time + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'yesterday':
            return (self.base_time - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'day_before_yesterday':
            return (self.base_time - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # N일 전/후
        elif expr_type == 'day_offset':
            m = re.search(r'(\d+)\s*일\s*(전|후)', text)
            if m:
                days = int(m.group(1))
                direction = m.group(2)
                delta = timedelta(days=days)
                result = self.base_time + delta if direction == '후' else self.base_time - delta
                return result.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # N주 전/후 또는 일주일 전/후
        elif expr_type == 'week_offset':
            if '일주일' in text:
                weeks = 1
            else:
                m = re.search(r'(\d+)\s*주', text)
                weeks = int(m.group(1)) if m else 1
            
            direction = '후' if '후' in text else '전'
            delta = timedelta(weeks=weeks)
            result = self.base_time + delta if direction == '후' else self.base_time - delta
            return result.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # N개월 전/후
        elif expr_type == 'month_offset':
            m = re.search(r'(\d+)\s*개?월\s*(전|후)', text)
            if m:
                months = int(m.group(1))
                direction = m.group(2)
                # 월 계산 (간단한 방식: 30일 * 개월수)
                delta = timedelta(days=30 * months)
                result = self.base_time + delta if direction == '후' else self.base_time - delta
                return result.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 주간 표현
        elif expr_type == 'this_week':
            # 이번주 월요일
            days_since_monday = self.base_time.weekday()
            return (self.base_time - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'next_week':
            # 다음주 월요일
            days_since_monday = self.base_time.weekday()
            return (self.base_time + timedelta(days=7 - days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'last_week':
            # 지난주 월요일
            days_since_monday = self.base_time.weekday()
            return (self.base_time - timedelta(days=7 + days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 요일 포함 주간 표현
        elif expr_type == 'week_with_day':
            m = re.match(r'(이번|다음|지난)\s*주\s*(월|화|수|목|금|토|일)요일', text)
            if m:
                week_type = m.group(1)
                weekday_kr = m.group(2)
                target_weekday = self.WEEKDAY_MAP[weekday_kr]
                
                # 현재 요일
                current_weekday = self.base_time.weekday()
                
                if week_type == '이번':
                    # 이번주 해당 요일
                    days_diff = target_weekday - current_weekday
                    result = self.base_time + timedelta(days=days_diff)
                elif week_type == '다음':
                    # 다음주 해당 요일
                    days_diff = target_weekday - current_weekday + 7
                    result = self.base_time + timedelta(days=days_diff)
                else:  # 지난
                    # 지난주 해당 요일
                    days_diff = target_weekday - current_weekday - 7
                    result = self.base_time + timedelta(days=days_diff)
                
                return result.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 월간 표현 (해당 월의 1일 반환)
        elif expr_type == 'this_month':
            return self.base_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'next_month':
            if self.base_time.month == 12:
                return self.base_time.replace(year=self.base_time.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                return self.base_time.replace(month=self.base_time.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'last_month':
            if self.base_time.month == 1:
                return self.base_time.replace(year=self.base_time.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                return self.base_time.replace(month=self.base_time.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 연간 표현
        elif expr_type == 'this_year':
            return self.base_time.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'next_year':
            return self.base_time.replace(year=self.base_time.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        elif expr_type == 'last_year':
            return self.base_time.replace(year=self.base_time.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # 즉시성 표현 (현재 시간 그대로)
        elif expr_type in ('now', 'just_now'):
            return self.base_time
        
        return None
    
    def format_date(self, dt: datetime, include_time: bool = False) -> str:
        """
        datetime을 한국어 날짜 문자열로 변환
        
        Args:
            dt: datetime 객체
            include_time: 시간 포함 여부
        
        Returns:
            "2026년 03월 11일" 또는 "2026년 03월 11일 17시 30분"
        """
        if include_time:
            return dt.strftime('%Y년 %m월 %d일 %H시 %M분')
        else:
            return dt.strftime('%Y년 %m월 %d일')
    
    def rewrite_query(self, query: str) -> str:
        """
        사용자 query에서 시간 표현을 절대 날짜로 재작성
        
        Args:
            query: 원본 query (예: "내일 날씨 알려줘")
        
        Returns:
            재작성된 query (예: "2026년 03월 11일 날씨 알려줘")
        """
        # 시간 표현 추출
        expressions = self.extract_expressions(query)
        
        if not expressions:
            # 시간 표현 없음
            logger.debug("temporal_expression_not_found",
                        query=query,
                        note="시간 표현 없음, 원본 query 사용")
            return query
        
        # 뒤에서부터 교체 (인덱스 변경 방지)
        expressions.sort(key=lambda x: x['start'], reverse=True)
        
        rewritten = query
        replaced_count = 0
        
        for expr in expressions:
            # 날짜로 변환
            dt = self.normalize_expression(expr)
            
            if dt:
                # 즉시성 표현은 시간 포함
                include_time = expr['type'] in ('now', 'just_now')
                formatted = self.format_date(dt, include_time=include_time)
                
                # 교체
                rewritten = (
                    rewritten[:expr['start']] +
                    formatted +
                    rewritten[expr['end']:]
                )
                replaced_count += 1
        
        # 로깅
        if replaced_count > 0:
            logger.info("temporal_expression_normalized",
                       original=query,
                       normalized=rewritten,
                       expressions_found=[e['text'] for e in expressions],
                       replaced_count=replaced_count,
                       base_time=self.base_time.isoformat(),
                       note="시간 표현을 절대 날짜로 변환")
        
        return rewritten
    
    def extract_and_normalize(self, query: str) -> List[Tuple[str, datetime, str]]:
        """
        시간 표현 추출 및 변환 결과 상세 반환 (디버깅/분석용)
        
        Args:
            query: 원본 query
        
        Returns:
            [(원본 표현, 변환된 날짜, 포맷된 문자열), ...]
        """
        expressions = self.extract_expressions(query)
        results = []
        
        for expr in expressions:
            dt = self.normalize_expression(expr)
            if dt:
                include_time = expr['type'] in ('now', 'just_now')
                formatted = self.format_date(dt, include_time=include_time)
                results.append((expr['text'], dt, formatted))
        
        return results
