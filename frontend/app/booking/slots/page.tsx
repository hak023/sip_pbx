'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';
import type { BookingSlot, BookingDomain } from '@/types';

interface SlotListResponse {
  total: number;
  items: BookingSlot[];
}

interface BulkResult {
  created: number;
  skipped: number;
  total_generated: number;
  preview: string[];
}

interface ExcludeWindow {
  start: string;
  end: string;
  label: string;
}

interface BulkForm {
  date_from: string;
  date_to: string;
  weekdays: number[];
  work_start: string;
  work_end: string;
  slot_duration_min: number;
  slot_interval_min: number;
  capacity: number;
  exclude_windows: ExcludeWindow[];
  skip_existing: boolean;
  domain_id: string;
}

interface NewSlotForm {
  slot_date: string;
  slot_time: string;
  capacity: number;
  domain_id: string;
}

type ViewMode = 'daily' | 'monthly';

const WEEKDAY_LABELS = ['월', '화', '수', '목', '금', '토', '일'];

function toDateStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function toMonthStr(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function formatDisplayDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' });
}

function formatDisplayMonth(year: number, month: number): string {
  return `${year}년 ${month}월`;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  const day = new Date(year, month - 1, 1).getDay();
  return day === 0 ? 6 : day - 1;
}

const today = new Date();
const EMPTY_SLOT_FORM: NewSlotForm = {
  slot_date: toDateStr(today),
  slot_time: '',
  capacity: 1,
  domain_id: '',
};

function makeDefaultBulkForm(): BulkForm {
  const from = toDateStr(today);
  const toDate = new Date(today);
  toDate.setDate(toDate.getDate() + 6);
  return {
    date_from: from,
    date_to: toDateStr(toDate),
    weekdays: [0, 1, 2, 3, 4],
    work_start: '09:00',
    work_end: '18:00',
    slot_duration_min: 60,
    slot_interval_min: 0,
    capacity: 1,
    exclude_windows: [{ start: '12:00', end: '13:00', label: '점심시간' }],
    skip_existing: true,
    domain_id: '',
  };
}


export default function SlotsPage() {
  const [viewMode, setViewMode] = useState<ViewMode>('daily');
  const [currentDate, setCurrentDate] = useState(toDateStr(today));
  const [currentYear, setCurrentYear] = useState(today.getFullYear());
  const [currentMonth, setCurrentMonth] = useState(today.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const [slots, setSlots] = useState<BookingSlot[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [showSlotForm, setShowSlotForm] = useState(false);
  const [slotForm, setSlotForm] = useState<NewSlotForm>(EMPTY_SLOT_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [showBulkForm, setShowBulkForm] = useState(false);
  const [bulkForm, setBulkForm] = useState<BulkForm>(makeDefaultBulkForm());
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);

  const [domains, setDomains] = useState<BookingDomain[]>([]);

  const owner = getTenantOwner();

  // ─── fetch ───────────────────────────────────
  const fetchSlots = useCallback(async () => {
    if (!owner) return;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({ owner, include_blocked: 'true', include_full: 'true' });

    if (viewMode === 'daily') {
      params.set('slot_date', currentDate);
    } else {
      if (selectedDate) {
        params.set('slot_date', selectedDate);
      } else {
        params.set('slot_month', `${currentYear}-${String(currentMonth).padStart(2, '0')}`);
      }
    }

    const res = await apiJson<SlotListResponse>(`/api/booking/slots?${params}`);
    if (res.ok) {
      setSlots(res.data.items);
      setTotal(res.data.total);
    } else {
      setError(res.message);
    }
    setLoading(false);
  }, [owner, viewMode, currentDate, currentYear, currentMonth, selectedDate]);

  useEffect(() => {
    fetchSlots();
  }, [fetchSlots]);

  // 도메인 목록 로드
  useEffect(() => {
    if (!owner) return;
    apiJson<{ total: number; items: BookingDomain[] }>(
      `/api/booking/domains?owner=${encodeURIComponent(owner)}`
    ).then(res => {
      if (res.ok) setDomains(res.data.items.filter(d => d.is_active));
    });
  }, [owner]);

  // ─── 뷰 전환 ─────────────────────────────────
  const handleModeChange = (mode: ViewMode) => {
    setViewMode(mode);
    setSelectedDate(null);
    if (mode === 'daily') {
      setCurrentDate(toDateStr(today));
    } else {
      setCurrentYear(today.getFullYear());
      setCurrentMonth(today.getMonth() + 1);
    }
  };

  const goToToday = () => {
    if (viewMode === 'daily') {
      setCurrentDate(toDateStr(today));
    } else {
      setCurrentYear(today.getFullYear());
      setCurrentMonth(today.getMonth() + 1);
      setSelectedDate(null);
    }
  };

  const goToPrev = () => {
    if (viewMode === 'daily') {
      const d = new Date(currentDate + 'T00:00:00');
      d.setDate(d.getDate() - 1);
      setCurrentDate(toDateStr(d));
    } else {
      setSelectedDate(null);
      if (currentMonth === 1) { setCurrentYear(y => y - 1); setCurrentMonth(12); }
      else setCurrentMonth(m => m - 1);
    }
  };

  const goToNext = () => {
    if (viewMode === 'daily') {
      const d = new Date(currentDate + 'T00:00:00');
      d.setDate(d.getDate() + 1);
      setCurrentDate(toDateStr(d));
    } else {
      setSelectedDate(null);
      if (currentMonth === 12) { setCurrentYear(y => y + 1); setCurrentMonth(1); }
      else setCurrentMonth(m => m + 1);
    }
  };

  // ─── 슬롯 CRUD ───────────────────────────────
  const handleCreateSlot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!owner) return;
    setSubmitting(true);
    const res = await apiJson(`/api/booking/slots?owner=${encodeURIComponent(owner)}`, {
      method: 'POST',
      body: slotForm as unknown as Record<string, unknown>,
    });
    if (res.ok) {
      setShowSlotForm(false);
      setSlotForm({ ...EMPTY_SLOT_FORM, slot_date: viewMode === 'daily' ? currentDate : (selectedDate || toDateStr(today)) });
      fetchSlots();
    } else {
      alert(`슬롯 생성 실패: ${res.message}`);
    }
    setSubmitting(false);
  };

  const handleToggleBlock = async (slot: BookingSlot) => {
    const res = await apiJson(`/api/booking/slots/${slot.slot_id}`, {
      method: 'PUT',
      body: { is_blocked: !slot.is_blocked },
    });
    if (!res.ok) alert(`변경 실패: ${res.message}`);
    else fetchSlots();
  };

  const handleDelete = async (slotId: string) => {
    if (!confirm('이 슬롯을 삭제하시겠습니까?\n연결된 예약이 있는 경우 주의하세요.')) return;
    setDeletingId(slotId);
    const res = await apiJson(`/api/booking/slots/${slotId}`, { method: 'DELETE' });
    if (!res.ok) alert(`삭제 실패: ${res.message}`);
    else fetchSlots();
    setDeletingId(null);
  };

  // ─── 일괄 생성 ───────────────────────────────
  const handleBulkCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!owner) return;
    setBulkSubmitting(true);
    setBulkResult(null);

    const body = {
      ...bulkForm,
      slot_interval_min: bulkForm.slot_interval_min || bulkForm.slot_duration_min,
    };
    const res = await apiJson<BulkResult>(`/api/booking/slots/bulk?owner=${encodeURIComponent(owner)}`, {
      method: 'POST',
      body,
    });
    if (res.ok) {
      setBulkResult(res.data);
      fetchSlots();
    } else {
      alert(`일괄 생성 실패: ${res.message}`);
    }
    setBulkSubmitting(false);
  };

  const toggleWeekday = (wd: number) => {
    setBulkForm(f => ({
      ...f,
      weekdays: f.weekdays.includes(wd)
        ? f.weekdays.filter(d => d !== wd)
        : [...f.weekdays, wd].sort(),
    }));
  };

  const addExcludeWindow = () => {
    setBulkForm(f => ({
      ...f,
      exclude_windows: [...f.exclude_windows, { start: '', end: '', label: '' }],
    }));
  };

  const updateExcludeWindow = (idx: number, field: keyof ExcludeWindow, value: string) => {
    setBulkForm(f => {
      const wins = [...f.exclude_windows];
      wins[idx] = { ...wins[idx], [field]: value };
      return { ...f, exclude_windows: wins };
    });
  };

  const removeExcludeWindow = (idx: number) => {
    setBulkForm(f => ({
      ...f,
      exclude_windows: f.exclude_windows.filter((_, i) => i !== idx),
    }));
  };

  // ─── 달력 헬퍼 ───────────────────────────────
  const daysInMonth = getDaysInMonth(currentYear, currentMonth);
  const firstDow = getFirstDayOfWeek(currentYear, currentMonth);
  const monthStr = `${currentYear}-${String(currentMonth).padStart(2, '0')}`;

  const slotCountByDate = slots.reduce<Record<string, number>>((acc, s) => {
    acc[s.slot_date] = (acc[s.slot_date] || 0) + 1;
    return acc;
  }, {});
  const bookedCountByDate = slots.reduce<Record<string, number>>((acc, s) => {
    acc[s.slot_date] = (acc[s.slot_date] || 0) + s.booked_count;
    return acc;
  }, {});

  // ─── 슬롯 그룹핑 (일별 뷰 / 달력 선택 날짜) ───
  const visibleSlots = viewMode === 'daily'
    ? slots
    : (selectedDate ? slots.filter(s => s.slot_date === selectedDate) : slots);

  const grouped = visibleSlots.reduce<Record<string, BookingSlot[]>>((acc, slot) => {
    (acc[slot.slot_date] = acc[slot.slot_date] || []).push(slot);
    return acc;
  }, {});
  const sortedDates = Object.keys(grouped).sort();

  // 도메인 ID → 이름 매핑
  const domainMap = domains.reduce<Record<string, string>>((acc, d) => {
    acc[d.domain_id] = d.domain_name;
    return acc;
  }, {});

  // 오늘 날짜 문자열 (달력 하이라이트)
  const todayStr = toDateStr(today);

  return (
    <div className="p-6 max-w-5xl mx-auto">

      {/* ── 헤더 ── */}
      <div className="flex justify-between items-start mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">슬롯 관리</h1>
          <p className="text-sm text-gray-500 mt-1">예약 가능 시간대 설정</p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/booking/domains"
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            도메인 관리
          </Link>
          <Link
            href="/booking"
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
          >
            예약 목록
          </Link>
          <button
            onClick={() => { setShowBulkForm(b => !b); setShowSlotForm(false); setBulkResult(null); }}
            className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition-colors"
          >
            ⚡ 일괄 자동 생성
          </button>
          <button
            onClick={() => {
              setSlotForm({ ...EMPTY_SLOT_FORM, slot_date: viewMode === 'daily' ? currentDate : (selectedDate || toDateStr(today)) });
              setShowSlotForm(b => !b);
              setShowBulkForm(false);
            }}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            + 슬롯 추가
          </button>
        </div>
      </div>

      {/* ── 일괄 자동 생성 폼 ── */}
      {showBulkForm && (
        <div className="bg-white rounded-xl border border-emerald-200 p-5 mb-4 shadow-sm">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-base font-semibold text-gray-900">⚡ 슬롯 일괄 자동 생성</h2>
            <p className="text-xs text-gray-500">기간·요일·업무시간을 설정하면 슬롯을 자동으로 만들어드립니다.</p>
          </div>
          <form onSubmit={handleBulkCreate} className="space-y-4">
            {/* 기간 */}
            <div className="flex flex-wrap gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">시작 날짜 *</label>
                <input type="date" required value={bulkForm.date_from}
                  onChange={e => setBulkForm(f => ({ ...f, date_from: e.target.value }))}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">종료 날짜 *</label>
                <input type="date" required value={bulkForm.date_to}
                  onChange={e => setBulkForm(f => ({ ...f, date_to: e.target.value }))}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
            </div>

            {/* 요일 선택 */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-2">운영 요일</label>
              <div className="flex gap-1">
                {WEEKDAY_LABELS.map((label, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => toggleWeekday(idx)}
                    className={`w-9 h-9 rounded-full text-sm font-medium transition-colors ${
                      bulkForm.weekdays.includes(idx)
                        ? idx >= 5
                          ? 'bg-red-500 text-white'
                          : 'bg-emerald-600 text-white'
                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* 업무 시간 */}
            <div className="flex flex-wrap gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">업무 시작 *</label>
                <input type="time" required value={bulkForm.work_start}
                  onChange={e => setBulkForm(f => ({ ...f, work_start: e.target.value }))}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">업무 종료 *</label>
                <input type="time" required value={bulkForm.work_end}
                  onChange={e => setBulkForm(f => ({ ...f, work_end: e.target.value }))}
                  className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">슬롯 길이(분) *</label>
                <input type="number" required min={5} max={480} value={bulkForm.slot_duration_min}
                  onChange={e => setBulkForm(f => ({ ...f, slot_duration_min: parseInt(e.target.value) || 60 }))}
                  className="w-24 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">시작 간격(분)</label>
                <input type="number" min={0} max={480} value={bulkForm.slot_interval_min}
                  onChange={e => setBulkForm(f => ({ ...f, slot_interval_min: parseInt(e.target.value) || 0 }))}
                  placeholder="0=길이와 동일"
                  className="w-28 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">최대 인원</label>
                <input type="number" min={1} max={500} value={bulkForm.capacity}
                  onChange={e => setBulkForm(f => ({ ...f, capacity: parseInt(e.target.value) || 1 }))}
                  className="w-20 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500" />
              </div>
            </div>

            {/* 제외 시간대 */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <label className="text-xs font-medium text-gray-700">제외 시간대</label>
                <button
                  type="button"
                  onClick={addExcludeWindow}
                  className="text-xs text-emerald-600 hover:text-emerald-700 font-medium"
                >
                  + 추가
                </button>
              </div>
              {bulkForm.exclude_windows.length === 0 && (
                <p className="text-xs text-gray-400">점심시간, 휴식시간 등 제외할 시간대가 없습니다.</p>
              )}
              <div className="space-y-2">
                {bulkForm.exclude_windows.map((w, idx) => (
                  <div key={idx} className="flex gap-2 items-center">
                    <input type="time" required value={w.start}
                      onChange={e => updateExcludeWindow(idx, 'start', e.target.value)}
                      className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-emerald-500" />
                    <span className="text-gray-400 text-sm">~</span>
                    <input type="time" required value={w.end}
                      onChange={e => updateExcludeWindow(idx, 'end', e.target.value)}
                      className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-emerald-500" />
                    <input type="text" value={w.label}
                      onChange={e => updateExcludeWindow(idx, 'label', e.target.value)}
                      placeholder="사유 (예: 점심시간)"
                      className="w-36 px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-emerald-500" />
                    <button type="button" onClick={() => removeExcludeWindow(idx)}
                      className="text-red-400 hover:text-red-600 text-lg leading-none">×</button>
                  </div>
                ))}
              </div>
            </div>

            {/* 도메인 선택 + 옵션 */}
            <div className="flex flex-wrap gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">예약 도메인</label>
                <div className="flex items-center gap-1.5">
                  <select
                    value={bulkForm.domain_id}
                    onChange={e => setBulkForm(f => ({ ...f, domain_id: e.target.value }))}
                    className="w-48 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  >
                    <option value="">도메인 미지정</option>
                    {domains.map(d => (
                      <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>
                    ))}
                  </select>
                  <Link
                    href="/booking/domains"
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg hover:bg-emerald-100 whitespace-nowrap"
                  >
                    도메인 관리
                  </Link>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="checkbox" checked={bulkForm.skip_existing}
                  onChange={e => setBulkForm(f => ({ ...f, skip_existing: e.target.checked }))}
                  className="rounded" />
                중복 슬롯 건너뜀
              </label>
            </div>

            {/* 버튼 */}
            <div className="flex gap-2 pt-2 border-t border-gray-100">
              <button
                type="submit"
                disabled={bulkSubmitting}
                className="px-5 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              >
                {bulkSubmitting ? '생성 중...' : '⚡ 슬롯 일괄 생성'}
              </button>
              <button
                type="button"
                onClick={() => { setShowBulkForm(false); setBulkResult(null); }}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
              >
                닫기
              </button>
            </div>
          </form>

          {/* 결과 */}
          {bulkResult && (
            <div className="mt-4 p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
              <p className="text-sm font-semibold text-emerald-800 mb-1">
                ✅ 생성 완료 — {bulkResult.created}개 생성 / {bulkResult.skipped}개 건너뜀
              </p>
              {bulkResult.preview.length > 0 && (
                <details className="text-xs text-emerald-700 mt-1">
                  <summary className="cursor-pointer">생성된 슬롯 미리보기 ({bulkResult.preview.length}개)</summary>
                  <div className="mt-2 grid grid-cols-4 gap-1 max-h-32 overflow-y-auto">
                    {bulkResult.preview.map((p, i) => (
                      <span key={i} className="bg-white rounded px-2 py-0.5 border border-emerald-100">{p}</span>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── 단일 슬롯 추가 폼 ── */}
      {showSlotForm && (
        <div className="bg-white rounded-xl border border-indigo-200 p-5 mb-4 shadow-sm">
          <h2 className="text-base font-semibold text-gray-900 mb-4">새 슬롯 추가</h2>
          <form onSubmit={handleCreateSlot} className="flex flex-wrap gap-4 items-end">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">날짜 *</label>
              <input type="date" required value={slotForm.slot_date}
                onChange={e => setSlotForm({ ...slotForm, slot_date: e.target.value })}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">시간 *</label>
              <input type="time" required value={slotForm.slot_time}
                onChange={e => setSlotForm({ ...slotForm, slot_time: e.target.value })}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">최대 인원</label>
              <input type="number" min={1} max={500} value={slotForm.capacity}
                onChange={e => setSlotForm({ ...slotForm, capacity: parseInt(e.target.value) || 1 })}
                className="w-20 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">예약 도메인</label>
              <div className="flex items-center gap-1.5">
                <select
                  value={slotForm.domain_id}
                  onChange={e => setSlotForm({ ...slotForm, domain_id: e.target.value })}
                  className="w-48 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">도메인 미지정</option>
                  {domains.map(d => (
                    <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>
                  ))}
                </select>
                  <Link
                    href="/booking/domains"
                    className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-lg hover:bg-indigo-100 whitespace-nowrap"
                  >
                    도메인 관리
                  </Link>
              </div>
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={submitting}
                className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                {submitting ? '저장 중...' : '저장'}
              </button>
              <button type="button"
                onClick={() => { setShowSlotForm(false); setSlotForm(EMPTY_SLOT_FORM); }}
                className="px-4 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">
                취소
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── 뷰 모드 & 날짜 네비게이션 ── */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          {/* 뷰 토글 */}
          <div className="flex rounded-lg overflow-hidden border border-gray-200">
            <button
              onClick={() => handleModeChange('daily')}
              className={`px-4 py-1.5 text-sm font-medium transition-colors ${
                viewMode === 'daily' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              일별
            </button>
            <button
              onClick={() => handleModeChange('monthly')}
              className={`px-4 py-1.5 text-sm font-medium transition-colors ${
                viewMode === 'monthly' ? 'bg-indigo-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              월별
            </button>
          </div>

          {/* 날짜 네비게이션 */}
          <div className="flex items-center gap-2">
            <button onClick={goToPrev}
              className="w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 text-lg">
              ‹
            </button>
            <span className="text-sm font-semibold text-gray-800 min-w-[160px] text-center">
              {viewMode === 'daily'
                ? formatDisplayDate(currentDate)
                : (selectedDate
                    ? `${formatDisplayMonth(currentYear, currentMonth)} › ${selectedDate.slice(8)}일`
                    : formatDisplayMonth(currentYear, currentMonth)
                  )
              }
            </span>
            <button onClick={goToNext}
              className="w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 text-lg">
              ›
            </button>
            <button onClick={goToToday}
              className="ml-1 px-3 py-1 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-lg hover:bg-indigo-50">
              오늘
            </button>
            {viewMode === 'monthly' && selectedDate && (
              <button onClick={() => setSelectedDate(null)}
                className="px-2 py-1 text-xs text-gray-500 hover:text-gray-700">
                전체 보기
              </button>
            )}
          </div>

          <span className="text-sm text-gray-500">총 {total}개 슬롯</span>
        </div>
      </div>

      {/* ── 월별 달력 ── */}
      {viewMode === 'monthly' && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
          <div className="grid grid-cols-7 mb-1">
            {['월', '화', '수', '목', '금', '토', '일'].map((d, i) => (
              <div key={d} className={`text-center text-xs font-medium py-1 ${i >= 5 ? 'text-red-400' : 'text-gray-500'}`}>
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-px bg-gray-100 rounded-lg overflow-hidden">
            {Array.from({ length: firstDow }, (_, i) => (
              <div key={`empty-${i}`} className="bg-white min-h-[56px]" />
            ))}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const dayNum = i + 1;
              const dateStr = `${monthStr}-${String(dayNum).padStart(2, '0')}`;
              const count = slotCountByDate[dateStr] || 0;
              const booked = bookedCountByDate[dateStr] || 0;
              const isToday = dateStr === todayStr;
              const isSelected = dateStr === selectedDate;
              const dowIdx = (firstDow + i) % 7;
              const isWeekend = dowIdx >= 5;
              return (
                <button
                  key={dayNum}
                  onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                  className={`bg-white min-h-[56px] p-1.5 text-left transition-colors hover:bg-indigo-50 ${
                    isSelected ? 'ring-2 ring-inset ring-indigo-500 bg-indigo-50' : ''
                  }`}
                >
                  <span className={`text-xs font-medium inline-flex w-6 h-6 items-center justify-center rounded-full ${
                    isToday ? 'bg-indigo-600 text-white' : isWeekend ? 'text-red-500' : 'text-gray-700'
                  }`}>
                    {dayNum}
                  </span>
                  {count > 0 && (
                    <div className="mt-0.5">
                      <div className="text-[10px] text-indigo-600 font-medium">{count}슬롯</div>
                      {booked > 0 && (
                        <div className="text-[10px] text-orange-500">{booked}예약</div>
                      )}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 슬롯 목록 ── */}
      {loading ? (
        <div className="flex justify-center items-center h-40 text-gray-500">불러오는 중...</div>
      ) : error ? (
        <div className="text-red-500 p-4">{error}</div>
      ) : sortedDates.length === 0 ? (
        <div className="flex flex-col justify-center items-center h-40 gap-3 text-gray-400">
          <span>
            {viewMode === 'daily'
              ? `${formatDisplayDate(currentDate)} 슬롯 없음`
              : selectedDate
                ? `${selectedDate} 슬롯 없음`
                : '이 달에 슬롯이 없습니다.'}
          </span>
          <button
            onClick={() => { setShowBulkForm(true); setShowSlotForm(false); }}
            className="text-sm text-emerald-600 hover:underline"
          >
            ⚡ 일괄 자동 생성하기
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {sortedDates.map((date) => (
            <div key={date} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
                <h3 className="text-sm font-semibold text-gray-700">{formatDisplayDate(date)}</h3>
                <span className="text-xs text-gray-400">{grouped[date].length}개 슬롯</span>
              </div>
              <div className="divide-y divide-gray-100">
                {grouped[date].map((slot) => (
                  <div
                    key={slot.slot_id}
                    className={`flex items-center justify-between px-4 py-3 ${slot.is_blocked ? 'bg-gray-50 opacity-60' : ''}`}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-base font-mono font-medium text-gray-900 w-16">
                        {slot.slot_time}
                      </span>
                      {slot.domain_id && domainMap[slot.domain_id] && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-indigo-100 text-indigo-700 rounded-full">
                          {domainMap[slot.domain_id]}
                        </span>
                      )}
                      {slot.label && !slot.domain_id && (
                        <span className="text-sm text-gray-500">{slot.label}</span>
                      )}
                      {slot.is_blocked && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-gray-200 text-gray-600 rounded-full">차단됨</span>
                      )}
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="flex items-center gap-2">
                        <div className="w-24 bg-gray-200 rounded-full h-2">
                          <div
                            className="bg-indigo-500 h-2 rounded-full transition-all"
                            style={{ width: `${Math.min(100, (slot.booked_count / slot.capacity) * 100)}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500">{slot.booked_count}/{slot.capacity}</span>
                      </div>
                      <div className="flex gap-1">
                        <button
                          onClick={() => handleToggleBlock(slot)}
                          className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                            slot.is_blocked
                              ? 'text-green-700 bg-green-50 hover:bg-green-100'
                              : 'text-yellow-700 bg-yellow-50 hover:bg-yellow-100'
                          }`}
                        >
                          {slot.is_blocked ? '차단 해제' : '차단'}
                        </button>
                        <button
                          onClick={() => handleDelete(slot.slot_id)}
                          disabled={deletingId === slot.slot_id}
                          className="px-2 py-1 text-xs font-medium text-red-700 bg-red-50 rounded hover:bg-red-100 disabled:opacity-50"
                        >
                          삭제
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
