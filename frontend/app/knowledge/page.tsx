'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { KNOWLEDGE_CATEGORIES, DOC_TYPES, KNOWLEDGE_SOURCES, type KnowledgeItem } from '@/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function KnowledgePage() {
  const router = useRouter();
  const [tenant, setTenant] = useState<{ owner: string; name?: string } | null>(null);
  const [text, setText] = useState('');
  const [category, setCategory] = useState('question');
  const [docType, setDocType] = useState<string>('knowledge'); // 추가
  const [answer, setAnswer] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [department, setDepartment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [filterOwner, setFilterOwner] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterDocType, setFilterDocType] = useState(''); // 추가
  const [filterSource, setFilterSource] = useState(''); // 추가
  const [loadingList, setLoadingList] = useState(false);
  const [groupByCategory, setGroupByCategory] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    const t = localStorage.getItem('tenant');
    if (!t) {
      router.push('/login');
      return;
    }
    try {
      const parsed = JSON.parse(t) as { owner: string; name?: string };
      setTenant(parsed);
      setFilterOwner(parsed.owner || '');
    } catch {
      router.push('/login');
    }
  }, [router]);

  const fetchList = useCallback(async () => {
    setLoadingList(true);
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    const params = new URLSearchParams();
    if (filterOwner) {
      params.set('owner', filterOwner);
    }
    if (filterCategory) params.set('category', filterCategory);
    if (filterDocType) params.set('doc_type', filterDocType); // 추가
    if (filterSource) params.set('source', filterSource); // 추가
    try {
      const res = await fetch(`${API_URL}/api/knowledge?${params.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setItems(Array.isArray(data.items) ? data.items : []);
        setMessage(null);
      } else {
        setItems([]);
        const err = await res.json().catch(() => ({}));
        const detail = err.detail ?? err.error ?? `HTTP ${res.status}`;
        setMessage({ type: 'error', text: typeof detail === 'string' ? detail : JSON.stringify(detail) });
      }
    } catch {
      setItems([]);
    } finally {
      setLoadingList(false);
    }
  }, [filterOwner, filterCategory, filterDocType, filterSource]);

  useEffect(() => {
    if (tenant) fetchList();
  }, [tenant, fetchList]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenant?.owner || !text.trim() || !category) {
      setMessage({ type: 'error', text: '착신(owner), 내용(text), 카테고리(category)를 입력하세요.' });
      return;
    }
    if (category === 'contact' && !phoneNumber.trim()) {
      setMessage({ type: 'error', text: '연락처 카테고리는 전화번호(phone_number)가 필요합니다.' });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    const postUrl = `${API_URL}/api/knowledge`;
    try {
      const res = await fetch(postUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          text: text.trim(),
          owner: tenant.owner,
          category,
          doc_type: docType, // 추가
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
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setMessage({ type: 'ok', text: `저장됨 (doc_id: ${data.doc_id}${data.cached ? ', 즉시 캐시됨' : ''})` });
        setText('');
        setAnswer('');
        setPhoneNumber('');
        setDepartment('');
        fetchList();
      } else {
        const errorMsg = typeof data.detail === 'string' 
          ? data.detail 
          : data.detail 
            ? JSON.stringify(data.detail) 
            : data.error || `HTTP ${res.status}`;
        setMessage({ type: 'error', text: errorMsg });
      }
    } catch (err) {
      setMessage({ type: 'error', text: (err as Error).message || '요청 실패' });
    } finally {
      setSubmitting(false);
    }
  };

  const needsAnswer = ['greeting_phase1', 'greeting_phase2', 'farewell'].includes(category);
  const needsContactFields = category === 'contact';

  const handleDelete = async (docId: string) => {
    if (!confirm('이 지식을 삭제할까요?')) return;
    setDeletingId(docId);
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    try {
      const res = await fetch(`${API_URL}/api/knowledge/${encodeURIComponent(docId)}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setMessage({ type: 'ok', text: '삭제되었습니다.' });
        fetchList();
      } else {
        setMessage({ type: 'error', text: data.detail || data.error || `HTTP ${res.status}` });
      }
    } catch (err) {
      setMessage({ type: 'error', text: (err as Error).message || '삭제 요청 실패' });
    } finally {
      setDeletingId(null);
    }
  };

  const categoryLabel = (value: string) => KNOWLEDGE_CATEGORIES.find((c) => c.value === value)?.label ?? value;
  const itemsByCategory = items.reduce<Record<string, KnowledgeItem[]>>((acc, item) => {
    const cat = item.metadata?.category ?? 'unknown';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});
  const sortedCategories = Object.keys(itemsByCategory).sort();

  return (
    <div>
      <div className="max-w-4xl mx-auto px-0 py-4">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">지식 베이스</h1>
        <p className="text-gray-600 text-sm mb-6">
          등록한 문구는 의도(질문·불만·전환·잡담·인사 등)에 맞춰 <strong>벡터 검색(RAG)</strong>에 포함됩니다.
          인사·종료는 <strong>응답 문장</strong>을 넣으면 캐시로 더 빠르게 반응하고, 캐시 미스 시에도 동일 문구는 지식 컬렉션에서 검색됩니다.
        </p>

        {/* 등록 폼 */}
        <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow p-6 mb-8">
          <h2 className="text-lg font-semibold mb-4">지식 추가</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">카테고리 *</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                {KNOWLEDGE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                질의·FAQ·잡담·불만·전환·연락처는 모두 RAG 후보입니다. (doc_type은 검색 필터가 아니라 구분용입니다.)
              </p>
            </div>
            {needsContactFields && (
              <div className="space-y-2 rounded-md border border-amber-100 bg-amber-50/50 p-3">
                <p className="text-xs text-amber-900 font-medium">연락처 카테고리 — 전화번호 필수</p>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">전화번호 *</label>
                  <input
                    type="text"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value)}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder="예: 02-1234-5678"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">부서명 (선택)</label>
                  <input
                    type="text"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder="예: 총무팀"
                  />
                </div>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">문서 유형 (doc_type)</label>
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                {DOC_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">대시보드 입력은 기본적으로 knowledge 사용</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">내용 (질문/문구) *</label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="예: 안녕하세요, OO입니다 / 영업시간이 궁금해요"
              />
            </div>
            {needsAnswer && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">응답 문장 (즉시 캐시용)</label>
                <textarea
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  rows={2}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  placeholder="예: 안녕하세요. 무엇을 도와드릴까요?"
                />
                <p className="text-xs text-gray-500 mt-1">인사/종료 인사는 이 문장이 캐시되어 다음 통화부터 즉시 사용됩니다.</p>
              </div>
            )}
          </div>
          {message && (
            <p className={`mt-3 text-sm ${message.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {message.text}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="mt-4 px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? '저장 중…' : '저장'}
          </button>
        </form>

        {/* 목록 — 조회·삭제·카테고리별 분류 */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold mb-4">등록된 지식 (조회·삭제·카테고리별 분류)</h2>
          <div className="flex flex-wrap items-center gap-4 mb-4">
            <input
              type="text"
              value={filterOwner}
              onChange={(e) => setFilterOwner(e.target.value)}
              placeholder="owner 필터"
              className="border border-gray-300 rounded px-2 py-1 text-sm w-24"
            />
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
            >
              <option value="">전체 카테고리</option>
              {KNOWLEDGE_CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
            <select
              value={filterDocType}
              onChange={(e) => setFilterDocType(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
            >
              <option value="">전체 doc_type</option>
              {DOC_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
            <select
              value={filterSource}
              onChange={(e) => setFilterSource(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm"
            >
              <option value="">전체 source</option>
              {KNOWLEDGE_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={groupByCategory}
                onChange={(e) => setGroupByCategory(e.target.checked)}
                className="rounded border-gray-300"
              />
              카테고리별 분류 표시
            </label>
            <button
              type="button"
              onClick={fetchList}
              disabled={loadingList}
              className="px-3 py-1 rounded bg-gray-100 hover:bg-gray-200 text-sm disabled:opacity-50"
            >
              새로고침
            </button>
          </div>
          {loadingList ? (
            <p className="text-gray-500 text-sm">로딩 중…</p>
          ) : items.length === 0 ? (
            <p className="text-gray-500 text-sm">등록된 지식이 없거나 API를 사용할 수 없습니다.</p>
          ) : groupByCategory && sortedCategories.length > 0 ? (
            <div className="space-y-6">
              {sortedCategories.map((cat) => (
                <div key={cat}>
                  <h3 className="text-sm font-medium text-gray-700 mb-2 pb-1 border-b">
                    {categoryLabel(cat)} ({itemsByCategory[cat].length}건)
                  </h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-gray-600">
                          <th className="py-2 pr-4">ID</th>
                          <th className="py-2 pr-4">owner</th>
                          <th className="py-2 pr-4">doc_type</th>
                          <th className="py-2 pr-4">source</th>
                          <th className="py-2 pr-4">내용</th>
                          <th className="py-2 w-20">삭제</th>
                        </tr>
                      </thead>
                      <tbody>
                        {itemsByCategory[cat].map((row) => (
                          <tr key={row.id} className="border-b border-gray-100">
                            <td className="py-2 pr-4 font-mono text-xs">{row.id}</td>
                            <td className="py-2 pr-4">{row.metadata?.owner ?? '-'}</td>
                            <td className="py-2 pr-4">{DOC_TYPES.find(t => t.value === row.metadata?.doc_type)?.label ?? row.metadata?.doc_type ?? '-'}</td>
                            <td className="py-2 pr-4">{KNOWLEDGE_SOURCES.find(s => s.value === row.metadata?.source)?.label ?? row.metadata?.source ?? '-'}</td>
                            <td className="py-2 max-w-md truncate" title={row.text}>{row.text}</td>
                            <td className="py-2">
                              <button
                                type="button"
                                onClick={() => handleDelete(row.id)}
                                disabled={deletingId === row.id}
                                className="text-red-600 hover:text-red-800 text-xs disabled:opacity-50"
                              >
                                {deletingId === row.id ? '삭제 중…' : '삭제'}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-gray-600">
                    <th className="py-2 pr-4">ID</th>
                    <th className="py-2 pr-4">카테고리</th>
                    <th className="py-2 pr-4">owner</th>
                    <th className="py-2 pr-4">doc_type</th>
                    <th className="py-2 pr-4">source</th>
                    <th className="py-2 pr-4">내용</th>
                    <th className="py-2 w-20">삭제</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row) => (
                    <tr key={row.id} className="border-b border-gray-100">
                      <td className="py-2 pr-4 font-mono text-xs">{row.id}</td>
                      <td className="py-2 pr-4">{row.metadata?.category ?? '-'}</td>
                      <td className="py-2 pr-4">{row.metadata?.owner ?? '-'}</td>
                      <td className="py-2 pr-4">{DOC_TYPES.find(t => t.value === row.metadata?.doc_type)?.label ?? row.metadata?.doc_type ?? '-'}</td>
                      <td className="py-2 pr-4">{KNOWLEDGE_SOURCES.find(s => s.value === row.metadata?.source)?.label ?? row.metadata?.source ?? '-'}</td>
                      <td className="py-2 max-w-md truncate" title={row.text}>{row.text}</td>
                      <td className="py-2">
                        <button
                          type="button"
                          onClick={() => handleDelete(row.id)}
                          disabled={deletingId === row.id}
                          className="text-red-600 hover:text-red-800 text-xs disabled:opacity-50"
                        >
                          {deletingId === row.id ? '삭제 중…' : '삭제'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
