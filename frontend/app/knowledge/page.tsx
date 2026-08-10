'use client';

import { KNOWLEDGE_CATEGORIES, KNOWLEDGE_SOURCES, type KnowledgeItem } from '@/types';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ForwardTargetRow {
  id: string;
  owner: string;
  name: string;
  kind: string;
  single_extension?: string | null;
  members?: string[];
  ring_mode?: string;
}

export default function KnowledgePage() {
  const router = useRouter();
  const [tenant, setTenant] = useState<{ owner: string; name?: string } | null>(null);
  const [text, setText] = useState('');
  const [category, setCategory] = useState('persona');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [filterOwner, setFilterOwner] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterSource, setFilterSource] = useState('');
  const [loadingList, setLoadingList] = useState(false);
  const [groupByCategory, setGroupByCategory] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [sortByHit, setSortByHit] = useState(false);

  const [forwardTargets, setForwardTargets] = useState<ForwardTargetRow[]>([]);
  const [forwardTargetsError, setForwardTargetsError] = useState<string | null>(null);
  const [loadingForwardTargets, setLoadingForwardTargets] = useState(false);
  const [contactManualExt, setContactManualExt] = useState('');
  const [contactSelectedForwardId, setContactSelectedForwardId] = useState('');
  const [contactTransferLabel, setContactTransferLabel] = useState('');

  // Persona 입력 필드 (category === 'persona' 일 때만 표시)
  const [personaName, setPersonaName] = useState('');
  const [personaDescription, setPersonaDescription] = useState('');
  const [personaScopeKeywords, setPersonaScopeKeywords] = useState<string[]>([]);
  const [personaEnabled, setPersonaEnabled] = useState(true);
  const [keywordInput, setKeywordInput] = useState('');
  // 저장된 페르소나 요약 (목록 카드용)
  const [savedPersona, setSavedPersona] = useState<{
    name: string; description: string; scope_keywords: string[];
    enabled: boolean;
  } | null>(null);

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
    if (filterSource) params.set('source', filterSource);
    if (sortByHit) params.set('sort_by', 'hit_count');
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
  }, [filterOwner, filterCategory, filterSource, sortByHit]);

  useEffect(() => {
    if (tenant) {
      fetchList();
      loadPersonaIfExists(tenant.owner);
    }
  }, [tenant, fetchList]);

  // category가 'persona'로 변경되면 기존 데이터 로드
  useEffect(() => {
    if (category === 'persona' && tenant?.owner) {
      loadPersonaIfExists(tenant.owner);
    }
  }, [category, tenant]);

  useEffect(() => {
    if (category !== 'contact' || !tenant?.owner) {
      setForwardTargets([]);
      setForwardTargetsError(null);
      return;
    }
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    let cancelled = false;
    (async () => {
      setLoadingForwardTargets(true);
      setForwardTargetsError(null);
      try {
        const res = await fetch(
          `${API_URL}/api/call-control/forward-targets?owner=${encodeURIComponent(tenant.owner)}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} },
        );
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          const detail = err.detail ?? err.error ?? `HTTP ${res.status}`;
          if (!cancelled) {
            setForwardTargets([]);
            setForwardTargetsError(typeof detail === 'string' ? detail : JSON.stringify(detail));
          }
          return;
        }
        const data = await res.json();
        if (!cancelled) setForwardTargets(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) {
          setForwardTargets([]);
          setForwardTargetsError((e as Error).message || '착신 전환 목록을 불러오지 못했습니다.');
        }
      } finally {
        if (!cancelled) setLoadingForwardTargets(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [category, tenant?.owner]);

  useEffect(() => {
    if (category !== 'contact') {
      setContactManualExt('');
      setContactSelectedForwardId('');
      setContactTransferLabel('');
    }
  }, [category]);

  const loadPersonaIfExists = async (owner: string) => {
    if (!owner) return;
    try {
      const res = await fetch(`${API_URL}/api/persona/${encodeURIComponent(owner)}`);
      if (res.ok) {
        const data = await res.json();
        setPersonaName(data.name || '');
        setPersonaDescription(data.description || '');
        setPersonaScopeKeywords(data.scope_keywords || []);
        setPersonaEnabled(data.enabled ?? true);
        setSavedPersona({
          name: data.name || '',
          description: data.description || '',
          scope_keywords: data.scope_keywords || [],
          enabled: data.enabled ?? true,
        });
      } else {
        setSavedPersona(null);
      }
    } catch (e) {
      console.warn('[knowledge] loadPersona error', e);
      setSavedPersona(null);
    }
  };

  const handleAddKeyword = () => {
    if (!keywordInput.trim()) return;
    const newKeywords = keywordInput.split(',').map(k => k.trim()).filter(Boolean);
    setPersonaScopeKeywords([...personaScopeKeywords, ...newKeywords]);
    setKeywordInput('');
  };

  const handleRemoveKeyword = (index: number) => {
    setPersonaScopeKeywords(personaScopeKeywords.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Persona 저장
    if (category === 'persona') {
      if (!tenant?.owner || !personaName.trim() || !personaDescription.trim()) {
        setMessage({ type: 'error', text: '조직명과 조직 설명은 필수입니다.' });
        return;
      }

      setSubmitting(true);
      setMessage(null);

      try {
        const res = await fetch(`${API_URL}/api/persona/${encodeURIComponent(tenant.owner)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: personaName.trim(),
            description: personaDescription.trim(),
            scope_keywords: personaScopeKeywords,
            enabled: personaEnabled,
          }),
        });

        if (res.ok) {
          setMessage({ type: 'ok', text: '조직 페르소나가 저장되었습니다.' });
          setKeywordInput('');
          await loadPersonaIfExists(tenant.owner);
        } else {
          const err = await res.json().catch(() => ({}));
          setMessage({ type: 'error', text: err.detail || `저장 실패 (HTTP ${res.status})` });
        }
      } catch (err) {
        setMessage({ type: 'error', text: (err as Error).message || '저장 실패' });
      } finally {
        setSubmitting(false);
      }
      return;
    }

    // 일반 지식 저장
    if (!tenant?.owner || !text.trim() || !category) {
      setMessage({ type: 'error', text: '착신(owner), 내용(text), 카테고리(category)를 입력하세요.' });
      return;
    }
    let phone_number = '';
    let transfer_label = '';
    if (category === 'contact') {
      const manual = contactManualExt.trim();
      if (manual) {
        phone_number = manual;
        transfer_label = '';
      } else if (contactSelectedForwardId) {
        phone_number = `fwd:${contactSelectedForwardId}`;
        transfer_label = contactTransferLabel.trim();
      }
      if (!phone_number) {
        setMessage({
          type: 'error',
          text: '연락처(contact): 설정 → 착신 전환 탭에서 등록한 대상을 선택하거나, 직접 내선 번호를 입력하세요.',
        });
        return;
      }
    }
    setSubmitting(true);
    setMessage(null);
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    const postUrl = `${API_URL}/api/knowledge`;
    try {
      const body: Record<string, unknown> = {
        text: text.trim(),
        owner: tenant.owner,
        category,
        source: 'api',
      };
      if (category === 'contact') {
        body.phone_number = phone_number;
        if (transfer_label) body.transfer_label = transfer_label;
      }
      const res = await fetch(postUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.ok) {
        setMessage({ type: 'ok', text: `저장됨 (doc_id: ${data.doc_id}${data.cached ? ', 즉시 캐시됨' : ''})` });
        setText('');
        if (category === 'contact') {
          setContactManualExt('');
          setContactSelectedForwardId('');
          setContactTransferLabel('');
        }
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
    const cat = item.category || item.metadata?.category || 'unknown';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});
  const sortedCategories = Object.keys(itemsByCategory).sort();

  return (
    <div>
      <div className="max-w-4xl mx-auto px-0 py-4">
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-2xl font-bold text-gray-900">고객 지식 베이스</h1>
          <button
            type="button"
            onClick={() => router.push('/knowledge/upload')}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            📄 지식 추가 (TXT 업로드)
          </button>
        </div>
        <p className="text-xs text-amber-700 mb-2">
          ⚠️ 이 화면은 통화·문자 응대용 <strong>고객 지식 베이스</strong>(페르소나/인사말/FAQ)입니다.
          AI 도우미 전용 지식베이스(매뉴얼·업로드 문서)는{' '}
          <Link href="/settings/ai-assistant/docs" className="underline">
            설정 &gt; AI 도우미
          </Link>
          에서 별도로 관리합니다.
        </p>
        <p className="text-gray-600 text-sm mb-6">
          <strong>카테고리</strong>는 질의·인사·연락처 등 업무 구분이고, <strong>doc_type</strong>(knowledge / capability 등)은 서버가 기본값으로 두며
          이 화면에서는 보내지 않습니다. Capability 전용 문서는 별도 API로만 적재됩니다.{' '}
          <strong>내용</strong> 필드 하나로 저장됩니다. 일반 카테고리는 RAG 검색에 쓰이고,
          <strong className="font-medium"> 인사 (시작)·인사 (첫 응답)</strong>은 통화 시작 시 해당 문구를 <strong>LLM 없이 TTS</strong>로 재생합니다
          (카테고리별 최신 1건). <strong className="font-medium">도움말·할 수 있는 일 (help)</strong>은 항목마다 <strong>별도로 한 줄씩</strong> 등록하면,
          사용자가 무엇을 할 수 있는지 물을 때 그 목록으로 안내 멘트가 만들어집니다. <strong className="font-medium">종료 인사</strong>는 대화 중 종료 의도 시{' '}
          <strong>qa_cache</strong>에도 같은 문구로 올라가 빠른 응답에 활용됩니다.
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
                {category === 'persona'
                  ? 'AI가 응대하는 조직의 정체성을 정의합니다. 업무 관련 질문과 잡담을 정확히 분류하는 데 사용됩니다.'
                  : category === 'waiting_phrase'
                    ? 'LLM 처리 중 고객에게 발화되는 대기 안내 멘트입니다. 멘트를 한 줄씩 등록하면 순서대로 순환 발화됩니다. 등록이 없으면 기본 멘트가 사용됩니다.'
                    : category === 'contact'
                      ? '고객이 상담원 연결·전환을 요청할 때(퀵 의도) 발화와 이 문구의 유사도로 매칭됩니다. 전환 대상은 아래에서 «착신 전환»에 등록한 항목(fwd:) 또는 내선 번호로 저장됩니다.'
                      : '질의·FAQ·잡담·불만·전환·연락처는 RAG 후보입니다. 인사(시작)/(첫 응답)은 오프닝 TTS, help는 "뭘 할 수 있어요" 류 질문 시 멘트 구성용입니다.'
                }
              </p>
            </div>

            {category === 'persona' ? (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">조직명 *</label>
                  <input
                    type="text"
                    value={personaName}
                    onChange={(e) => setPersonaName(e.target.value)}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder="예: 기상청"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">조직 설명 및 업무 범위 *</label>
                  <textarea
                    value={personaDescription}
                    onChange={(e) => setPersonaDescription(e.target.value)}
                    rows={3}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder="예: 기상청은 날씨정보와 기상특보를 안내하는 국가 공공기관입니다. 날씨 정보에 대한 응대를 돕습니다."
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">업무 범위 키워드 (선택)</label>
                  <div className="flex gap-2 mb-2">
                    <input
                      type="text"
                      value={keywordInput}
                      onChange={(e) => setKeywordInput(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddKeyword())}
                      className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
                      placeholder="날씨, 예보, 기상, 특보"
                    />
                    <button
                      type="button"
                      onClick={handleAddKeyword}
                      className="px-4 py-2 bg-gray-600 text-white rounded-md text-sm hover:bg-gray-700"
                    >
                      추가
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {personaScopeKeywords.map((kw, idx) => (
                      <span
                        key={idx}
                        className="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm"
                      >
                        {kw}
                        <button
                          type="button"
                          onClick={() => handleRemoveKeyword(idx)}
                          className="text-blue-600 hover:text-blue-900 font-bold"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">업무 관련 키워드 (쉼표로 구분)</p>
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={personaEnabled}
                      onChange={(e) => setPersonaEnabled(e.target.checked)}
                      className="rounded border-gray-300"
                    />
                    <span className="text-sm font-medium text-gray-700">활성화</span>
                  </label>
                </div>
                <p className="text-xs text-gray-600 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
                  SIP MESSAGE(채팅) AI 자동응답은{' '}
                  <Link href="/settings/chat-relay" className="text-indigo-600 hover:text-indigo-800 underline font-medium">
                    설정 → 채팅·SIP MESSAGE
                  </Link>
                  에서 관리합니다.
                </p>
              </>
            ) : (
              <>
                {category === 'contact' && (
                  <div className="rounded-md border border-indigo-100 bg-indigo-50/60 p-4 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-indigo-900">전환 대상 (Call Control)</span>
                      <Link
                        href="/settings/call-control?tab=forward-targets"
                        className="text-sm text-indigo-700 hover:text-indigo-900 underline font-medium"
                      >
                        착신 전환 탭으로 이동
                      </Link>
                    </div>
                    <p className="text-xs text-gray-700 leading-relaxed">
                      먼저 <strong>설정 → 착신 라우팅(Call Control) → «착신 전환»</strong> 탭에서 단일 내선 또는 그룹을 등록한 뒤,
                      여기서 항목을 선택하면 <code className="bg-white/80 px-1 rounded">fwd:…</code> 형태로 저장되어 통화 시 실제 내선으로 해석됩니다.
                      직접 내선만 쓸 경우 아래 번호란에 입력하면 됩니다(선택과 번호란 동시 입력 시 <strong>번호란</strong>이 우선합니다).
                    </p>
                    {forwardTargetsError && (
                      <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
                        착신 전환 목록을 불러오지 못했습니다: {forwardTargetsError}
                      </p>
                    )}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">착신 전환 대상 선택</label>
                      <select
                        value={contactSelectedForwardId}
                        disabled={!!contactManualExt.trim() || loadingForwardTargets}
                        onChange={(e) => {
                          const id = e.target.value;
                          setContactSelectedForwardId(id);
                          setContactManualExt('');
                          if (!id) {
                            setContactTransferLabel('');
                            return;
                          }
                          const row = forwardTargets.find((t) => t.id === id);
                          setContactTransferLabel(row?.name?.trim() || '');
                        }}
                        className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm disabled:bg-gray-100"
                      >
                        <option value="">
                          {loadingForwardTargets ? '불러오는 중…' : '— 선택 —'}
                        </option>
                        {forwardTargets.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name} ({t.kind === 'group' ? '그룹' : '단일'}
                            {t.kind === 'group' ? ` · ${(t.members || []).length}명` : ''})
                          </option>
                        ))}
                      </select>
                      {!loadingForwardTargets && forwardTargets.length === 0 && !forwardTargetsError && (
                        <p className="text-xs text-gray-500 mt-1">
                          등록된 착신 전환 대상이 없습니다. 위 링크에서 추가하세요.
                        </p>
                      )}
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">또는 직접 내선 번호</label>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={contactManualExt}
                        onChange={(e) => {
                          setContactManualExt(e.target.value);
                          if (e.target.value.trim()) {
                            setContactSelectedForwardId('');
                            setContactTransferLabel('');
                          }
                        }}
                        placeholder="예: 1003"
                        className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {category === 'waiting_phrase'
                      ? '대기 안내 멘트 (한 줄) *'
                      : category === 'contact'
                        ? '매칭용 문구 (고객이 말할 내용에 가깝게) *'
                        : '내용 (질문/문구) *'}
                  </label>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={category === 'waiting_phrase' ? 2 : category === 'contact' ? 4 : 3}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder={
                      category === 'waiting_phrase'
                        ? '예: 잠시만 기다려 주세요. / 정보를 확인하고 있습니다.'
                        : category === 'contact'
                          ? '예: 예약 담당 연결해 주세요 / 영업팀으로 바꿔줘 / 상담원이랑 통화하고 싶어요'
                          : '예: 안녕하세요, OO입니다 / 영업시간이 궁금해요'
                    }
                  />
                  {category === 'waiting_phrase' && (
                    <p className="text-xs text-amber-600 mt-1">
                      ⏳ 멘트 한 줄씩 개별 등록하세요. LLM 처리 중 순서대로 순환 발화됩니다.
                    </p>
                  )}
                </div>
              </>
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

        {/* 저장된 페르소나 요약 카드 */}
        {savedPersona && (
          <div className="bg-white rounded-lg shadow p-5 mb-6 border-l-4 border-indigo-400">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-lg">🎭</span>
                <h2 className="text-base font-semibold text-gray-800">{savedPersona.name}</h2>
                {savedPersona.enabled ? (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">활성</span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 font-medium">비활성</span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setCategory('persona')}
                className="shrink-0 text-xs text-indigo-600 hover:text-indigo-800 underline"
              >
                수정
              </button>
            </div>
            <p className="text-sm text-gray-600 mb-2">{savedPersona.description}</p>
            {savedPersona.scope_keywords.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-1">
                {savedPersona.scope_keywords.filter(Boolean).map((kw, i) => (
                  <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-100">{kw}</span>
                ))}
              </div>
            )}
            <p className="text-xs text-gray-500 mt-2">
              SIP MESSAGE AI 자동응답:{' '}
              <Link href="/settings/chat-relay" className="text-indigo-600 hover:text-indigo-800 underline">
                설정에서 관리
              </Link>
            </p>
          </div>
        )}

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
            <label className="flex items-center gap-1.5 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={sortByHit}
                onChange={(e) => setSortByHit(e.target.checked)}
                className="rounded border-gray-300"
              />
              히트수 순 정렬
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
                  <table className="w-full text-sm table-fixed">
                    <colgroup>
                      <col className="w-36" />
                      <col className="w-14" />
                      <col className="w-20" />
                      <col className="w-16" />
                      <col />
                      <col className="w-10" />
                      <col className="w-12" />
                    </colgroup>
                    <thead>
                      <tr className="border-b text-left text-gray-600">
                        <th className="py-2 pr-3">ID</th>
                        <th className="py-2 pr-3">owner</th>
                        <th className="py-2 pr-3">doc_type</th>
                        <th className="py-2 pr-3">source</th>
                        <th className="py-2 pr-3">내용</th>
                        <th className="py-2 text-center">HIT</th>
                        <th className="py-2 text-right">삭제</th>
                      </tr>
                    </thead>
                    <tbody>
                      {itemsByCategory[cat].map((row) => (
                        <tr key={row.id} className="border-b border-gray-100">
                          <td className="py-2 pr-3 font-mono text-xs truncate" title={row.id}>{row.id}</td>
                          <td className="py-2 pr-3 truncate">{row.metadata?.owner ?? '-'}</td>
                          <td className="py-2 pr-3 truncate text-xs text-gray-600" title={row.metadata?.doc_type ?? ''}>{row.metadata?.doc_type ?? '-'}</td>
                          <td className="py-2 pr-3 truncate text-xs text-gray-600">{row.metadata?.source ?? '-'}</td>
                          <td className="py-2 pr-3 truncate" title={row.text}>{row.text}</td>
                          <td className="py-2 text-center">
                            {(row.hit_count ?? 0) > 0 ? (
                              <span className="inline-flex items-center justify-center min-w-[1.5rem] px-1 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold text-xs">
                                {row.hit_count}
                              </span>
                            ) : (
                              <span className="text-gray-300 text-xs">0</span>
                            )}
                          </td>
                          <td className="py-2 text-right">
                            <button
                              type="button"
                              onClick={() => handleDelete(row.id)}
                              disabled={deletingId === row.id}
                              className="text-red-600 hover:text-red-800 text-xs disabled:opacity-50"
                            >
                              {deletingId === row.id ? '…' : '삭제'}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          ) : (
            <table className="w-full text-sm table-fixed">
              <colgroup>
                <col className="w-36" />
                <col className="w-24" />
                <col className="w-14" />
                <col className="w-20" />
                <col className="w-16" />
                <col />
                <col className="w-10" />
                <col className="w-12" />
              </colgroup>
              <thead>
                <tr className="border-b text-left text-gray-600">
                  <th className="py-2 pr-3">ID</th>
                  <th className="py-2 pr-3">카테고리</th>
                  <th className="py-2 pr-3">owner</th>
                  <th className="py-2 pr-3">doc_type</th>
                  <th className="py-2 pr-3">source</th>
                  <th className="py-2 pr-3">내용</th>
                  <th className="py-2 text-center">HIT</th>
                  <th className="py-2 text-right">삭제</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-b border-gray-100">
                    <td className="py-2 pr-3 font-mono text-xs truncate" title={row.id}>{row.id}</td>
                    <td className="py-2 pr-3 truncate text-xs">{categoryLabel(row.category || row.metadata?.category || '')}</td>
                    <td className="py-2 pr-3 truncate">{row.metadata?.owner ?? '-'}</td>
                    <td className="py-2 pr-3 truncate text-xs text-gray-600" title={row.metadata?.doc_type ?? ''}>{row.metadata?.doc_type ?? '-'}</td>
                    <td className="py-2 pr-3 truncate text-xs text-gray-600">{row.metadata?.source ?? '-'}</td>
                    <td className="py-2 pr-3 truncate" title={row.text}>{row.text}</td>
                    <td className="py-2 text-center">
                      {(row.hit_count ?? 0) > 0 ? (
                        <span className="inline-flex items-center justify-center min-w-[1.5rem] px-1 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-semibold text-xs">
                          {row.hit_count}
                        </span>
                      ) : (
                        <span className="text-gray-300 text-xs">0</span>
                      )}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => handleDelete(row.id)}
                        disabled={deletingId === row.id}
                        className="text-red-600 hover:text-red-800 text-xs disabled:opacity-50"
                      >
                        {deletingId === row.id ? '…' : '삭제'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
