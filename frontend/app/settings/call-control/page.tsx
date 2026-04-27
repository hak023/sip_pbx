'use client';

/**
 * Call Control 설정 페이지
 *
 * 착신 라우팅 규칙(무응답AI/즉시AI/착신전환)과
 * 시간 스케줄, 착신 전환 대상(단일/그룹), 통화 연결음(스케줄별), 발신자 필터를 탭 UI로 관리한다.
 * - '직접 연결'은 규칙 없는 기본 동작이므로 제거
 * - 규칙 순서는 목록에서 드래그로 변경, 우선순위는 자동 지정
 * - 착신 규칙의 전환 대상은 `fwd:<id>`(착신 전환 탭) 또는 내선/SIP 직접 입력
 * - 발신자 필터: 번호+연결옵션(차단/직접응대/AI응대) 모달 형식
 */

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { apiJson, authHeaders, getApiUrl } from '@/lib/api';
import {
  DAY_LABELS,
  autoRoutingRuleName,
  autoScheduleName,
  formatCallControlStatusLine,
  formatScheduleDetailLines,
  formatScheduleOneLine,
  routingActionSummary,
} from '@/lib/call-control-display';
import { getTenantOwner } from '@/lib/tenant';
import { wsClient } from '@/lib/websocket';
import { useWebSocket } from '@/hooks/useWebSocket';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RoutingAction =
  | 'no_answer_ai'
  | 'immediate_ai'
  | 'busy_ai'
  | 'forward_always'
  | 'forward_when_busy'
  | 'forward'; // API 하위 호환
type FilterAction = 'block' | 'direct' | 'ai';

interface RoutingRule {
  id: string;
  owner: string;
  name: string;
  priority: number;
  action: RoutingAction;
  no_answer_timeout: number;
  forward_to: string | null;
  announcement_id: string | null;
  schedule_id: string | null;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

interface TimeRange {
  start: string;
  end: string;
}

interface Schedule {
  id: string;
  owner: string;
  name: string;
  days: string[];
  time_ranges: TimeRange[];
  include_holidays: boolean;
  holiday_country: string;
  timezone: string;
  created_at?: string;
}

interface RingbackScheduleAssignmentRow {
  id: string;
  owner: string;
  name: string;
  schedule_id: string | null;
  position?: number;
  enabled: boolean;
  generation_mode?: 'tts' | 'suno';
  tts_text: string;
  tts_audio_path?: string | null;
  suno_lyrics?: string | null;
  suno_style?: string | null;
  suno_title?: string | null;
  suno_vocal_gender?: string;
  suno_duration_target?: number;
  suno_audio_path?: string | null;
  suno_audio_url?: string | null;
  suno_task_id?: string | null;
  suno_generation_status?: string | null;
  created_at?: string;
  updated_at?: string;
  schedule_name?: string | null;
}

interface CallerFilter {
  id: string;
  owner: string;
  name: string;
  pattern: string;
  action: FilterAction;
  priority: number;
  enabled: boolean;
}

type ForwardTargetKind = 'single' | 'group';
type ForwardRingMode = 'simultaneous' | 'sequential' | 'circular';

interface ForwardTargetRow {
  id: string;
  owner: string;
  name: string;
  kind: ForwardTargetKind;
  single_extension: string | null;
  members: string[];
  ring_mode: ForwardRingMode;
  created_at?: string;
  updated_at?: string;
}

interface OverflowPolicy {
  owner: string;
  enabled: boolean;
  max_concurrent_calls: number;
  overflow_action: RoutingAction | 'direct' | 'immediate_ai' | 'no_answer_ai';
  announcement_id: string | null;
}

interface CurrentStatus {
  owner: string;
  rule: RoutingRule | null;
  schedule: Schedule | null;
  is_schedule_active: boolean;
  current_time: string;
  description: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACTION_LABELS: Record<string, string> = {
  no_answer_ai: '무응답 시 AI 응대',
  immediate_ai: '즉시 AI 응대',
  busy_ai: '통화중 시 AI 응대',
  forward_always: '무조건 착신전환',
  forward_when_busy: '통화 중 착신전환',
  forward: '착신전환 (구버전)',
};

const ACTION_COLORS: Record<string, string> = {
  no_answer_ai: 'bg-yellow-100 text-yellow-800',
  immediate_ai: 'bg-orange-100 text-orange-800',
  busy_ai: 'bg-amber-100 text-amber-900',
  forward_always: 'bg-purple-100 text-purple-800',
  forward_when_busy: 'bg-fuchsia-100 text-fuchsia-900',
  forward: 'bg-purple-100 text-purple-800',
};

/** 규칙 추가 모달에서 표시할 착신 동작 순서 */
const RULE_ACTION_OPTIONS: RoutingAction[] = [
  'no_answer_ai',
  'immediate_ai',
  'busy_ai',
  'forward_always',
  'forward_when_busy',
];

const FILTER_ACTION_LABELS: Record<FilterAction, string> = {
  block: '차단',
  direct: '직접 응대',
  ai: 'AI 응대',
};

const FILTER_ACTION_COLORS: Record<FilterAction, string> = {
  block: 'bg-red-100 text-red-800',
  direct: 'bg-blue-100 text-blue-800',
  ai: 'bg-orange-100 text-orange-800',
};

const FILTER_ACTION_DESC: Record<FilterAction, string> = {
  block: '수신 거부 (연결하지 않음)',
  direct: '일반 통화로 직접 연결',
  ai: '즉시 AI 비서가 응대',
};

const ALL_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

const FORWARD_RING_MODE_LABELS: Record<ForwardRingMode, string> = {
  simultaneous: '동시 링 (유휴·등록 우선으로 1명)',
  sequential: '순차 링 (목록 순)',
  circular: '순환 (현재는 순차와 동일 선택)',
};

function forwardTargetSummary(t: ForwardTargetRow): string {
  if (t.kind === 'group') {
    const m = (t.members || []).filter(Boolean).join(', ');
    return `${FORWARD_RING_MODE_LABELS[t.ring_mode] || t.ring_mode} · ${m || '(멤버 없음)'}`;
  }
  return t.single_extension ? `내선 ${t.single_extension}` : '(내선 미지정)';
}

// ---------------------------------------------------------------------------
// Sortable Rule Card
// ---------------------------------------------------------------------------

interface SortableRuleCardProps {
  rule: RoutingRule;
  index: number;
  schedules: Schedule[];
  forwardTargets: ForwardTargetRow[];
  currentRuleId?: string;
  onToggle: (rule: RoutingRule) => void;
  onEdit: (rule: RoutingRule) => void;
  onDelete: (id: string) => void;
}

function SortableRuleCard({
  rule, index, schedules, forwardTargets, currentRuleId,
  onToggle, onEdit, onDelete,
}: SortableRuleCardProps) {
  const {
    attributes, listeners, setNodeRef,
    transform, transition, isDragging,
  } = useSortable({ id: rule.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const schedule = schedules.find(s => s.id === rule.schedule_id);
  const isCurrent = currentRuleId === rule.id;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`rounded-xl border p-4 transition-all select-none ${
        isDragging
          ? 'border-indigo-400 bg-indigo-50 shadow-lg'
          : isCurrent
          ? 'border-indigo-300 bg-indigo-50'
          : rule.enabled
          ? 'border-gray-200 bg-white hover:border-gray-300'
          : 'border-gray-100 bg-gray-50 opacity-60'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          {/* 드래그 핸들 + 순서 번호 */}
          <div
            {...attributes}
            {...listeners}
            className="flex-shrink-0 flex flex-col items-center gap-0.5 cursor-grab active:cursor-grabbing mt-0.5 px-1"
            title="드래그하여 순서 변경"
          >
            <div className="w-6 h-5 flex flex-col justify-center gap-0.5">
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
            </div>
            <span className="text-xs font-bold text-gray-400">{index + 1}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center px-3 py-1.5 rounded-lg text-sm font-semibold leading-snug ${
                  ACTION_COLORS[rule.action] || 'bg-gray-100 text-gray-700'
                }`}
              >
                {routingActionSummary(rule.action, rule.no_answer_timeout, rule.forward_to, forwardTargets)}
              </span>
              {isCurrent && (
                <span className="px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700 font-medium shrink-0">적용 중</span>
              )}
            </div>
            {schedule ? (
              <div className="mt-2 text-xs text-gray-600 border-l-2 border-indigo-200 pl-2.5 space-y-0.5">
                <div className="font-medium text-gray-700">시간 조건</div>
                {formatScheduleDetailLines(schedule).map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-gray-500">시간 조건 없음 (항상 이 순서에서 평가)</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => onToggle(rule)}
            className={`relative inline-flex h-6 w-10 rounded-full transition-colors ${
              rule.enabled ? 'bg-indigo-600' : 'bg-gray-300'
            }`}
          >
            <span className={`inline-block h-5 w-5 mt-0.5 ml-0.5 rounded-full bg-white shadow transition-transform ${
              rule.enabled ? 'translate-x-4' : 'translate-x-0'
            }`} />
          </button>
          <button
            onClick={() => onEdit(rule)}
            className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            수정
          </button>
          <button
            onClick={() => onDelete(rule.id)}
            className="px-3 py-1.5 text-xs border border-red-100 text-red-600 rounded-lg hover:bg-red-50"
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sortable Ringback assignment card (통화 연결음 탭)
// ---------------------------------------------------------------------------

function ringbackModeLabel(mode: string | undefined): string {
  return mode === 'tts' ? 'TTS' : 'Suno';
}

function ringbackSummaryLine(row: RingbackScheduleAssignmentRow): string {
  const mode = row.generation_mode || 'suno';
  if (mode === 'tts') {
    return ringbackTtsSummary(row);
  }
  const st = (row.suno_generation_status || 'idle').toLowerCase();
  if (st === 'pending') return '음원 생성 중… (완료되면 자동으로 반영됩니다)';
  if (st === 'failed') return 'Suno 음원 생성 실패 — 가사·스타일·서버 설정 확인 후 다시 저장하세요';
  return (row.suno_audio_path || '').trim()
    ? 'Suno MP3 적용됨'
    : 'Suno · 가사·스타일 입력 후 «저장»하면 음원이 생성됩니다';
}

function ringbackTtsSummary(row: RingbackScheduleAssignmentRow): string {
  const p = (row.tts_audio_path || '').trim();
  if (p) return 'TTS 음원 파일 준비됨 (저장 시 갱신)';
  const t = (row.tts_text || '').trim();
  if (t) return 'TTS · 저장 후 백그라운드에서 음원 파일 생성 중이거나 대기 중';
  return '(TTS 문구 없음)';
}

type RingbackMediaPreviewFields = Pick<
  RingbackScheduleAssignmentRow,
  | 'id'
  | 'generation_mode'
  | 'suno_generation_status'
  | 'suno_audio_path'
  | 'suno_audio_url'
  | 'tts_audio_path'
>;

/** 로컬 캐시 MP3/WAV: Bearer fetch → Blob URL. 원격 MP3만 있으면 `<audio src>` 직접. */
function RingbackMediaPreview({ owner, row }: { owner: string; row: RingbackMediaPreviewFields }) {
  const [blobSrc, setBlobSrc] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const blobRef = useRef<string | null>(null);

  const mode = (row.generation_mode || 'suno').toLowerCase();
  const sunoDone = mode === 'suno' && (row.suno_generation_status || '').toLowerCase() === 'complete';
  const hasLocalSuno = sunoDone && !!(row.suno_audio_path || '').trim();
  const remoteUrl = (row.suno_audio_url || '').trim();
  const ttsReady = mode === 'tts' && !!(row.tts_audio_path || '').trim();

  useEffect(() => {
    return () => {
      if (blobRef.current) {
        URL.revokeObjectURL(blobRef.current);
        blobRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current);
      blobRef.current = null;
    }
    setBlobSrc(null);
    setErr(null);
  }, [row.id, row.suno_audio_path, row.tts_audio_path, row.suno_generation_status]);

  const loadLocal = async () => {
    setErr(null);
    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current);
      blobRef.current = null;
    }
    setBlobSrc(null);
    setLoading(true);
    try {
      const path = `/api/call-control/ringback-assignments/${encodeURIComponent(row.id)}/media?owner=${encodeURIComponent(owner)}`;
      const url = `${getApiUrl()}${path}`;
      const res = await fetch(url, { headers: authHeaders(false) as HeadersInit, cache: 'no-store' });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = (await res.json()) as { detail?: string };
          if (typeof j?.detail === 'string') msg = j.detail;
        } catch {
          /* ignore */
        }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const u = URL.createObjectURL(blob);
      blobRef.current = u;
      setBlobSrc(u);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '미리듣기 실패');
    } finally {
      setLoading(false);
    }
  };

  if (hasLocalSuno || ttsReady) {
    return (
      <div className="mt-3 border-t border-gray-100 pt-2">
        <div className="flex flex-wrap items-center gap-2">
          {!blobSrc && (
            <button
              type="button"
              onClick={() => void loadLocal()}
              disabled={loading}
              className="px-2.5 py-1 text-xs rounded-lg border border-indigo-200 bg-indigo-50 text-indigo-800 hover:bg-indigo-100 disabled:opacity-50"
            >
              {loading ? '불러오는 중…' : '미리듣기'}
            </button>
          )}
          {blobSrc ? (
            <audio controls src={blobSrc} className="h-9 flex-1 min-w-[180px] max-w-md" preload="metadata" />
          ) : null}
          {err ? <span className="text-xs text-red-600">{err}</span> : null}
        </div>
      </div>
    );
  }

  if (sunoDone && remoteUrl) {
    return (
      <div className="mt-3 border-t border-gray-100 pt-2">
        <p className="text-xs text-gray-500 mb-1">원격 음원 URL (로컬 캐시 없음)</p>
        <audio controls src={remoteUrl} className="h-9 w-full max-w-md" preload="metadata" />
      </div>
    );
  }

  return null;
}

interface SortableRingbackAssignmentCardProps {
  row: RingbackScheduleAssignmentRow;
  index: number;
  owner: string;
  schedules: Schedule[];
  onToggle: (row: RingbackScheduleAssignmentRow) => void;
  onEdit: (row: RingbackScheduleAssignmentRow) => void;
  onDelete: (id: string) => void;
}

function SortableRingbackAssignmentCard({
  row, index, owner, schedules, onToggle, onEdit, onDelete,
}: SortableRingbackAssignmentCardProps) {
  const isPending = (row.suno_generation_status || '').toLowerCase() === 'pending';
  const {
    attributes, listeners, setNodeRef,
    transform, transition, isDragging,
  } = useSortable({ id: row.id, disabled: isPending });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const schedule = schedules.find(s => s.id === row.schedule_id);

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`rounded-xl border p-4 transition-all select-none ${
        isDragging
          ? 'border-indigo-400 bg-indigo-50 shadow-lg'
          : row.enabled
          ? 'border-gray-200 bg-white hover:border-gray-300'
          : 'border-gray-100 bg-gray-50 opacity-60'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div
            {...attributes}
            {...listeners}
            className="flex-shrink-0 flex flex-col items-center gap-0.5 cursor-grab active:cursor-grabbing mt-0.5 px-1"
            title="드래그하여 순서 변경"
          >
            <div className="w-6 h-5 flex flex-col justify-center gap-0.5">
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
              <span className="block h-0.5 w-4 bg-gray-400 rounded" />
            </div>
            <span className="text-xs font-bold text-gray-400">{index + 1}</span>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-gray-900">{row.name || '통화 연결음'}</span>
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700">
                {ringbackModeLabel(row.generation_mode)}
              </span>
              {isPending && (
                <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-900">
                  음원 생성중
                </span>
              )}
            </div>
            <div className="text-xs text-gray-500 mt-1">
              스케줄:{' '}
              <span className="font-medium text-gray-700">
                {schedule ? formatScheduleOneLine(schedule) : '항상'}
              </span>
            </div>
            <p className="text-sm text-gray-600 mt-1 break-words">{ringbackSummaryLine(row)}</p>
            <RingbackMediaPreview owner={owner} row={row} />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            onClick={() => onToggle(row)}
            disabled={isPending}
            className={`relative inline-flex h-6 w-10 rounded-full transition-colors ${
              row.enabled ? 'bg-indigo-600' : 'bg-gray-300'
            } ${isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <span className={`inline-block h-5 w-5 mt-0.5 ml-0.5 rounded-full bg-white shadow transition-transform ${
              row.enabled ? 'translate-x-4' : 'translate-x-0'
            }`} />
          </button>
          <button
            type="button"
            onClick={() => onEdit(row)}
            disabled={isPending}
            className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            수정
          </button>
          <button
            type="button"
            onClick={() => onDelete(row.id)}
            disabled={isPending}
            className="px-3 py-1.5 text-xs border border-red-100 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule Form Modal
// ---------------------------------------------------------------------------

interface RuleFormModalProps {
  rule: Partial<RoutingRule> | null;
  schedules: Schedule[];
  forwardTargets: ForwardTargetRow[];
  owner: string;
  onSave: (data: Partial<RoutingRule>) => Promise<void>;
  onClose: () => void;
}

function RuleFormModal({ rule, schedules, forwardTargets, owner, onSave, onClose }: RuleFormModalProps) {
  const isNew = !rule?.id;
  const normalizedAction: RoutingAction =
    rule?.action === 'forward' ? 'forward_always' : (rule?.action as RoutingAction) || 'no_answer_ai';
  const initialFwdId =
    rule?.forward_to?.toLowerCase().startsWith('fwd:') ? rule.forward_to.slice(4).trim() : '';
  const [form, setForm] = useState<Partial<RoutingRule>>({
    owner,
    name: '',
    no_answer_timeout: 20,
    forward_to: '',
    announcement_id: null,
    schedule_id: null,
    enabled: true,
    ...rule,
    action: normalizedAction,
  });
  const [forwardPick, setForwardPick] = useState<'registry' | 'manual'>(initialFwdId ? 'registry' : 'manual');
  const [selectedForwardTargetId, setSelectedForwardTargetId] = useState(initialFwdId);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof RoutingRule, value: unknown) =>
    setForm(prev => ({ ...prev, [key]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const needsForward =
      form.action === 'forward' || form.action === 'forward_always' || form.action === 'forward_when_busy';
    if (needsForward && forwardPick === 'registry') {
      if (!selectedForwardTargetId) {
        setError('«착신 전환» 탭에 등록한 대상을 선택하거나, 직접 입력으로 전환하세요.');
        return;
      }
    } else if (needsForward && forwardPick === 'manual' && !form.forward_to?.trim()) {
      setError('착신전환 대상 번호를 입력하세요.'); return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload: Partial<RoutingRule> = { ...form, announcement_id: null };
      if (needsForward && forwardPick === 'registry') {
        payload.forward_to = `fwd:${selectedForwardTargetId}`;
      }
      if (!(payload.name || '').trim()) {
        payload.name = autoRoutingRuleName(
          String(payload.action || 'no_answer_ai'),
          payload.no_answer_timeout,
          payload.forward_to,
          forwardTargets,
        );
      }
      await onSave(payload);
    }
    catch (err) { setError(err instanceof Error ? err.message : '저장 실패'); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg">
        <div className="flex justify-between items-center p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900">
            {isNew ? '규칙 추가' : '규칙 수정'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* 착신 동작 선택 (직접 연결 제외) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">착신 동작 *</label>
            <div className="grid grid-cols-1 gap-2 max-h-[52vh] overflow-y-auto pr-1">
              {RULE_ACTION_OPTIONS.map(action => (
                <button
                  key={action}
                  type="button"
                  onClick={() => set('action', action)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg border-2 text-left transition-all ${
                    form.action === action
                      ? 'border-indigo-500 bg-indigo-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                    form.action === action ? 'bg-indigo-500' : 'bg-gray-300'
                  }`} />
                  <div>
                    <span className="text-sm font-medium text-gray-900">{ACTION_LABELS[action]}</span>
                    <span className="text-xs text-gray-500 ml-2 block mt-0.5">
                      {action === 'no_answer_ai' && '착신자 무응답 시 AI 전환'}
                      {action === 'immediate_ai' && '항상 AI가 먼저 응대'}
                      {action === 'busy_ai' && '착신자가 다른 통화 중일 때만 AI가 응대'}
                      {action === 'forward_always' && '항상 착신 번호를 전환 대상 내선으로 변경'}
                      {action === 'forward_when_busy' && '착신자 통화 중일 때만 전환 대상 내선으로 변경'}
                    </span>
                  </div>
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              규칙이 없으면 기본 직접 연결(A→B)이 적용됩니다.
            </p>
          </div>

          {/* 무응답 AI: 타임아웃 선택 */}
          {form.action === 'no_answer_ai' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">무응답 대기 시간</label>
              <div className="flex gap-2">
                {[10, 20, 30].map(sec => (
                  <button
                    key={sec}
                    type="button"
                    onClick={() => set('no_answer_timeout', sec)}
                    className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium transition-all ${
                      form.no_answer_timeout === sec
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-gray-200 text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    {sec}초
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 착신전환: 등록 대상 또는 직접 입력 */}
          {(form.action === 'forward' || form.action === 'forward_always' || form.action === 'forward_when_busy') && (
            <div className="space-y-3">
              <label className="block text-sm font-medium text-gray-700">전환 대상 *</label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setForwardPick('registry')}
                  className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium ${
                    forwardPick === 'registry'
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-800'
                      : 'border-gray-200 text-gray-600'
                  }`}
                >
                  착신 전환 탭 대상
                </button>
                <button
                  type="button"
                  onClick={() => setForwardPick('manual')}
                  className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium ${
                    forwardPick === 'manual'
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-800'
                      : 'border-gray-200 text-gray-600'
                  }`}
                >
                  직접 입력
                </button>
              </div>
              {forwardPick === 'registry' ? (
                <div>
                  <select
                    value={selectedForwardTargetId}
                    onChange={e => setSelectedForwardTargetId(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">선택…</option>
                    {forwardTargets.map(t => (
                      <option key={t.id} value={t.id}>
                        {t.name} ({t.kind === 'group' ? '그룹' : '단일'})
                      </option>
                    ))}
                  </select>
                  {forwardTargets.length === 0 && (
                    <p className="text-xs text-amber-700 mt-1">
                      등록된 대상이 없습니다. «착신 전환» 탭에서 단일 내선 또는 그룹을 먼저 추가하세요.
                    </p>
                  )}
                  <p className="text-xs text-gray-400 mt-1">
                    규칙에는 내부 참조 <code className="bg-gray-100 px-1 rounded">fwd:…</code> 가 저장됩니다.
                  </p>
                </div>
              ) : (
                <div>
                  <input
                    type="text"
                    value={form.forward_to || ''}
                    onChange={e => set('forward_to', e.target.value)}
                    placeholder="예: 200, sip:200@10.0.0.1 (등록된 내선)"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <p className="text-xs text-gray-400 mt-1">PBX에 등록된 내선만 전환 가능합니다.</p>
                </div>
              )}
            </div>
          )}

          {/* 시간 조건 (스케줄) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">시간 조건</label>
            <select
              value={form.schedule_id || ''}
              onChange={e => set('schedule_id', e.target.value || null)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">항상 적용 (조건 없음)</option>
              {schedules.map(s => (
                <option key={s.id} value={s.id}>{formatScheduleOneLine(s)}</option>
              ))}
            </select>
            {schedules.length === 0 && (
              <p className="text-xs text-gray-400 mt-1">스케줄 탭에서 시간 조건을 먼저 만드세요.</p>
            )}
          </div>

          {/* 활성화 */}
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="rule-enabled"
              checked={form.enabled !== false}
              onChange={e => set('enabled', e.target.checked)}
              className="w-4 h-4 text-indigo-600 rounded"
            />
            <label htmlFor="rule-enabled" className="text-sm font-medium text-gray-700">규칙 활성화</label>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 착신 전환 대상 모달
// ---------------------------------------------------------------------------

interface ForwardTargetFormModalProps {
  row: Partial<ForwardTargetRow> | null;
  owner: string;
  onSave: (data: Partial<ForwardTargetRow>) => Promise<void>;
  onClose: () => void;
}

function ForwardTargetFormModal({ row, owner, onSave, onClose }: ForwardTargetFormModalProps) {
  const isNew = !row?.id;
  const [name, setName] = useState(row?.name || '');
  const [kind, setKind] = useState<ForwardTargetKind>((row?.kind as ForwardTargetKind) || 'single');
  const [singleExt, setSingleExt] = useState(row?.single_extension || '');
  const [members, setMembers] = useState<string[]>(
    (row?.members && row.members.length > 0) ? [...row.members] : [''],
  );
  const [ringMode, setRingMode] = useState<ForwardRingMode>((row?.ring_mode as ForwardRingMode) || 'simultaneous');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDesignNote, setShowDesignNote] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) { setError('이름을 입력하세요.'); return; }
    if (kind === 'single' && !singleExt.trim()) { setError('내선 번호를 입력하세요.'); return; }
    const mem = kind === 'group' ? members.map(m => m.trim()).filter(Boolean) : [];
    if (kind === 'group' && mem.length < 1) { setError('그룹은 최소 1개의 내선이 필요합니다.'); return; }
    setSaving(true);
    setError(null);
    try {
      await onSave({
        id: row?.id,
        owner,
        name: name.trim(),
        kind,
        single_extension: kind === 'single' ? singleExt.trim() : null,
        members: mem,
        ring_mode: ringMode,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장 실패');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-5 border-b sticky top-0 bg-white">
          <h2 className="text-lg font-semibold text-gray-900">
            {isNew ? '착신 전환 대상 추가' : '착신 전환 대상 수정'}
          </h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <button
            type="button"
            onClick={() => setShowDesignNote(v => !v)}
            className="text-xs text-indigo-600 hover:text-indigo-800"
          >
            {showDesignNote ? '▼' : '▶'} 그룹 동작 설계 참고 (대표번호·헌트그룹)
          </button>
          {showDesignNote && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 space-y-2">
              <p>
                일반 통화 서비스에서는 <strong>동시 링</strong>(한 번에 여러 착신),
                <strong> 순차 링</strong>(끊기면 다음), <strong>순환</strong>(공정 분배) 등으로
                그룹 내 착신을 분배합니다.
              </p>
              <p>
                현재 PBX B2BUA는 한 통화에 <strong>한 내선만</strong> INVITE 하므로,
                동시/순차/순환 모두 «목록 순으로 등록된 내선 중, 통화 중이 아닌 사람 우선 → 없으면 등록된 첫 사람»으로
                한 명을 고릅니다. (순환은 이후 마지막 응답 기준으로 확장 가능.)
              </p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">표시 이름 *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="예: 영업 백업, 야간 당번"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700 mb-2">유형</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setKind('single')}
                className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium ${
                  kind === 'single' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200'
                }`}
              >
                단일 내선
              </button>
              <button
                type="button"
                onClick={() => setKind('group')}
                className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium ${
                  kind === 'group' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200'
                }`}
              >
                그룹
              </button>
            </div>
          </div>

          {kind === 'single' ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">착신 내선 번호 *</label>
              <input
                type="text"
                value={singleExt}
                onChange={e => setSingleExt(e.target.value)}
                placeholder="예: 200"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">그룹 링 방식</label>
                <select
                  value={ringMode}
                  onChange={e => setRingMode(e.target.value as ForwardRingMode)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {(Object.keys(FORWARD_RING_MODE_LABELS) as ForwardRingMode[]).map(k => (
                    <option key={k} value={k}>{FORWARD_RING_MODE_LABELS[k]}</option>
                  ))}
                </select>
              </div>
              <div>
                <span className="block text-sm font-medium text-gray-700 mb-1">멤버 내선 (순서 유지) *</span>
                {members.map((m, i) => (
                  <div key={i} className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={m}
                      onChange={e => {
                        const next = [...members];
                        next[i] = e.target.value;
                        setMembers(next);
                      }}
                      placeholder={`내선 ${i + 1}`}
                      className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm"
                    />
                    {members.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setMembers(members.filter((_, j) => j !== i))}
                        className="px-2 text-red-500 text-sm"
                      >
                        삭제
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => setMembers([...members, ''])}
                  className="text-sm text-indigo-600 hover:text-indigo-800"
                >
                  + 멤버 추가
                </button>
              </div>
            </>
          )}

          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schedule Form Modal
// ---------------------------------------------------------------------------

interface ScheduleFormModalProps {
  schedule: Partial<Schedule> | null;
  owner: string;
  onSave: (data: Partial<Schedule>) => Promise<void>;
  onClose: () => void;
}

function ScheduleFormModal({ schedule, owner, onSave, onClose }: ScheduleFormModalProps) {
  const isNew = !schedule?.id;
  const [form, setForm] = useState<Partial<Schedule>>({
    owner,
    name: '',
    days: [],
    time_ranges: [{ start: '09:00', end: '18:00' }],
    include_holidays: false,
    holiday_country: 'KR',
    timezone: 'Asia/Seoul',
    ...schedule,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleDay = (day: string) => {
    const days = form.days || [];
    setForm(prev => ({
      ...prev,
      days: days.includes(day) ? days.filter(d => d !== day) : [...days, day],
    }));
  };

  const updateTimeRange = (idx: number, field: 'start' | 'end', val: string) => {
    const trs = [...(form.time_ranges || [])];
    trs[idx] = { ...trs[idx], [field]: val };
    setForm(prev => ({ ...prev, time_ranges: trs }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave({
        ...form,
        name: autoScheduleName({
          days: form.days || [],
          time_ranges: form.time_ranges || [],
          include_holidays: form.include_holidays,
          holiday_country: form.holiday_country,
          timezone: form.timezone,
        }),
      });
    }
    catch (err) { setError(err instanceof Error ? err.message : '저장 실패'); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex justify-between items-center p-5 border-b sticky top-0 bg-white">
          <h2 className="text-lg font-semibold">{isNew ? '스케줄 추가' : '스케줄 수정'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">적용 요일</label>
            <div className="flex gap-1.5 flex-wrap">
              {ALL_DAYS.map(d => (
                <button
                  key={d}
                  type="button"
                  onClick={() => toggleDay(d)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium transition-all ${
                    (form.days || []).includes(d)
                      ? 'bg-indigo-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {DAY_LABELS[d]}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1">미선택 시 매일 적용</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">적용 시간 범위</label>
            {(form.time_ranges || []).map((tr, i) => (
              <div key={i} className="flex items-center gap-2 mb-2">
                <input
                  type="time"
                  value={tr.start}
                  onChange={e => updateTimeRange(i, 'start', e.target.value)}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
                />
                <span className="text-gray-400">~</span>
                <input
                  type="time"
                  value={tr.end}
                  onChange={e => updateTimeRange(i, 'end', e.target.value)}
                  className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm"
                />
                {(form.time_ranges || []).length > 1 && (
                  <button
                    type="button"
                    onClick={() => setForm(prev => ({
                      ...prev,
                      time_ranges: (prev.time_ranges || []).filter((_, idx) => idx !== i),
                    }))}
                    className="text-red-400 hover:text-red-600 text-sm"
                  >
                    삭제
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={() => setForm(prev => ({
                ...prev,
                time_ranges: [...(prev.time_ranges || []), { start: '09:00', end: '18:00' }],
              }))}
              className="text-sm text-indigo-600 hover:text-indigo-800"
            >
              + 시간 범위 추가
            </button>
            <p className="text-xs text-gray-400 mt-1">미설정 시 하루 종일 적용</p>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="include_holidays"
              checked={form.include_holidays || false}
              onChange={e => setForm(prev => ({ ...prev, include_holidays: e.target.checked }))}
              className="w-4 h-4 text-indigo-600 rounded"
            />
            <label htmlFor="include_holidays" className="text-sm font-medium text-gray-700">
              공휴일 포함 (한국 공휴일 자동 적용)
            </label>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50">취소</button>
            <button type="submit" disabled={saving} className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
              {saving ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 통화 연결음 스케줄 할당 모달 (TTS 또는 Suno 생성 — 목록 순서가 평가 순서)
// ---------------------------------------------------------------------------

/** Suno `style` 필드용 — 서버 자동 생성과 유사한 영문 태그(직접 입력 없이 버튼으로만 채움). */
const SUNO_STYLE_PRESETS: { label: string; value: string }[] = [
  {
    label: '밝은 대기',
    value:
      'K-Pop, uplifting, bright, cheerful, advertisement jingle, hold music, male vocal, short, under 60 seconds',
  },
  {
    label: '차분한 대기',
    value:
      'Lo-fi, calm, warm, professional, friendly, hold music, soft, male vocal, short, under 60 seconds',
  },
  {
    label: '재즈',
    value:
      'Soft Jazz, smooth, warm, light groove, advertisement jingle, hold music, male vocal, under 60 seconds',
  },
  {
    label: '어쿠스틱',
    value:
      'Acoustic Pop, warm, friendly, gentle, brand music, hold music, male vocal, under 60 seconds',
  },
  {
    label: '경쾌 CM',
    value:
      'Corporate Pop, upbeat, positive, commercial jingle, bright, hold music, male vocal, under 60 seconds',
  },
];

interface RingbackAssignmentFormModalProps {
  row: Partial<RingbackScheduleAssignmentRow> | null;
  schedules: Schedule[];
  owner: string;
  onSave: (data: Partial<RingbackScheduleAssignmentRow>) => Promise<void>;
  onClose: () => void;
}

function RingbackAssignmentFormModal({
  row, schedules, owner, onSave, onClose,
}: RingbackAssignmentFormModalProps) {
  const isNew = !row?.id;
  const [name, setName] = useState(row?.name || '');
  const [scheduleId, setScheduleId] = useState<string>(row?.schedule_id || '');
  const [generationMode, setGenerationMode] = useState<'tts' | 'suno'>(
    (row?.generation_mode as 'tts' | 'suno') || 'suno',
  );
  const [ttsText, setTtsText] = useState(row?.tts_text || '');
  const [sunoLyrics, setSunoLyrics] = useState(row?.suno_lyrics || '');
  const [sunoStyle, setSunoStyle] = useState(row?.suno_style || '');
  const [enabled, setEnabled] = useState(row?.enabled !== false);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Suno 가사·스타일 AI 생성 시 LLM에 넘기는 운영자 요청(한글 가능) */
  const [lyricsBrief, setLyricsBrief] = useState('');
  const [lyricsWarning, setLyricsWarning] = useState<string | null>(null);

  useEffect(() => {
    if (!row) return;
    setName(row.name || '');
    setScheduleId(row.schedule_id || '');
    setGenerationMode((row.generation_mode as 'tts' | 'suno') || 'suno');
    setTtsText(row.tts_text || '');
    setSunoLyrics(row.suno_lyrics || '');
    setSunoStyle(row.suno_style || '');
    setEnabled(row.enabled !== false);
    setLyricsBrief('');
    setLyricsWarning(null);
  }, [row?.id, row?.updated_at, row?.suno_audio_path, row?.generation_mode, row?.suno_generation_status]);

  /** Suno API용 — 화면에서는 입력받지 않음(기존 링백 설정 UX). DB에 있으면 유지. */
  const sunoVocalForApi = (row?.suno_vocal_gender || 'm').toString().slice(0, 1) === 'f' ? 'f' : 'm';
  const sunoDurationForApi = row?.suno_duration_target ?? 60;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (generationMode === 'tts' && !ttsText.trim()) {
      setError('TTS 모드에서는 연결음으로 읽을 문구를 입력하세요.');
      return;
    }
    if (generationMode === 'suno') {
      if (!sunoLyrics.trim() || !sunoStyle.trim()) {
        setError('가사·스타일을 채운 뒤 «저장»하면 서버에서 Suno 음원 생성이 시작됩니다.');
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      const pickedSch = schedules.find(s => s.id === scheduleId);
      const displayName =
        name.trim()
        || (pickedSch ? formatScheduleOneLine(pickedSch) : '')
        || '통화 연결음';
      await onSave({
        ...row,
        owner,
        name: displayName,
        schedule_id: scheduleId.trim() ? scheduleId : null,
        enabled,
        generation_mode: generationMode,
        tts_text: ttsText,
        suno_lyrics: sunoLyrics.trim() || null,
        suno_style: sunoStyle.trim() || null,
        // DB·Suno API title — 별도 «곡 제목» 없이 표시 이름과 항상 동일
        suno_title: displayName,
        suno_vocal_gender: sunoVocalForApi,
        suno_duration_target: sunoDurationForApi,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const doGenLyrics = async () => {
    setBusy('가사');
    setError(null);
    setLyricsWarning(null);
    try {
      const brief = lyricsBrief.trim();
      const res = await apiJson<{ lyrics?: string; warning?: string | null }>('/api/ringback/generate-lyrics', {
        method: 'POST',
        body: {
          owner,
          duration_target: sunoDurationForApi,
          ...(brief ? { brief } : {}),
        },
      });
      if (!res.ok) throw new Error(res.message);
      if (res.data.lyrics) setSunoLyrics(res.data.lyrics);
      if (res.data.warning) setLyricsWarning(res.data.warning);
    } catch (err) {
      setError(err instanceof Error ? err.message : '가사 생성 실패');
    } finally {
      setBusy(null);
    }
  };

  /** 요청사항·가사 반영(LLM). 둘 다 비어 있으면 서버에서 기존 무작위와 동일. */
  const doGenStyleFromContext = async (opts?: { lyricsOverride?: string }) => {
    setBusy('스타일');
    setError(null);
    try {
      const brief = lyricsBrief.trim();
      const lyricsForStyle = (opts?.lyricsOverride ?? sunoLyrics).trim();
      const res = await apiJson<{ style?: string; used_llm?: boolean }>('/api/ringback/generate-style', {
        method: 'POST',
        body: {
          vocal_gender: sunoVocalForApi,
          duration_target: sunoDurationForApi,
          ...(brief ? { brief } : {}),
          ...(lyricsForStyle ? { lyrics: lyricsForStyle } : {}),
        },
      });
      if (!res.ok) throw new Error(res.message);
      if (res.data.style) setSunoStyle(res.data.style);
    } catch (err) {
      setError(err instanceof Error ? err.message : '스타일 생성 실패');
    } finally {
      setBusy(null);
    }
  };

  /** 프리셋 옆 «무작위» — 요청사항·가사 없이 서버 랜덤 태그만 */
  const doGenStyleRandom = async () => {
    setBusy('스타일');
    setError(null);
    try {
      const res = await apiJson<{ style?: string }>('/api/ringback/generate-style', {
        method: 'POST',
        body: { vocal_gender: sunoVocalForApi, duration_target: sunoDurationForApi },
      });
      if (!res.ok) throw new Error(res.message);
      if (res.data.style) setSunoStyle(res.data.style);
    } catch (err) {
      setError(err instanceof Error ? err.message : '스타일 생성 실패');
    } finally {
      setBusy(null);
    }
  };

  /** 가사 생성 후, 같은 요청·신규 가사로 스타일까지 맞춤 제안 */
  const doGenLyricsAndStyle = async () => {
    setBusy('연속');
    setError(null);
    setLyricsWarning(null);
    try {
      const brief = lyricsBrief.trim();
      const lr = await apiJson<{ lyrics?: string; warning?: string | null }>('/api/ringback/generate-lyrics', {
        method: 'POST',
        body: {
          owner,
          duration_target: sunoDurationForApi,
          ...(brief ? { brief } : {}),
        },
      });
      if (!lr.ok) throw new Error(lr.message);
      const newLyrics = lr.data.lyrics?.trim() || '';
      if (newLyrics) setSunoLyrics(newLyrics);
      if (lr.data.warning) setLyricsWarning(lr.data.warning);

      const st = await apiJson<{ style?: string }>('/api/ringback/generate-style', {
        method: 'POST',
        body: {
          vocal_gender: sunoVocalForApi,
          duration_target: sunoDurationForApi,
          ...(brief ? { brief } : {}),
          ...(newLyrics ? { lyrics: newLyrics } : {}),
        },
      });
      if (!st.ok) throw new Error(st.message);
      if (st.data.style) setSunoStyle(st.data.style);
    } catch (err) {
      setError(err instanceof Error ? err.message : '가사·스타일 생성 실패');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4 overflow-y-auto">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl my-6">
        <div className="flex justify-between items-center p-5 border-b">
          <h2 className="text-lg font-semibold">{isNew ? '통화 연결음 추가' : '통화 연결음 수정'}</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4 max-h-[calc(100vh-8rem)] overflow-y-auto">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">표시 이름</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="예: 평일 오전 연결음"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            />
            {generationMode === 'suno' && (
              <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">
                Suno AI 음원 생성 시 <strong>곡 제목</strong>에도 이 표시 이름이 그대로 사용됩니다.
              </p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">시간 스케줄</label>
            <select
              value={scheduleId}
              onChange={e => setScheduleId(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">항상 (시간 조건 없음)</option>
              {schedules.map(s => (
                <option key={s.id} value={s.id}>{formatScheduleOneLine(s)}</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">통화 연결음 탭에서 위에서 아래 순으로 평가됩니다 (착신 규칙과 동일).</p>
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700 mb-2">연결음 방식</span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="rb-mode"
                  checked={generationMode === 'tts'}
                  onChange={() => setGenerationMode('tts')}
                  className="text-indigo-600"
                />
                텍스트 TTS
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="rb-mode"
                  checked={generationMode === 'suno'}
                  onChange={() => setGenerationMode('suno')}
                  className="text-indigo-600"
                />
                Suno AI 음원
              </label>
            </div>
          </div>

          {generationMode === 'tts' ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">TTS로 읽을 문구 *</label>
              <textarea
                value={ttsText}
                onChange={e => setTtsText(e.target.value)}
                rows={5}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                placeholder="잠시만 기다려 주세요. 곧 연결해 드립니다."
              />
              <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">
                «저장» 시 서버가 Google TTS로 <strong>음성 파일(WAV)</strong>을 만들어 두고, 통화 시 그 파일만 반복 재생합니다(링 중 실시간 합성 아님).
              </p>
            </div>
          ) : (
            <div className="space-y-3 border border-gray-100 rounded-lg p-3 bg-gray-50/80">
              <p className="text-xs text-gray-500 leading-relaxed">
                가사·스타일을 준비한 뒤 «저장»을 누르면 서버에서 Suno 음원 생성이 시작됩니다. 완료되면 통화 연결음 목록에 자동 반영됩니다.
                서버에 <code className="text-[11px] bg-white px-1 rounded">SUNO_API_KEY</code>와 Suno가 POST할 수 있는 공개{' '}
                <code className="text-[11px] bg-white px-1 rounded">callBackUrl</code>(환경변수{' '}
                <code className="text-[11px] bg-white px-1 rounded">SUNO_CALLBACK_URL</code> 또는{' '}
                <code className="text-[11px] bg-white px-1 rounded">PUBLIC_API_BASE_URL</code> / config{' '}
                <code className="text-[11px] bg-white px-1 rounded">ringback.public_api_base_url</code>
                등)이 설정되어 있어야 합니다.
              </p>
              <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-3 space-y-2">
                <label className="block text-xs font-medium text-indigo-900">AI 생성 요청사항 (선택)</label>
                <textarea
                  value={lyricsBrief}
                  onChange={e => {
                    setLyricsBrief(e.target.value);
                    setLyricsWarning(null);
                  }}
                  rows={3}
                  className="w-full border border-indigo-200 rounded-lg px-3 py-2 text-sm bg-white placeholder:text-gray-400"
                  placeholder="예: 이탈리안 레스토랑 예약·웨이팅 안내를 넣고, 밝고 짧게 / 재즈풍으로 차분하게 / 힙합 느낌은 피하고 어쿠스틱 위주"
                />
                <p className="text-[11px] text-indigo-900/80 leading-relaxed">
                  비워 두면 페르소나·지식베이스만 반영해 이전과 같이 생성합니다. 내용을 쓰면 가사에 직접 반영되고, 스타일 제안 시에도 같은 의도로 영문 태그가 잡힙니다.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void doGenLyrics()}
                    disabled={!!busy}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-indigo-200 text-indigo-900 hover:bg-indigo-50 disabled:opacity-50"
                  >
                    {busy === '가사' ? '가사 생성 중…' : '가사만 생성'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void doGenStyleFromContext()}
                    disabled={!!busy}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-indigo-200 text-indigo-900 hover:bg-indigo-50 disabled:opacity-50"
                  >
                    {busy === '스타일' ? '스타일 생성 중…' : '스타일만 제안'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void doGenLyricsAndStyle()}
                    disabled={!!busy}
                    className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy === '연속' ? '생성 중…' : '가사 + 스타일 연속 생성'}
                  </button>
                </div>
                {lyricsWarning ? (
                  <p className="text-[11px] text-amber-800 bg-amber-50 border border-amber-100 rounded-md px-2 py-1.5">{lyricsWarning}</p>
                ) : null}
              </div>
              <div>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <label className="block text-xs font-medium text-gray-600">가사</label>
                </div>
                <textarea
                  value={sunoLyrics}
                  onChange={e => setSunoLyrics(e.target.value)}
                  rows={5}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                  placeholder="가사를 직접 쓰거나, 위에서 AI 생성 버튼을 사용하세요."
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">스타일 (Suno)</label>
                <p className="text-xs text-gray-500 mb-2 leading-relaxed">
                  장르·분위기를 <strong>영문 태그</strong>로 Suno에 넘깁니다. 아래 <strong>프리셋</strong>을 누르거나
                  <strong> 무작위 스타일</strong>(요청사항·가사 없이 랜덤)을 눌러 채울 수 있습니다. «스타일만 제안»은 위 요청사항·현재 가사를 반영해 LLM이 태그를 짓습니다.
                </p>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {SUNO_STYLE_PRESETS.map(p => (
                    <button
                      key={p.label}
                      type="button"
                      disabled={!!busy}
                      onClick={() => {
                        setSunoStyle(p.value);
                        setError(null);
                      }}
                      className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                        sunoStyle.trim() === p.value.trim()
                          ? 'border-indigo-500 bg-indigo-50 text-indigo-800'
                          : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => void doGenStyleRandom()}
                    disabled={!!busy}
                    className="px-2.5 py-1 text-xs rounded-full border border-dashed border-gray-400 text-gray-700 bg-white hover:bg-gray-50"
                  >
                    {busy === '스타일' ? '생성 중…' : '무작위 스타일'}
                  </button>
                </div>
                <textarea
                  value={sunoStyle}
                  onChange={e => setSunoStyle(e.target.value)}
                  rows={3}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white text-gray-800"
                  placeholder="위 프리셋 또는 «무작위 스타일»을 누르면 여기에 채워집니다."
                />
              </div>
            </div>
          )}

          <div className="flex items-center gap-3">
            <input
              id="rb-en"
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
              className="w-4 h-4 text-indigo-600 rounded"
            />
            <label htmlFor="rb-en" className="text-sm font-medium text-gray-700">활성</label>
          </div>
          {row?.id ? (
            <RingbackMediaPreview
              owner={owner}
              row={{
                id: row.id,
                generation_mode: row.generation_mode,
                suno_generation_status: row.suno_generation_status,
                suno_audio_path: row.suno_audio_path,
                suno_audio_url: row.suno_audio_url,
                tts_audio_path: row.tts_audio_path,
              }}
            />
          ) : null}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm">닫기</button>
            <button type="submit" disabled={saving || !!busy} className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">
              {saving ? '저장 중…' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Caller Filter Form Modal
// ---------------------------------------------------------------------------

interface CallerFilterFormModalProps {
  filter: Partial<CallerFilter> | null;
  owner: string;
  onSave: (data: Partial<CallerFilter>) => Promise<void>;
  onClose: () => void;
}

function CallerFilterFormModal({ filter, owner, onSave, onClose }: CallerFilterFormModalProps) {
  const isNew = !filter?.id;
  const [form, setForm] = useState<Partial<CallerFilter>>({
    owner,
    name: '',
    pattern: '',
    action: 'block',
    priority: 0,
    enabled: true,
    ...filter,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.pattern?.trim()) { setError('발신번호 패턴을 입력하세요.'); return; }
    setSaving(true);
    setError(null);
    try { await onSave({ ...form, name: form.pattern }); }
    catch (err) { setError(err instanceof Error ? err.message : '저장 실패'); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg">
        <div className="flex justify-between items-center p-5 border-b">
          <h2 className="text-lg font-semibold">{isNew ? '발신자 필터 추가' : '발신자 필터 수정'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* 발신번호 패턴 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">발신번호 패턴 *</label>
            <input
              type="text"
              value={form.pattern || ''}
              onChange={e => setForm(prev => ({ ...prev, pattern: e.target.value }))}
              placeholder="예: 010* (010으로 시작), 02-1234-5678 (정확 일치)"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <p className="text-xs text-gray-400 mt-1">
              <code className="bg-gray-100 px-1 rounded">*</code>을 사용해 접두사 매칭 가능. 예: <code className="bg-gray-100 px-1 rounded">010*</code>, <code className="bg-gray-100 px-1 rounded">+8210*</code>
            </p>
          </div>

          {/* 연결 옵션 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">연결 옵션 *</label>
            <div className="grid grid-cols-1 gap-2">
              {(Object.keys(FILTER_ACTION_LABELS) as FilterAction[]).map(action => (
                <button
                  key={action}
                  type="button"
                  onClick={() => setForm(prev => ({ ...prev, action }))}
                  className={`flex items-center gap-3 px-4 py-3 rounded-lg border-2 text-left transition-all ${
                    form.action === action
                      ? 'border-indigo-500 bg-indigo-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                    form.action === action ? 'bg-indigo-500' : 'bg-gray-300'
                  }`} />
                  <div>
                    <span className={`text-sm font-semibold px-2 py-0.5 rounded-full mr-2 ${FILTER_ACTION_COLORS[action]}`}>
                      {FILTER_ACTION_LABELS[action]}
                    </span>
                    <span className="text-xs text-gray-500">{FILTER_ACTION_DESC[action]}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 활성화 */}
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="filter-enabled"
              checked={form.enabled !== false}
              onChange={e => setForm(prev => ({ ...prev, enabled: e.target.checked }))}
              className="w-4 h-4 text-indigo-600 rounded"
            />
            <label htmlFor="filter-enabled" className="text-sm font-medium text-gray-700">필터 활성화</label>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50">취소</button>
            <button type="submit" disabled={saving} className="flex-1 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50">
              {saving ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

type TabId = 'rules' | 'schedules' | 'forward-targets' | 'ringback' | 'caller-filters';

const VALID_TABS: TabId[] = ['rules', 'schedules', 'forward-targets', 'ringback', 'caller-filters'];

function CallControlPage() {
  useWebSocket();
  const searchParams = useSearchParams();
  const [owner, setOwner] = useState('');
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    const tab = searchParams?.get('tab');
    return (VALID_TABS.includes(tab as TabId) ? tab : 'rules') as TabId;
  });
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [ringbackAssignments, setRingbackAssignments] = useState<RingbackScheduleAssignmentRow[]>([]);
  const [callerFilters, setCallerFilters] = useState<CallerFilter[]>([]);
  const [forwardTargets, setForwardTargets] = useState<ForwardTargetRow[]>([]);
  const [currentStatus, setCurrentStatus] = useState<CurrentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [editingRule, setEditingRule] = useState<Partial<RoutingRule> | null>(null);
  const [showRuleModal, setShowRuleModal] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<Partial<Schedule> | null>(null);
  const [showScheduleModal, setShowScheduleModal] = useState(false);
  const [editingRingbackAssignment, setEditingRingbackAssignment] = useState<Partial<RingbackScheduleAssignmentRow> | null>(null);
  const [showRingbackModal, setShowRingbackModal] = useState(false);
  const [editingFilter, setEditingFilter] = useState<Partial<CallerFilter> | null>(null);
  const [showFilterModal, setShowFilterModal] = useState(false);
  const [editingForwardTarget, setEditingForwardTarget] = useState<Partial<ForwardTargetRow> | null>(null);
  const [showForwardTargetModal, setShowForwardTargetModal] = useState(false);

  // 드래그 중 순서 저장용 (서버 동기화 debounce)
  const saveOrderDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveRingbackOrderDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const id = getTenantOwner() || '1004';
    setOwner(id);
  }, []);

  const loadAll = useCallback(async (o: string) => {
    if (!o) return;
    setLoading(true);
    setError(null);
    const [r1, r2, r3, r4, r5, r6] = await Promise.all([
      apiJson<RoutingRule[]>(`/api/call-control/rules?owner=${encodeURIComponent(o)}`),
      apiJson<Schedule[]>(`/api/call-control/schedules?owner=${encodeURIComponent(o)}`),
      apiJson<RingbackScheduleAssignmentRow[]>(`/api/call-control/ringback-assignments?owner=${encodeURIComponent(o)}`),
      apiJson<CurrentStatus>(`/api/call-control/status/${encodeURIComponent(o)}`),
      apiJson<CallerFilter[]>(`/api/call-control/caller-filters?owner=${encodeURIComponent(o)}`),
      apiJson<ForwardTargetRow[]>(`/api/call-control/forward-targets?owner=${encodeURIComponent(o)}`),
    ]);
    if (r1.ok) setRules(r1.data);
    if (r2.ok) setSchedules(r2.data);
    if (r3.ok) setRingbackAssignments(r3.data);
    if (r4.ok) setCurrentStatus(r4.data);
    if (r5.ok) setCallerFilters(r5.data);
    if (r6.ok) setForwardTargets(r6.data);
    if (!r1.ok) setError(r1.message);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (owner) loadAll(owner);
  }, [owner, loadAll]);

  const hasPendingSunoRingback = useMemo(
    () =>
      ringbackAssignments.some(
        r =>
          (r.generation_mode || 'suno').toLowerCase() === 'suno' &&
          (r.suno_generation_status || '').toLowerCase() === 'pending',
      ),
    [ringbackAssignments],
  );

  /** WebSocket 미연결·이벤트 유실 시에도 Suno 완료 반영 */
  useEffect(() => {
    if (!owner || !hasPendingSunoRingback) return;
    const id = window.setInterval(() => {
      void loadAll(owner);
    }, 10000);
    return () => window.clearInterval(id);
  }, [owner, hasPendingSunoRingback, loadAll]);

  useEffect(() => {
    if (!owner) return;
    const onRingbackWs = () => {
      void loadAll(owner);
    };
    wsClient.on('ringback_music_ready', onRingbackWs);
    wsClient.on('ringback_music_failed', onRingbackWs);
    return () => {
      wsClient.off('ringback_music_ready', onRingbackWs);
      wsClient.off('ringback_music_failed', onRingbackWs);
    };
  }, [owner, loadAll]);

  // --- Rule CRUD ---
  const saveRule = async (data: Partial<RoutingRule>) => {
    const isNew = !data.id;
    const body = isNew
      ? { ...data, priority: rules.length * 10 }  // 새 규칙은 목록 끝 priority
      : data;
    const res = isNew
      ? await apiJson<RoutingRule>('/api/call-control/rules', { method: 'POST', body: body as Record<string, unknown> })
      : await apiJson<RoutingRule>(`/api/call-control/rules/${data.id}`, { method: 'PUT', body: body as Record<string, unknown> });
    if (!res.ok) throw new Error(res.message);
    setShowRuleModal(false);
    await loadAll(owner);
  };

  const deleteRule = async (id: string) => {
    if (!confirm('규칙을 삭제하시겠습니까?')) return;
    await apiJson(`/api/call-control/rules/${id}`, { method: 'DELETE' });
    await loadAll(owner);
  };

  const toggleRule = async (rule: RoutingRule) => {
    await apiJson<RoutingRule>(`/api/call-control/rules/${rule.id}`, {
      method: 'PUT',
      body: { enabled: !rule.enabled } as Record<string, unknown>,
    });
    await loadAll(owner);
  };

  // 드래그 앤 드롭 순서 변경
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    setRules(prev => {
      const oldIdx = prev.findIndex(r => r.id === active.id);
      const newIdx = prev.findIndex(r => r.id === over.id);
      const reordered = arrayMove(prev, oldIdx, newIdx);

      // 서버에 순서 저장 (debounce 500ms)
      if (saveOrderDebounceRef.current) clearTimeout(saveOrderDebounceRef.current);
      saveOrderDebounceRef.current = setTimeout(async () => {
        await Promise.all(
          reordered.map((rule, idx) =>
            apiJson(`/api/call-control/rules/${rule.id}/priority`, {
              method: 'PATCH',
              body: { priority: idx * 10 } as Record<string, unknown>,
            })
          )
        );
      }, 500);

      return reordered;
    });
  };

  // --- Schedule CRUD ---
  const saveSchedule = async (data: Partial<Schedule>) => {
    const isNew = !data.id;
    const res = isNew
      ? await apiJson<Schedule>('/api/call-control/schedules', { method: 'POST', body: data as Record<string, unknown> })
      : await apiJson<Schedule>(`/api/call-control/schedules/${data.id}`, { method: 'PUT', body: data as Record<string, unknown> });
    if (!res.ok) throw new Error(res.message);
    setShowScheduleModal(false);
    await loadAll(owner);
  };

  const deleteSchedule = async (id: string) => {
    if (!confirm('스케줄을 삭제하시겠습니까?\n이 스케줄을 사용하는 규칙은 항상 적용으로 변경됩니다.')) return;
    await apiJson(`/api/call-control/schedules/${id}`, { method: 'DELETE' });
    await loadAll(owner);
  };

  // --- 통화 연결음(스케줄 할당) CRUD ---
  const saveRingbackAssignment = async (data: Partial<RingbackScheduleAssignmentRow>) => {
    const isNew = !data.id;
    const body: Record<string, unknown> = {
      name: data.name || '',
      schedule_id: data.schedule_id ?? null,
      enabled: data.enabled !== false,
      generation_mode: data.generation_mode ?? 'suno',
      tts_text: data.tts_text ?? '',
      tts_audio_path: data.tts_audio_path ?? null,
      suno_lyrics: data.suno_lyrics ?? null,
      suno_style: data.suno_style ?? null,
      suno_title: data.suno_title ?? null,
      suno_vocal_gender: data.suno_vocal_gender ?? 'm',
      suno_duration_target: data.suno_duration_target ?? 60,
      suno_audio_path: data.suno_audio_path ?? null,
      suno_audio_url: data.suno_audio_url ?? null,
      suno_task_id: data.suno_task_id ?? null,
    };
    const res = isNew
      ? await apiJson<RingbackScheduleAssignmentRow>('/api/call-control/ringback-assignments', {
          method: 'POST',
          body: { ...body, owner },
        })
      : await apiJson<RingbackScheduleAssignmentRow>(
          `/api/call-control/ringback-assignments/${data.id}?owner=${encodeURIComponent(owner)}`,
          { method: 'PUT', body },
        );
    if (!res.ok) throw new Error(res.message);
    setShowRingbackModal(false);
    setEditingRingbackAssignment(null);
    await loadAll(owner);
  };

  const toggleRingbackAssignment = async (row: RingbackScheduleAssignmentRow) => {
    await apiJson(`/api/call-control/ringback-assignments/${row.id}?owner=${encodeURIComponent(owner)}`, {
      method: 'PUT',
      body: { enabled: !row.enabled } as Record<string, unknown>,
    });
    await loadAll(owner);
  };

  const handleRingbackDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    setRingbackAssignments(prev => {
      const oldIdx = prev.findIndex(r => r.id === active.id);
      const newIdx = prev.findIndex(r => r.id === over.id);
      const reordered = arrayMove(prev, oldIdx, newIdx);

      if (saveRingbackOrderDebounceRef.current) clearTimeout(saveRingbackOrderDebounceRef.current);
      saveRingbackOrderDebounceRef.current = setTimeout(async () => {
        await apiJson(
          `/api/call-control/ringback-assignments/reorder?owner=${encodeURIComponent(owner)}`,
          {
            method: 'PATCH',
            body: { ordered_ids: reordered.map(r => r.id) } as Record<string, unknown>,
          },
        );
      }, 500);

      return reordered;
    });
  };

  const deleteRingbackAssignment = async (id: string) => {
    if (!confirm('이 통화 연결음 설정을 삭제하시겠습니까?')) return;
    await apiJson(
      `/api/call-control/ringback-assignments/${id}?owner=${encodeURIComponent(owner)}`,
      { method: 'DELETE' },
    );
    await loadAll(owner);
  };

  // --- Caller Filter CRUD ---
  const saveFilter = async (data: Partial<CallerFilter>) => {
    const isNew = !data.id;
    // FilterAction → API RoutingAction 매핑
    const apiAction = data.action === 'ai' ? 'immediate_ai' : data.action; // block→block, direct→direct
    const body = { ...data, action: apiAction };
    const res = isNew
      ? await apiJson<CallerFilter>('/api/call-control/caller-filters', { method: 'POST', body: body as Record<string, unknown> })
      : await apiJson<CallerFilter>(`/api/call-control/caller-filters/${data.id}`, { method: 'PUT', body: body as Record<string, unknown> });
    if (!res.ok) throw new Error(res.message);
    setShowFilterModal(false);
    await loadAll(owner);
  };

  const deleteFilter = async (id: string) => {
    if (!confirm('필터를 삭제하시겠습니까?')) return;
    await apiJson(`/api/call-control/caller-filters/${id}`, { method: 'DELETE' });
    await loadAll(owner);
  };

  const saveForwardTarget = async (data: Partial<ForwardTargetRow>) => {
    const isNew = !data.id;
    const kind = data.kind || 'single';
    const payload: Record<string, unknown> = {
      name: data.name || '',
      kind,
      single_extension: kind === 'single' ? (data.single_extension || '').trim() || null : null,
      members: kind === 'group' ? (data.members || []).map(m => String(m).trim()).filter(Boolean) : [],
      ring_mode: data.ring_mode || 'simultaneous',
    };
    const res = isNew
      ? await apiJson<ForwardTargetRow>('/api/call-control/forward-targets', {
          method: 'POST',
          body: { ...payload, owner },
        })
      : await apiJson<ForwardTargetRow>(
          `/api/call-control/forward-targets/${data.id}?owner=${encodeURIComponent(owner)}`,
          { method: 'PUT', body: payload },
        );
    if (!res.ok) throw new Error(res.message);
    setShowForwardTargetModal(false);
    setEditingForwardTarget(null);
    await loadAll(owner);
  };

  const deleteForwardTarget = async (id: string) => {
    if (!confirm('이 착신 전환 대상을 삭제하시겠습니까?\n착신 규칙에 참조(fwd:…)가 남아 있으면 전환이 실패할 수 있습니다.')) return;
    await apiJson(
      `/api/call-control/forward-targets/${id}?owner=${encodeURIComponent(owner)}`,
      { method: 'DELETE' },
    );
    await loadAll(owner);
  };

  // 서버에서 온 CallerFilter action 값을 UI FilterAction으로 역매핑
  const toFilterAction = (cf: CallerFilter): FilterAction => {
    const a = cf.action as string;
    if (a === 'block') return 'block';
    if (a === 'direct') return 'direct';
    return 'ai'; // immediate_ai, no_answer_ai 등
  };

  const tabs = [
    { id: 'rules' as TabId, label: '착신 규칙', count: rules.length },
    { id: 'schedules' as TabId, label: '시간 스케줄', count: schedules.length },
    { id: 'forward-targets' as TabId, label: '착신 전환', count: forwardTargets.length },
    { id: 'ringback' as TabId, label: '통화 연결음', count: ringbackAssignments.length },
    { id: 'caller-filters' as TabId, label: '발신자 필터', count: callerFilters.length },
  ];

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">착신 제어 (Call Control)</h1>
          <p className="text-sm text-gray-500 mt-1">
            내선 <span className="font-medium text-gray-700">{owner}</span>의 착신 동작, 시간 스케줄, 착신 전환 대상, 통화 연결음을 설정합니다.
          </p>
          <p className="text-sm mt-2">
            <Link href="/settings/ai-escalation" className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium">
              AI 에스컬레이션 (한계 시 동작) 설정
            </Link>
          </p>
        </div>
        <button
          onClick={() => loadAll(owner)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-600"
        >
          새로고침
        </button>
      </div>

      {/* 현재 상태 카드 */}
      {currentStatus && (
        <div className={`rounded-xl border-2 p-4 ${
          currentStatus.is_schedule_active
            ? 'border-indigo-200 bg-indigo-50'
            : 'border-gray-200 bg-gray-50'
        }`}>
          <div className="flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${
              currentStatus.is_schedule_active ? 'bg-indigo-500' : 'bg-gray-400'
            }`} />
            <div>
              <p className="text-sm font-semibold text-gray-900">현재 적용 중</p>
              <p className="text-sm text-gray-600 mt-0.5">
                {formatCallControlStatusLine(owner, currentStatus.description)}
              </p>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
      )}

      {/* 탭 */}
      <div className="border-b border-gray-200">
        <div className="flex gap-1">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
              {tab.count > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-xs ${
                  activeTab === tab.id ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600'
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 탭 콘텐츠 */}
      {loading ? (
        <div className="flex items-center justify-center h-40 text-gray-400">로딩 중...</div>
      ) : (
        <>
          {/* ── 착신 규칙 탭 ── */}
          {activeTab === 'rules' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-500">
                  위에서 아래 순서로 평가되며, 조건이 일치하는 첫 번째 규칙이 적용됩니다.
                  <span className="ml-1 text-gray-400">드래그(⠿)로 순서를 변경하세요.</span>
                </p>
                <button
                  onClick={() => { setEditingRule(null); setShowRuleModal(true); }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
                >
                  + 규칙 추가
                </button>
              </div>

              {rules.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p className="text-lg">착신 규칙이 없습니다.</p>
                  <p className="text-sm mt-1">규칙이 없으면 기본 직접 연결(A→B)이 적용됩니다.</p>
                </div>
              ) : (
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext items={rules.map(r => r.id)} strategy={verticalListSortingStrategy}>
                    <div className="space-y-3">
                      {rules.map((rule, idx) => (
                        <SortableRuleCard
                          key={rule.id}
                          rule={rule}
                          index={idx}
                          schedules={schedules}
                          forwardTargets={forwardTargets}
                          currentRuleId={currentStatus?.rule?.id}
                          onToggle={toggleRule}
                          onEdit={r => { setEditingRule(r); setShowRuleModal(true); }}
                          onDelete={deleteRule}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}
            </div>
          )}

          {/* ── 시간 스케줄 탭 ── */}
          {activeTab === 'schedules' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-500">착신 규칙에 연결할 시간 조건을 정의합니다.</p>
                <button
                  onClick={() => { setEditingSchedule(null); setShowScheduleModal(true); }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
                >
                  + 스케줄 추가
                </button>
              </div>

              {schedules.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p>스케줄이 없습니다.</p>
                  <p className="text-sm mt-1">시간 조건 없이 항상 적용되는 규칙만 사용 중입니다.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {schedules.map(s => (
                    <div key={s.id} className="rounded-xl border border-gray-200 bg-white p-4">
                      <div className="flex justify-between items-start">
                        <div className="min-w-0 pr-2">
                          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">시간 조건</p>
                          <div className="mt-1 space-y-0.5 text-sm text-gray-800">
                            {formatScheduleDetailLines(s).map((line, i) => (
                              <p key={i} className="leading-relaxed">{line}</p>
                            ))}
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <button onClick={() => { setEditingSchedule(s); setShowScheduleModal(true); }} className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50">수정</button>
                          <button onClick={() => deleteSchedule(s.id)} className="px-3 py-1.5 text-xs border border-red-100 text-red-600 rounded-lg hover:bg-red-50">삭제</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 착신 전환 대상 탭 ── */}
          {activeTab === 'forward-targets' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-500 max-w-3xl">
                  착신 규칙에서 «착신 전환» 동작의 대상으로 선택할 수 있는 항목입니다.
                  단일 내선 또는 여러 내선 그룹을 등록한 뒤, 착신 규칙 탭에서 «착신 전환 탭 대상»으로 연결하세요.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setEditingForwardTarget({ owner, kind: 'single', members: [], ring_mode: 'simultaneous' });
                    setShowForwardTargetModal(true);
                  }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 flex-shrink-0 ml-4"
                >
                  + 대상 추가
                </button>
              </div>

              {forwardTargets.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p>등록된 착신 전환 대상이 없습니다.</p>
                  <p className="text-sm mt-1">단일 내선 또는 그룹을 추가한 뒤 규칙의 전환 대상으로 지정할 수 있습니다.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {forwardTargets.map(t => (
                    <div
                      key={t.id}
                      className="rounded-xl border border-gray-200 bg-white p-4 flex justify-between items-start gap-4"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-gray-900">{t.name}</span>
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                            t.kind === 'group' ? 'bg-violet-100 text-violet-800' : 'bg-slate-100 text-slate-700'
                          }`}>
                            {t.kind === 'group' ? '그룹' : '단일'}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1 break-words">{forwardTargetSummary(t)}</p>
                        <p className="text-xs text-gray-400 mt-1 font-mono">id: {t.id}</p>
                      </div>
                      <div className="flex gap-2 flex-shrink-0">
                        <button
                          type="button"
                          onClick={() => { setEditingForwardTarget(t); setShowForwardTargetModal(true); }}
                          className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50"
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteForwardTarget(t.id)}
                          className="px-3 py-1.5 text-xs border border-red-100 text-red-600 rounded-lg hover:bg-red-50"
                        >
                          삭제
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 통화 연결음 탭 (스케줄 → 저장된 Suno 음원) ── */}
          {activeTab === 'ringback' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-500">
                  위에서 아래 순으로 평가되며, 스케줄이 맞는 첫 항목의 TTS 또는 Suno 연결음이 재생됩니다.
                  <span className="ml-1 text-gray-400">드래그(⠿)로 순서를 바꿀 수 있습니다.</span>
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setEditingRingbackAssignment({
                      owner,
                      enabled: true,
                      generation_mode: 'suno',
                      tts_text: '',
                    });
                    setShowRingbackModal(true);
                  }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
                >
                  + 통화 연결음 추가
                </button>
              </div>

              {ringbackAssignments.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p>등록된 통화 연결음 스케줄이 없습니다.</p>
                  <p className="text-sm mt-1">매칭되는 항목이 없으면 기본 설정(ringback_settings)의 연결음 경로가 사용됩니다.</p>
                </div>
              ) : (
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleRingbackDragEnd}
                >
                  <SortableContext items={ringbackAssignments.map(r => r.id)} strategy={verticalListSortingStrategy}>
                    <div className="space-y-3">
                      {ringbackAssignments.map((row, idx) => (
                        <SortableRingbackAssignmentCard
                          key={row.id}
                          row={row}
                          index={idx}
                          owner={owner}
                          schedules={schedules}
                          onToggle={toggleRingbackAssignment}
                          onEdit={r => { setEditingRingbackAssignment(r); setShowRingbackModal(true); }}
                          onDelete={deleteRingbackAssignment}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}
            </div>
          )}

          {/* ── 발신자 필터 탭 ── */}
          {activeTab === 'caller-filters' && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-gray-500">
                  발신번호 패턴과 일치하면 착신 규칙보다 먼저 이 동작이 적용됩니다.
                </p>
                <button
                  onClick={() => { setEditingFilter(null); setShowFilterModal(true); }}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
                >
                  + 필터 추가
                </button>
              </div>

              {callerFilters.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <p>발신자 필터가 없습니다.</p>
                  <p className="text-sm mt-1">특정 번호에 대해 차단, 직접 응대, AI 응대를 설정할 수 있습니다.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {callerFilters.map(cf => {
                    const uiAction = toFilterAction(cf);
                    return (
                      <div
                        key={cf.id}
                        className={`rounded-xl border p-4 bg-white ${cf.enabled ? 'border-gray-200' : 'border-gray-100 opacity-60'}`}
                      >
                        <div className="flex justify-between items-center">
                          <div className="flex-1 min-w-0 mr-4">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-medium text-gray-900">{cf.name}</span>
                              <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${FILTER_ACTION_COLORS[uiAction]}`}>
                                {FILTER_ACTION_LABELS[uiAction]}
                              </span>
                              {!cf.enabled && (
                                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">비활성</span>
                              )}
                            </div>
                            <p className="text-xs text-gray-500 mt-1">
                              패턴: <code className="bg-gray-100 px-1 rounded">{cf.pattern}</code>
                            </p>
                          </div>
                          <div className="flex gap-2 flex-shrink-0">
                            <button
                              onClick={() => { setEditingFilter({ ...cf, action: uiAction }); setShowFilterModal(true); }}
                              className="px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50"
                            >
                              수정
                            </button>
                            <button
                              onClick={() => deleteFilter(cf.id)}
                              className="px-3 py-1.5 text-xs border border-red-100 text-red-600 rounded-lg hover:bg-red-50"
                            >
                              삭제
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Modals */}
      {showRuleModal && (
        <RuleFormModal
          key={editingRule?.id ? `rule-${editingRule.id}` : 'rule-new'}
          rule={editingRule}
          schedules={schedules}
          forwardTargets={forwardTargets}
          owner={owner}
          onSave={saveRule}
          onClose={() => setShowRuleModal(false)}
        />
      )}
      {showForwardTargetModal && (
        <ForwardTargetFormModal
          key={editingForwardTarget?.id ? `ft-${editingForwardTarget.id}` : 'ft-new'}
          row={editingForwardTarget}
          owner={owner}
          onSave={saveForwardTarget}
          onClose={() => {
            setShowForwardTargetModal(false);
            setEditingForwardTarget(null);
          }}
        />
      )}
      {showScheduleModal && (
        <ScheduleFormModal
          schedule={editingSchedule}
          owner={owner}
          onSave={saveSchedule}
          onClose={() => setShowScheduleModal(false)}
        />
      )}
      {showRingbackModal && (
        <RingbackAssignmentFormModal
          row={editingRingbackAssignment}
          schedules={schedules}
          owner={owner}
          onSave={saveRingbackAssignment}
          onClose={() => {
            setShowRingbackModal(false);
            setEditingRingbackAssignment(null);
          }}
        />
      )}
      {showFilterModal && (
        <CallerFilterFormModal
          filter={editingFilter}
          owner={owner}
          onSave={saveFilter}
          onClose={() => setShowFilterModal(false)}
        />
      )}
    </div>
  );
}

export default function CallControlPageWithSuspense() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-600">불러오는 중…</div>}>
      <CallControlPage />
    </Suspense>
  );
}
