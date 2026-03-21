'use client';

import { useState, useEffect } from 'react';
import { Knowledge } from '@/types/knowledge';

interface KnowledgeListTabProps {
  tenantId: string;
}

export default function KnowledgeListTab({ tenantId }: KnowledgeListTabProps) {
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const limit = 20;

  useEffect(() => {
    fetchKnowledge();
  }, [tenantId, page]);

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const fetchKnowledge = async () => {
    try {
      setLoading(true);
      const ownerFilter = `sip:${tenantId}@unknown`;
      const response = await fetch(
        `${API_URL}/api/knowledge?tenant_id=${encodeURIComponent(ownerFilter)}&page=${page}&limit=${limit}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch knowledge');
      }
      
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      const totalCount = typeof data.total === 'number' ? data.total : 0;
      setKnowledge(items);
      setTotal(totalCount);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      setKnowledge([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      fetchKnowledge();
      return;
    }

    try {
      setLoading(true);
      const ownerFilter = `sip:${tenantId}@unknown`;
      const response = await fetch(`${API_URL}/api/knowledge/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tenant_id: ownerFilter,
          query: searchQuery,
          top_k: 20
        })
      });

      if (!response.ok) {
        throw new Error('Failed to search knowledge');
      }

      const data = await response.json();
      const searchResults: Knowledge[] = data.results.map((r: any) => ({
        id: r.id,
        text: r.text,
        category: r.category,
        keywords: [],
        confidence: r.metadata?.confidence || 0,
        call_id: r.metadata?.call_id || '',
        created_at: '',
        owner: tenantId
      }));
      
      setKnowledge(searchResults);
      setTotal(searchResults.length);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  const totalPages = Math.ceil(total / limit);

  if (loading && knowledge.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-center text-gray-500">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      {/* 검색 바 */}
      <div className="mb-6">
        <div className="flex gap-4">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="지식 검색..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
          <button
            onClick={handleSearch}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            검색
          </button>
          {searchQuery && (
            <button
              onClick={() => {
                setSearchQuery('');
                setPage(1);
                fetchKnowledge();
              }}
              className="px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 transition-colors"
            >
              초기화
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded-lg">
          {error}
        </div>
      )}

      {/* 지식 목록 */}
      {knowledge.length === 0 ? (
        <div className="text-center py-8 space-y-3">
          <p className="text-gray-700 font-medium">저장된 지식이 없습니다.</p>
          <p className="text-sm text-gray-500">
            API에서 총 <strong>{total}</strong>건을 반환했습니다. (테넌트: {tenantId})
          </p>
          {total === 0 && (
            <p className="text-xs text-gray-400 max-w-md mx-auto">
              데이터가 없거나, 해당 테넌트(owner)로 저장된 지식이 없을 수 있습니다. 통화 후 지식 추출이 되거나, POST /api/knowledge 로 추가할 수 있습니다.
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="mb-4 text-sm text-gray-600">
            총 {total.toLocaleString()}개의 지식
          </div>
          
          <div className="space-y-4">
            {knowledge.map((item) => (
              <div key={item.id} className="border rounded-lg p-4 hover:bg-gray-50 transition-colors">
                <div className="flex justify-between items-start mb-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                      {item.category}
                    </span>
                    <span className="text-sm text-gray-500">
                      신뢰도: {(item.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {item.created_at && (
                    <span className="text-sm text-gray-500">
                      {new Date(item.created_at).toLocaleDateString('ko-KR')}
                    </span>
                  )}
                </div>
                
                <p className="text-gray-800 mb-2">{item.text}</p>
                
                <div className="flex items-center gap-4 text-xs text-gray-500">
                  {item.call_id && (
                    <span>통화 ID: {item.call_id.substring(0, 8)}...</span>
                  )}
                  {item.keywords && item.keywords.length > 0 && (
                    <div className="flex gap-2">
                      {item.keywords.map((kw, idx) => (
                        <span key={idx} className="text-blue-600">
                          #{kw}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* 페이지네이션 */}
          {!searchQuery && totalPages > 1 && (
            <div className="mt-6 flex justify-center items-center gap-2">
              <button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page === 1}
                className="px-4 py-2 border border-gray-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                이전
              </button>
              
              <div className="flex gap-1">
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum = i + 1;
                  if (totalPages > 5 && page > 3) {
                    pageNum = page - 2 + i;
                    if (pageNum > totalPages) pageNum = totalPages - (4 - i);
                  }
                  
                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`px-3 py-2 border rounded-lg ${
                        page === pageNum
                          ? 'bg-blue-600 text-white border-blue-600'
                          : 'border-gray-300 hover:bg-gray-50'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
              </div>
              
              <button
                onClick={() => setPage(Math.min(totalPages, page + 1))}
                disabled={page === totalPages}
                className="px-4 py-2 border border-gray-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
              >
                다음
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
