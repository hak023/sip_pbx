'use client';

import { useState, useEffect } from 'react';
import { KnowledgeStats } from '@/types/knowledge';

interface StatsTabProps {
  tenantId: string;
}

export default function StatsTab({ tenantId }: StatsTabProps) {
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    fetchStats();
  }, [tenantId]);

  const fetchStats = async () => {
    try {
      setLoading(true);
      const ownerFilter = `sip:${tenantId}@unknown`;
      const response = await fetch(
        `http://localhost:8000/api/knowledge/stats?tenant_id=${encodeURIComponent(ownerFilter)}`
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch stats');
      }
      
      const data = await response.json();
      setStats(data);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-center text-gray-500">로딩 중...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="p-4 bg-red-100 border border-red-400 text-red-700 rounded-lg">
          {error}
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-center text-gray-500">통계 정보를 불러올 수 없습니다.</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 전체 통계 카드 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">총 지식</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats.total_knowledge.toLocaleString()}
          </div>
          <div className="text-xs text-gray-400 mt-1">개</div>
        </div>
        
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">이번 주 추가</div>
          <div className="text-3xl font-bold text-blue-600">
            +{stats.this_week.toLocaleString()}
          </div>
          <div className="text-xs text-gray-400 mt-1">개</div>
        </div>
        
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-sm text-gray-500 mb-2">평균 신뢰도</div>
          <div className="text-3xl font-bold text-green-600">
            {(stats.avg_confidence * 100).toFixed(0)}%
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {stats.total_knowledge > 0 ? '정확도' : 'N/A'}
          </div>
        </div>
      </div>

      {/* 카테고리별 분포 */}
      {Object.keys(stats.categories).length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h3 className="text-lg font-bold mb-4">카테고리별 분포</h3>
          <div className="space-y-3">
            {Object.entries(stats.categories)
              .sort((a, b) => b[1] - a[1])
              .map(([category, count]) => (
                <div key={category} className="flex items-center gap-4">
                  <div className="w-24 text-sm text-gray-600 truncate" title={category}>
                    {category}
                  </div>
                  <div className="flex-1 bg-gray-200 rounded-full h-6 relative overflow-hidden">
                    <div
                      className="bg-blue-500 h-6 rounded-full transition-all duration-300"
                      style={{
                        width: `${Math.max(5, (count / stats.total_knowledge) * 100)}%`
                      }}
                    />
                    <span className="absolute inset-0 flex items-center justify-center text-xs font-medium text-gray-700">
                      {count}개 ({((count / stats.total_knowledge) * 100).toFixed(1)}%)
                    </span>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* 최근 추출 내역 */}
      {stats.recent_extractions.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h3 className="text-lg font-bold mb-4">최근 지식 추출</h3>
          <div className="space-y-2">
            {stats.recent_extractions.map((extraction, idx) => (
              <div key={idx} className="flex justify-between items-center py-3 border-b last:border-b-0">
                <div>
                  <span className="text-sm font-medium text-gray-900">
                    통화 {extraction.call_id.substring(0, 8)}...
                  </span>
                  <span className="ml-3 text-sm text-gray-500">
                    {extraction.extracted_count}개 추출
                  </span>
                </div>
                <span className="text-sm text-gray-500">
                  {extraction.timestamp 
                    ? new Date(extraction.timestamp).toLocaleDateString('ko-KR', {
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      })
                    : 'N/A'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 데이터 없음 */}
      {stats.total_knowledge === 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <div className="text-center text-gray-500 py-8">
            아직 저장된 지식이 없습니다.<br />
            통화를 진행하면 자동으로 지식이 추출됩니다.
          </div>
        </div>
      )}
    </div>
  );
}
