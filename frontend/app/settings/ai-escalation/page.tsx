'use client';

/**
 * AI 에스컬레이션 설정 — 페르소나의 escalation_mode (hitl | transfer | none) 만 갱신.
 * 호전환 대상은 «상담원 직접 연결» 모드에서 착신 규칙(call-control)으로 결정되며 고정 내선 입력은 사용하지 않는다.
 */

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { apiJson } from '@/lib/api';
import { getTenantOwner } from '@/lib/tenant';

export type EscalationMode = 'hitl' | 'transfer' | 'none';

interface PersonaEscalationFields {
  escalation_mode: EscalationMode;
  transfer_extension?: string | null;
}

export default function AiEscalationSettingsPage() {
  const [owner, setOwner] = useState('');
  const [mode, setMode] = useState<EscalationMode>('hitl');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = getTenantOwner() || '1004';
    setOwner(id);
  }, []);

  const load = useCallback(async (o: string) => {
    if (!o) return;
    setLoading(true);
    setError(null);
    const res = await apiJson<PersonaEscalationFields>(`/api/persona/${encodeURIComponent(o)}`);
    if (res.ok) {
      const m = (res.data.escalation_mode || 'hitl').toLowerCase() as EscalationMode;
      setMode(m === 'transfer' || m === 'none' ? m : 'hitl');
    } else if (res.status === 404) {
      setMode('hitl');
    } else {
      setError(res.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (owner) void load(owner);
  }, [owner, load]);

  const save = async () => {
    if (!owner) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    const body: { escalation_mode: EscalationMode; transfer_extension?: null } = {
      escalation_mode: mode,
    };
    if (mode === 'transfer' || mode === 'none') {
      body.transfer_extension = null;
    }
    const res = await apiJson<PersonaEscalationFields>(
      `/api/persona/${encodeURIComponent(owner)}/escalation`,
      { method: 'PUT', body },
    );
    if (res.ok) {
      setMessage('저장되었습니다.');
      await load(owner);
    } else {
      setError(res.message);
    }
    setSaving(false);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex justify-between items-start gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AI 에스컬레이션</h1>
          <p className="text-sm text-gray-500 mt-1">
            내선 <span className="font-medium text-gray-700">{owner || '—'}</span> — AI가 답변 한계에 도달했을 때의 동작입니다.
          </p>
          <p className="text-sm mt-2">
            <Link href="/settings/call-control" className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium">
              ← 착신 제어 (Call Control)
            </Link>
          </p>
        </div>
        <button
          type="button"
          onClick={() => owner && load(owner)}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-600 flex-shrink-0"
        >
          새로고침
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
      )}
      {message && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">{message}</div>
      )}

      {loading ? (
        <p className="text-sm text-gray-500">불러오는 중…</p>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-5">
          <fieldset className="space-y-4">
            <legend className="text-sm font-semibold text-gray-900 mb-2">한계 시 동작</legend>

            <label className="flex gap-3 cursor-pointer items-start">
              <input
                type="radio"
                name="escalation"
                className="mt-1"
                checked={mode === 'hitl'}
                onChange={() => setMode('hitl')}
              />
              <span>
                <span className="font-medium text-gray-900">운영자 알림 (HITL)</span>
                <span className="block text-sm text-gray-600 mt-0.5">
                  대시보드에 개입 요청을 보내고, 고객에게는 통일된 한계 안내 멘트를 재생합니다.
                </span>
              </span>
            </label>

            <label className="flex gap-3 cursor-pointer items-start">
              <input
                type="radio"
                name="escalation"
                className="mt-1"
                checked={mode === 'transfer'}
                onChange={() => setMode('transfer')}
              />
              <span>
                <span className="font-medium text-gray-900">상담원 직접 연결 (SIP 호전환)</span>
                <span className="block text-sm text-gray-600 mt-0.5">
                  호전환 대상은 이 화면의 고정 내선이 아니라,{' '}
                  <strong>착신 규칙</strong>(발신자 필터 → 규칙 우선순위, 스케줄·전환·그룹)과 동일한 우선순위로 결정됩니다.
                  «착신 제어»에서 규칙과 전환 대상을 맞춰 두세요.
                </span>
              </span>
            </label>

            <label className="flex gap-3 cursor-pointer items-start">
              <input
                type="radio"
                name="escalation"
                className="mt-1"
                checked={mode === 'none'}
                onChange={() => setMode('none')}
              />
              <span>
                <span className="font-medium text-gray-900">AI가 에스컬레이션 하지 않음</span>
                <span className="block text-sm text-gray-600 mt-0.5">
                  모르는 내용·저신뢰 등 <strong>AI 판정</strong>으로 올라가는 HITL/호전환만 끕니다. 고객이 명시적으로 상담원 연결을 말한 경우는 기존처럼 처리합니다.
                </span>
              </span>
            </label>
          </fieldset>

          <div className="pt-2 border-t border-gray-100">
            <button
              type="button"
              disabled={saving || !owner}
              onClick={() => void save()}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? '저장 중…' : '저장'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
