'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';
import type { Booking } from '@/types';
import { BOOKING_STATUS_LABELS, BOOKING_STATUS_COLORS } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Google Calendar 이벤트 컴포넌트 ──────────────────────────────────────────

interface GcalEvent {
  id: string;
  summary: string;
  description?: string;
  start: string;
  end: string;
  status?: string;
  booking_id?: string;
  html_link?: string;
}

function GoogleCalendarTab({ owner }: { owner: string }) {
  const today = new Date();
  const [dateFrom, setDateFrom] = useState(
    () => today.toISOString().split('T')[0]
  );
  const [dateTo, setDateTo] = useState(() => {
    const d = new Date(today);
    d.setDate(d.getDate() + 30);
    return d.toISOString().split('T')[0];
  });
  const [events, setEvents] = useState<GcalEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [error, setError] = useState('');

  const checkStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/google/oauth/status?owner=${encodeURIComponent(owner)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setConnected(data.connected ?? false);
    } catch {
      setConnected(false);
    }
  }, [owner]);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ owner, date_from: dateFrom, date_to: dateTo });
      const res = await fetch(`${API_BASE}/api/google/calendar/events?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setEvents(data.events || []);
    } catch (e: unknown) {
      setError(`이벤트 조회 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [owner, dateFrom, dateTo]);

  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  useEffect(() => {
    if (connected) fetchEvents();
  }, [connected, fetchEvents]);

  if (connected === null) {
    return <div className="py-8 text-center text-gray-400 text-sm">연동 상태 확인 중…</div>;
  }

  if (!connected) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-6 py-8 text-center">
        <p className="text-lg font-medium text-amber-800 mb-2">Google Calendar 연동이 필요합니다</p>
        <p className="text-sm text-amber-600 mb-4">
          설정 페이지에서 Google 계정을 연동하면 예약이 캘린더에 자동 동기화됩니다.
        </p>
        <Link
          href="/settings/general"
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
        >
          ⚙️ 설정으로 이동
        </Link>
      </div>
    );
  }

  const formatEventDate = (s: string) => {
    try {
      return new Date(s).toLocaleString('ko-KR', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
      });
    } catch { return s; }
  };

  return (
    <div className="space-y-4">
      {/* 조회 기간 선택 */}
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">시작일</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">종료일</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <button
          onClick={fetchEvents}
          disabled={loading}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? '조회 중…' : '조회'}
        </button>
        <span className="text-sm text-gray-500 ml-auto">
          {events.length}건
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* 이벤트 목록 */}
      {loading ? (
        <div className="py-8 text-center text-gray-400 text-sm">로딩 중…</div>
      ) : events.length === 0 ? (
        <div className="py-8 text-center text-gray-400 text-sm">
          조회 기간에 Google Calendar 이벤트가 없습니다.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-700">제목</th>
                <th className="px-4 py-3 text-left font-medium text-gray-700">시작</th>
                <th className="px-4 py-3 text-left font-medium text-gray-700">종료</th>
                <th className="px-4 py-3 text-left font-medium text-gray-700">상태</th>
                <th className="px-4 py-3 text-left font-medium text-gray-700">예약번호</th>
                <th className="px-4 py-3 text-left font-medium text-gray-700">링크</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {events.map((ev) => (
                <tr key={ev.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{ev.summary}</td>
                  <td className="px-4 py-3 text-gray-600">{formatEventDate(ev.start)}</td>
                  <td className="px-4 py-3 text-gray-600">{formatEventDate(ev.end)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                      ev.status === 'cancelled'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-green-100 text-green-700'
                    }`}>
                      {ev.status === 'cancelled' ? '취소됨' : '활성'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">
                    {ev.booking_id || '-'}
                  </td>
                  <td className="px-4 py-3">
                    {ev.html_link ? (
                      <a
                        href={ev.html_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline text-xs"
                      >
                        캘린더 열기 ↗
                      </a>
                    ) : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface BookingListResponse {
  total: number;
  items: Booking[];
}

type ViewMode = 'daily' | 'monthly';
type MainTab = 'bookings' | 'gcalendar';

const STATUS_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'confirmed', label: '확정' },
  { value: 'cancelled', label: '취소' },
  { value: 'no_show', label: '노쇼' },
  { value: 'completed', label: '완료' },
];

function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDisplayDate(dateStr: string): string {
  const [y, m, d] = dateStr.split('-');
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  const dayNames = ['일', '월', '화', '수', '목', '금', '토'];
  return `${y}년 ${Number(m)}월 ${Number(d)}일 (${dayNames[date.getDay()]})`;
}

function formatDisplayMonth(year: number, month: number): string {
  return `${year}년 ${month}월`;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function getFirstDayOfMonth(year: number, month: number): number {
  return new Date(year, month - 1, 1).getDay();
}

export default function BookingListPage() {
  const today = new Date();

  const [mainTab, setMainTab] = useState<MainTab>('bookings');
  const [viewMode, setViewMode] = useState<ViewMode>('daily');
  const [currentDate, setCurrentDate] = useState<Date>(today);
  const [currentYear, setCurrentYear] = useState(today.getFullYear());
  const [currentMonth, setCurrentMonth] = useState(today.getMonth() + 1);

  const [bookings, setBookings] = useState<Booking[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterPhone, setFilterPhone] = useState('');
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  // 월별 뷰에서 선택된 날짜 (달력 셀 클릭 시)
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const owner = getTenantOwner();

  const fetchBookings = useCallback(async (dateParam?: string) => {
    if (!owner) return;
    setLoading(true);
    setError('');

    const params = new URLSearchParams({ owner });

    if (viewMode === 'daily') {
      params.set('slot_date', toDateStr(currentDate));
    } else if (selectedDate) {
      params.set('slot_date', selectedDate);
    } else {
      // 월 전체: slot_date 파라미터 없이 조회 후 클라이언트 필터
      const monthStr = `${currentYear}-${String(currentMonth).padStart(2, '0')}`;
      params.set('slot_month', monthStr);
    }

    if (filterStatus) params.set('status', filterStatus);
    if (filterPhone) params.set('customer_phone', filterPhone);
    if (dateParam) params.set('slot_date', dateParam);

    const res = await apiJson<BookingListResponse>(`/api/booking?${params}`);
    if (res.ok) {
      setBookings(res.data.items);
      setTotal(res.data.total);
    } else {
      setError(res.message);
    }
    setLoading(false);
  }, [owner, viewMode, currentDate, currentYear, currentMonth, selectedDate, filterStatus, filterPhone]);

  useEffect(() => {
    fetchBookings();
  }, [fetchBookings]);

  // 일별 네비게이션
  const goToPrevDay = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() - 1);
    setCurrentDate(d);
  };

  const goToNextDay = () => {
    const d = new Date(currentDate);
    d.setDate(d.getDate() + 1);
    setCurrentDate(d);
  };

  // 월별 네비게이션
  const goToPrevMonth = () => {
    if (currentMonth === 1) {
      setCurrentYear((y) => y - 1);
      setCurrentMonth(12);
    } else {
      setCurrentMonth((m) => m - 1);
    }
    setSelectedDate(null);
  };

  const goToNextMonth = () => {
    if (currentMonth === 12) {
      setCurrentYear((y) => y + 1);
      setCurrentMonth(1);
    } else {
      setCurrentMonth((m) => m + 1);
    }
    setSelectedDate(null);
  };

  const handleModeChange = (mode: ViewMode) => {
    setViewMode(mode);
    setSelectedDate(null);
    if (mode === 'daily') {
      setCurrentDate(today);
    } else {
      setCurrentYear(today.getFullYear());
      setCurrentMonth(today.getMonth() + 1);
    }
  };

  const handleStatusChange = async (bookingId: string, newStatus: string) => {
    setUpdatingId(bookingId);
    if (newStatus === 'cancelled') {
      const res = await apiJson(`/api/booking/${bookingId}`, { method: 'DELETE' });
      if (!res.ok) alert(`취소 실패: ${res.message}`);
    } else {
      const res = await apiJson(`/api/booking/${bookingId}`, {
        method: 'PUT',
        body: { status: newStatus },
      });
      if (!res.ok) alert(`상태 변경 실패: ${res.message}`);
    }
    setUpdatingId(null);
    fetchBookings();
  };

  // 달력 데이터 계산
  const daysInMonth = getDaysInMonth(currentYear, currentMonth);
  const firstDayOfWeek = getFirstDayOfMonth(currentYear, currentMonth);
  const calendarCells: (number | null)[] = [
    ...Array(firstDayOfWeek).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  // 달력에서 날짜별 예약 수 집계 (월별 전체 데이터 기준)
  const bookingCountByDate = bookings.reduce<Record<string, number>>((acc, b) => {
    if (b.slot_date) {
      acc[b.slot_date] = (acc[b.slot_date] || 0) + 1;
    }
    return acc;
  }, {});

  // 월별 모드에서 날짜 선택 시 해당 날짜 예약만 필터링
  const displayedBookings = viewMode === 'monthly' && selectedDate
    ? bookings.filter((b) => b.slot_date === selectedDate)
    : bookings;

  const todayStr = toDateStr(today);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* 헤더 */}
      <div className="flex justify-between items-center mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">예약 관리</h1>
          {mainTab === 'bookings' && (
            <p className="text-sm text-gray-500 mt-1">
              {viewMode === 'daily'
                ? `${formatDisplayDate(toDateStr(currentDate))} · ${total}건`
                : selectedDate
                  ? `${formatDisplayDate(selectedDate)} · ${displayedBookings.length}건`
                  : `${formatDisplayMonth(currentYear, currentMonth)} · 전체 ${total}건`}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Link
            href="/booking/domains"
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            도메인 관리
          </Link>
          <Link
            href="/booking/slots"
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            슬롯 관리
          </Link>
        </div>
      </div>

      {/* 메인 탭 */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        <button
          onClick={() => setMainTab('bookings')}
          className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
            mainTab === 'bookings'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          📋 예약 목록
        </button>
        <button
          onClick={() => setMainTab('gcalendar')}
          className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
            mainTab === 'gcalendar'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          📅 Google 캘린더
        </button>
      </div>

      {/* Google Calendar 탭 */}
      {mainTab === 'gcalendar' && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <GoogleCalendarTab owner={owner} />
        </div>
      )}

      {/* 예약 목록 탭 */}
      {mainTab === 'bookings' && (<>

      {/* 날짜 네비게이터 */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
        <div className="flex items-center justify-between">
          {/* 뷰 모드 토글 */}
          <div className="flex rounded-lg border border-gray-300 overflow-hidden">
            <button
              onClick={() => handleModeChange('daily')}
              className={`px-4 py-2 text-sm font-medium transition-colors ${
                viewMode === 'daily'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              일별
            </button>
            <button
              onClick={() => handleModeChange('monthly')}
              className={`px-4 py-2 text-sm font-medium transition-colors border-l border-gray-300 ${
                viewMode === 'monthly'
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50'
              }`}
            >
              월별
            </button>
          </div>

          {/* 날짜 네비게이션 */}
          <div className="flex items-center gap-3">
            <button
              onClick={viewMode === 'daily' ? goToPrevDay : goToPrevMonth}
              className="p-2 rounded-lg border border-gray-300 hover:bg-gray-50 transition-colors text-gray-700"
              aria-label="이전"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>

            <span className="text-base font-semibold text-gray-900 min-w-[160px] text-center">
              {viewMode === 'daily'
                ? formatDisplayDate(toDateStr(currentDate))
                : formatDisplayMonth(currentYear, currentMonth)}
            </span>

            <button
              onClick={viewMode === 'daily' ? goToNextDay : goToNextMonth}
              className="p-2 rounded-lg border border-gray-300 hover:bg-gray-50 transition-colors text-gray-700"
              aria-label="다음"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>

            <button
              onClick={() => {
                if (viewMode === 'daily') {
                  setCurrentDate(today);
                } else {
                  setCurrentYear(today.getFullYear());
                  setCurrentMonth(today.getMonth() + 1);
                  setSelectedDate(null);
                }
              }}
              className="px-3 py-2 text-sm font-medium text-indigo-600 border border-indigo-300 rounded-lg hover:bg-indigo-50 transition-colors"
            >
              오늘
            </button>
          </div>
        </div>
      </div>

      {/* 월별 달력 */}
      {viewMode === 'monthly' && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
          <div className="grid grid-cols-7 mb-2">
            {['일', '월', '화', '수', '목', '금', '토'].map((d) => (
              <div
                key={d}
                className={`text-center text-xs font-semibold py-1 ${
                  d === '일' ? 'text-red-500' : d === '토' ? 'text-blue-500' : 'text-gray-500'
                }`}
              >
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {calendarCells.map((day, idx) => {
              if (day === null) {
                return <div key={`empty-${idx}`} />;
              }
              const dateStr = `${currentYear}-${String(currentMonth).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
              const isToday = dateStr === todayStr;
              const isSelected = dateStr === selectedDate;
              const count = bookingCountByDate[dateStr] || 0;
              const dayOfWeek = (firstDayOfWeek + day - 1) % 7;

              return (
                <button
                  key={day}
                  onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                  className={`relative flex flex-col items-center justify-start rounded-lg py-2 px-1 min-h-[56px] transition-all text-sm font-medium border ${
                    isSelected
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : isToday
                        ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
                        : 'border-transparent hover:border-gray-200 hover:bg-gray-50 text-gray-800'
                  } ${dayOfWeek === 0 ? 'text-red-500' : ''} ${dayOfWeek === 6 ? 'text-blue-500' : ''} ${
                    isSelected ? '!text-white' : ''
                  }`}
                >
                  <span>{day}</span>
                  {count > 0 && (
                    <span
                      className={`mt-1 text-xs font-semibold px-1.5 py-0.5 rounded-full ${
                        isSelected
                          ? 'bg-white text-indigo-600'
                          : 'bg-indigo-100 text-indigo-700'
                      }`}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          {selectedDate && (
            <div className="mt-3 flex items-center justify-between text-sm text-gray-600 border-t pt-3">
              <span>
                <span className="font-medium text-gray-900">{formatDisplayDate(selectedDate)}</span> 예약 {displayedBookings.length}건
              </span>
              <button
                onClick={() => setSelectedDate(null)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                선택 해제
              </button>
            </div>
          )}
        </div>
      )}

      {/* 필터 영역 */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4 flex flex-wrap gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">상태</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">전화번호</label>
          <input
            type="text"
            value={filterPhone}
            onChange={(e) => setFilterPhone(e.target.value)}
            placeholder="010-0000-0000"
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div className="flex items-end">
          <button
            onClick={() => fetchBookings()}
            className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            검색
          </button>
        </div>
      </div>

      {/* 예약 테이블 */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="flex justify-center items-center h-40 text-gray-500">불러오는 중...</div>
        ) : error ? (
          <div className="flex justify-center items-center h-40 text-red-500">{error}</div>
        ) : displayedBookings.length === 0 ? (
          <div className="flex flex-col justify-center items-center h-40 text-gray-400 gap-1">
            <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <span className="text-sm">예약 내역이 없습니다.</span>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">예약번호</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">날짜/시간</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">예약자</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">전화번호</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">인원</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">서비스</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">상태</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">메모</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">액션</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {displayedBookings.map((b) => (
                <tr key={b.booking_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs text-gray-600">{b.booking_id}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="font-medium text-gray-900">{b.slot_date}</div>
                    <div className="text-gray-500">{b.slot_time}</div>
                  </td>
                  <td className="px-4 py-3 text-gray-900">{b.customer_name || '-'}</td>
                  <td className="px-4 py-3 text-gray-600">{b.customer_phone || '-'}</td>
                  <td className="px-4 py-3 text-center text-gray-900">{b.party_size}명</td>
                  <td className="px-4 py-3 text-gray-600">{b.service_type || '-'}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${BOOKING_STATUS_COLORS[b.status] || 'bg-gray-100 text-gray-600'}`}>
                      {BOOKING_STATUS_LABELS[b.status] || b.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-500 max-w-[120px] truncate">{b.memo || '-'}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {b.status === 'confirmed' && (
                        <>
                          <button
                            onClick={() => handleStatusChange(b.booking_id, 'completed')}
                            disabled={updatingId === b.booking_id}
                            className="px-2 py-1 text-xs font-medium text-blue-700 bg-blue-50 rounded hover:bg-blue-100 disabled:opacity-50"
                          >
                            완료
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('예약을 취소하시겠습니까?')) {
                                handleStatusChange(b.booking_id, 'cancelled');
                              }
                            }}
                            disabled={updatingId === b.booking_id}
                            className="px-2 py-1 text-xs font-medium text-red-700 bg-red-50 rounded hover:bg-red-100 disabled:opacity-50"
                          >
                            취소
                          </button>
                          <button
                            onClick={() => handleStatusChange(b.booking_id, 'no_show')}
                            disabled={updatingId === b.booking_id}
                            className="px-2 py-1 text-xs font-medium text-yellow-700 bg-yellow-50 rounded hover:bg-yellow-100 disabled:opacity-50"
                          >
                            노쇼
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      </>)}
    </div>
  );
}
