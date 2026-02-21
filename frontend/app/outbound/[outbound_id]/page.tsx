'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface QuestionAnswer {
  question_id: string;
  question_text: string;
  status: string;
  answer_text: string | null;
  answer_summary: string | null;
  confidence: number;
}

interface TranscriptEntry {
  timestamp: number;
  speaker: string;
  text: string;
}

interface OutboundResult {
  outbound_id: string;
  state: string;
  caller_number: string;
  callee_number: string;
  purpose: string;
  answers: QuestionAnswer[];
  summary: string;
  task_completed: boolean;
  transcript: TranscriptEntry[];
  duration_seconds: number;
  ai_turns: number;
  customer_turns: number;
  created_at: string | null;
  answered_at: string | null;
  completed_at: string | null;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  answered: { label: '답변 완료', color: 'bg-green-100 text-green-800' },
  pending: { label: '미확인', color: 'bg-gray-100 text-gray-800' },
  unclear: { label: '불명확', color: 'bg-yellow-100 text-yellow-800' },
  refused: { label: '거부', color: 'bg-red-100 text-red-800' },
  not_asked: { label: '미질문', color: 'bg-gray-100 text-gray-500' },
};

export default function OutboundResultPage() {
  const params = useParams();
  const outboundId = params?.outbound_id as string;
  const [result, setResult] = useState<OutboundResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!outboundId) return;
    const fetchResult = async () => {
      try {
        const res = await axios.get(`${API_BASE}/api/outbound/${outboundId}/result`);
        setResult(res.data);
      } catch (err: any) {
        setError(err?.response?.data?.detail || '결과를 불러올 수 없습니다.');
      } finally {
        setLoading(false);
      }
    };
    fetchResult();
  }, [outboundId]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500">로딩 중...</p>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-4">{error || '결과를 찾을 수 없습니다.'}</p>
          <a href="/outbound" className="text-blue-600 hover:text-blue-800 text-sm">목록으로</a>
        </div>
      </div>
    );
  }

  const formatTime = (ts: string | null) => {
    if (!ts) return '-';
    return new Date(ts).toLocaleString('ko-KR');
  };

  const formatSeconds = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return m > 0 ? `${m}분 ${s}초` : `${s}초`;
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center gap-4">
            <a href="/outbound" className="text-gray-500 hover:text-gray-700 text-sm">&larr; 목록으로</a>
            <h1 className="text-xl font-bold text-gray-900">통화 결과 상세</h1>
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${result.task_completed ? 'bg-emerald-100 text-emerald-800' : 'bg-yellow-100 text-yellow-800'}`}>
              {result.task_completed ? '태스크 완료' : '부분 완료'}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* 기본 정보 */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">기본 정보</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <p className="text-xs text-gray-500">발신번호</p>
              <p className="text-sm font-medium">{result.caller_number}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">착신번호</p>
              <p className="text-sm font-medium">{result.callee_number}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">통화 시간</p>
              <p className="text-sm font-medium">{formatSeconds(result.duration_seconds)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">요청 시간</p>
              <p className="text-sm">{formatTime(result.created_at)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">연결 시간</p>
              <p className="text-sm">{formatTime(result.answered_at)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">종료 시간</p>
              <p className="text-sm">{formatTime(result.completed_at)}</p>
            </div>
          </div>
          <div className="mt-4">
            <p className="text-xs text-gray-500">통화 목적</p>
            <p className="text-sm text-gray-900">{result.purpose}</p>
          </div>
        </div>

        {/* AI 요약 */}
        {result.summary && (
          <div className="bg-blue-50 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-blue-900 mb-2">AI 요약</h2>
            <p className="text-sm text-blue-800 whitespace-pre-line">{result.summary}</p>
          </div>
        )}

        {/* 확인 사항 결과 */}
        {result.answers.length > 0 && (
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">확인 사항 결과</h2>
            <div className="space-y-4">
              {result.answers.map((a) => {
                const statusInfo = STATUS_LABELS[a.status] || { label: a.status, color: 'bg-gray-100 text-gray-800' };
                return (
                  <div key={a.question_id} className="border rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-gray-900">Q. {a.question_text}</span>
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusInfo.color}`}>
                        {statusInfo.label}
                      </span>
                    </div>
                    {a.answer_text ? (
                      <div className="bg-gray-50 rounded p-3">
                        <p className="text-sm text-gray-700">A. {a.answer_text}</p>
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400 italic">답변 없음</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* 대화록 */}
        {result.transcript.length > 0 && (
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              대화록 ({result.ai_turns}턴 AI / {result.customer_turns}턴 고객)
            </h2>
            <div className="space-y-3">
              {result.transcript.map((entry, idx) => (
                <div key={idx} className={`flex ${entry.speaker === 'ai' ? 'justify-start' : 'justify-end'}`}>
                  <div className={`max-w-[75%] rounded-lg px-4 py-2 ${
                    entry.speaker === 'ai'
                      ? 'bg-blue-50 text-blue-900'
                      : 'bg-gray-100 text-gray-900'
                  }`}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-medium">
                        {entry.speaker === 'ai' ? 'AI' : '고객'}
                      </span>
                      <span className="text-xs text-gray-400">
                        {entry.timestamp > 0 ? `+${entry.timestamp}s` : ''}
                      </span>
                    </div>
                    <p className="text-sm">{entry.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
