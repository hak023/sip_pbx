/**
 * 지식 추가 — /api/knowledge 스펙과 knowledge/page.tsx 와 동일.
 * (구버전 faq/keywords/metadata 전용 폼 제거)
 */

'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { KNOWLEDGE_CATEGORIES, DOC_TYPES } from '@/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function AddKnowledgePage() {
  const router = useRouter();
  const [tenant, setTenant] = useState<{ owner: string; name?: string } | null>(null);
  const [text, setText] = useState('');
  const [category, setCategory] = useState('question');
  const [docType, setDocType] = useState<string>('knowledge');
  const [answer, setAnswer] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [department, setDepartment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);

  useEffect(() => {
    const t = localStorage.getItem('tenant');
    if (!t) {
      router.push('/login');
      return;
    }
    try {
      setTenant(JSON.parse(t) as { owner: string; name?: string });
    } catch {
      router.push('/login');
    }
  }, [router]);

  const needsAnswer = ['greeting_phase1', 'greeting_phase2', 'farewell'].includes(category);
  const needsContactFields = category === 'contact';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenant?.owner || !text.trim()) {
      setMessage({ type: 'error', text: '로그인(착신 owner)과 내용을 입력하세요.' });
      return;
    }
    if (category === 'contact' && !phoneNumber.trim()) {
      setMessage({ type: 'error', text: '연락처 카테고리는 전화번호가 필요합니다.' });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    try {
      const res = await fetch(`${API_URL}/api/knowledge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          text: text.trim(),
          owner: tenant.owner,
          category,
          doc_type: docType,
          answer: answer.trim() || undefined,
          source: 'api',
          ...(category === 'contact'
            ? {
                phone_number: phoneNumber.trim(),
                ...(department.trim() ? { department: department.trim() } : {}),
              }
            : {}),
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        ok?: boolean;
        doc_id?: string;
        cached?: boolean;
        detail?: unknown;
        error?: string;
      };
      if (res.ok && data.ok) {
        setMessage({
          type: 'ok',
          text: `저장됨 (doc_id: ${data.doc_id}${data.cached ? ', 즉시 캐시됨' : ''})`,
        });
        setText('');
        setAnswer('');
        setPhoneNumber('');
        setDepartment('');
      } else {
        const err =
          typeof data.detail === 'string'
            ? data.detail
            : data.detail
              ? JSON.stringify(data.detail)
              : data.error || `HTTP ${res.status}`;
        setMessage({ type: 'error', text: err });
      }
    } catch (err) {
      setMessage({ type: 'error', text: (err as Error).message || '요청 실패' });
    } finally {
      setSubmitting(false);
    }
  };

  if (!tenant) {
    return <div className="p-6 text-gray-600 text-sm">로딩 중…</div>;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-4">
          <button
            type="button"
            onClick={() => router.push('/knowledge')}
            className="text-sm text-indigo-600 hover:text-indigo-800"
          >
            ← 지식 목록
          </button>
          <h1 className="text-xl font-bold text-gray-900">지식 추가</h1>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-8">
        <p className="text-sm text-gray-600 mb-6">
          착신 테넌트: <strong>{tenant.owner}</strong> — API는 SIP username 형태(예: 1004)로 정규화되어 저장됩니다.
        </p>

        <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">카테고리 *</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {KNOWLEDGE_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">모든 카테고리는 통화 시 RAG 검색 후보에 포함됩니다.</p>
          </div>

          {needsContactFields && (
            <div className="space-y-2 rounded-md border border-amber-100 bg-amber-50/50 p-3">
              <p className="text-xs text-amber-900 font-medium">연락처 — 전화번호 필수</p>
              <input
                type="text"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="전화번호 *"
              />
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="부서명 (선택)"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">문서 유형</label>
            <select
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              {DOC_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">내용 *</label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={6}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="질문 문장 또는 안내 문구"
              required
            />
          </div>

          {needsAnswer && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">응답 (즉시 캐시용)</label>
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={2}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              />
            </div>
          )}

          {message && (
            <p className={`text-sm ${message.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {message.text}
            </p>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => router.push('/knowledge')}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium disabled:opacity-50"
            >
              {submitting ? '저장 중…' : '저장'}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
