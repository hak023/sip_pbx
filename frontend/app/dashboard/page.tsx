'use client';

import { useState, useEffect } from 'react';
import { useWebSocket, useHITL } from '@/hooks/useWebSocket';
import { LiveCallMonitor } from '@/components/LiveCallMonitor';
import { HITLDialog } from '@/components/HITLDialog';
import { OperatorStatusToggle } from '@/components/OperatorStatusToggle';
import type { DashboardMetrics, ActiveCall, HITLRequest } from '@/types';

export default function DashboardPage() {
  const { isConnected } = useWebSocket();
  const { requests: hitlRequests, clearRequest } = useHITL();
  
  const [metrics, setMetrics] = useState<DashboardMetrics>({
    activeCalls: 0,
    hitlQueueSize: 0,
    avgAIConfidence: 0,
    todayCallsCount: 0,
    avgResponseTime: 0,
    knowledgeBaseSize: 0,
  });

  const [activeCalls, setActiveCalls] = useState<ActiveCall[]>([]);
  const [selectedCall, setSelectedCall] = useState<string | null>(null);
  const [selectedHITL, setSelectedHITL] = useState<HITLRequest | null>(null);

  // Mock 데이터 로드 (추후 API 연동)
  useEffect(() => {
    setMetrics({
      activeCalls: 3,
      hitlQueueSize: hitlRequests.length,
      avgAIConfidence: 85,
      todayCallsCount: 42,
      avgResponseTime: 0.9,
      knowledgeBaseSize: 156,
    });
  }, [hitlRequests]);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-900">
              🤖 AI Voicebot Control Center
            </h1>
            <div className="flex items-center gap-2">
              <span className={`flex items-center gap-2 px-3 py-1 rounded-full text-sm ${
                isConnected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
              }`}>
                <span className={`w-2 h-2 rounded-full ${
                  isConnected ? 'bg-green-600 animate-pulse' : 'bg-red-600'
                }`} />
                {isConnected ? 'WebSocket 연결됨' : 'WebSocket 연결 안됨'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Operator Status Toggle (신규) */}
        <div className="grid grid-cols-12 gap-6 mb-8">
          <OperatorStatusToggle />
        </div>

        {/* Metrics Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <MetricCard
            title="활성 통화"
            value={metrics.activeCalls}
            icon="📞"
            color="blue"
          />
          <MetricCard
            title="HITL 대기"
            value={hitlRequests.length}
            icon="🆘"
            color="orange"
            urgent={hitlRequests.length > 0}
          />
          <MetricCard
            title="AI 신뢰도"
            value={`${metrics.avgAIConfidence}%`}
            icon="🎯"
            color="green"
          />
          <MetricCard
            title="오늘 통화"
            value={metrics.todayCallsCount}
            icon="📊"
            color="purple"
          />
        </div>

        {/* Active Calls & HITL Queue */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Active Calls List */}
          <div className="lg:col-span-2 bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4">실시간 통화</h2>
            {activeCalls.length === 0 ? (
              <p className="text-gray-500 text-center py-8">
                현재 활성 통화가 없습니다
              </p>
            ) : (
              <div className="space-y-4">
                {activeCalls.map((call) => (
                  <div
                    key={call.callId}
                    className="border rounded-lg p-4 hover:bg-gray-50 cursor-pointer"
                    onClick={() => setSelectedCall(call.callId)}
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <p className="font-semibold">{call.caller.name || call.caller.uri}</p>
                        <p className="text-sm text-gray-500">→ {call.callee.name || call.callee.uri}</p>
                      </div>
                      <span className={`px-3 py-1 rounded-full text-sm ${
                        call.isAIHandled ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'
                      }`}>
                        {call.isAIHandled ? 'AI 응대' : '일반'}
                      </span>
                    </div>
                    <div className="mt-2 text-sm text-gray-600">
                      통화 시간: {Math.floor(call.duration / 60)}분 {call.duration % 60}초
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* HITL Queue */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold mb-4 text-orange-600">
              🆘 도움 요청
            </h2>
            {hitlRequests.length === 0 ? (
              <p className="text-gray-500 text-center py-8">
                대기 중인 요청이 없습니다
              </p>
            ) : (
              <div className="space-y-4">
                {hitlRequests.map((request) => (
                  <div
                    key={request.callId}
                    className="border-l-4 border-orange-500 bg-orange-50 p-4 rounded animate-pulse-slow"
                  >
                    <p className="font-semibold text-sm">{request.question}</p>
                    <p className="text-xs text-gray-600 mt-2">
                      {request.context.callerInfo.name || request.context.callerInfo.uri}
                    </p>
                    <button
                      onClick={() => setSelectedHITL(request)}
                      className="mt-3 w-full bg-orange-600 text-white px-4 py-2 rounded hover:bg-orange-700 text-sm font-semibold transition"
                    >
                      답변하기
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Live Call Monitor (if selected) */}
        {selectedCall && (
          <div className="mb-8">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">통화 모니터</h2>
              <button
                onClick={() => setSelectedCall(null)}
                className="text-gray-500 hover:text-gray-700"
              >
                닫기 ✕
              </button>
            </div>
            <LiveCallMonitor callId={selectedCall} />
          </div>
        )}

        {/* Quick Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">평균 응답 시간</h3>
            <p className="text-3xl font-bold text-blue-600">{metrics.avgResponseTime}초</p>
            <p className="text-sm text-gray-500 mt-1">STT → TTS 전체 시간</p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">지식 베이스</h3>
            <p className="text-3xl font-bold text-green-600">{metrics.knowledgeBaseSize}</p>
            <p className="text-sm text-gray-500 mt-1">저장된 항목 수</p>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold mb-2">시스템 상태</h3>
            <p className={`text-3xl font-bold ${isConnected ? 'text-green-600' : 'text-red-600'}`}>
              {isConnected ? '정상' : '오류'}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              {isConnected ? '모든 서비스 작동 중' : 'WebSocket 연결 필요'}
            </p>
          </div>
        </div>
      </main>

      {/* HITL Dialog */}
      {selectedHITL && (
        <HITLDialog
          request={selectedHITL}
          onClose={() => setSelectedHITL(null)}
          onSubmit={() => {
            clearRequest(selectedHITL.callId);
            setSelectedHITL(null);
          }}
        />
      )}
    </div>
  );
}

interface MetricCardProps {
  title: string;
  value: number | string;
  icon: string;
  color: 'blue' | 'orange' | 'green' | 'purple';
  urgent?: boolean;
}

function MetricCard({ title, value, icon, color, urgent }: MetricCardProps) {
  const colorClasses = {
    blue: 'bg-blue-50 text-blue-600',
    orange: urgent ? 'bg-orange-50 text-orange-600 animate-pulse' : 'bg-orange-50 text-orange-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
  };

  return (
    <div className={`${colorClasses[color]} rounded-lg shadow p-6`}>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium opacity-80">{title}</p>
          <p className="text-3xl font-bold mt-2">{value}</p>
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  );
}
