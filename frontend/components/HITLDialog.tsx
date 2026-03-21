'use client';

import { useState } from 'react';
import type { HITLRequest } from '@/types';
import { wsClient } from '@/lib/websocket';

interface HITLDialogProps {
  request: HITLRequest;
  onClose: () => void;
  onSubmit?: () => void;
}

export function HITLDialog({ request, onClose, onSubmit }: HITLDialogProps) {
  const [responseText, setResponseText] = useState('');
  const [saveToKB, setSaveToKB] = useState(true);
  const [category, setCategory] = useState('faq');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!responseText.trim()) {
      setError('답변을 입력하세요');
      return;
    }

    setIsSubmitting(true);
    setError('');

    try {
      await wsClient.submitHITLResponse({
        call_id: request.callId,
        response_text: responseText,
        save_to_kb: saveToKB,
        category: saveToKB ? category : undefined,
        question: request.question  // 질문 추가
      });

      // 성공
      if (onSubmit) onSubmit();
      onClose();
    } catch (err: any) {
      setError(err.message || '답변 제출 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-2xl max-w-6xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="bg-orange-600 text-white px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">🆘 AI가 도움을 요청했습니다</h2>
            <p className="text-orange-100 text-sm mt-1">
              통화 상대방은 대기 음악을 듣고 있습니다
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-white hover:bg-orange-700 rounded-full p-2"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 p-6">
          {/* Left: Context */}
          <div className="space-y-4">
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
              <h3 className="font-semibold text-lg mb-2">📞 질문</h3>
              <p className="text-xl">{request.question}</p>
              <div className="mt-2 flex items-center gap-2">
                <span className={`px-2 py-1 rounded text-xs font-semibold ${
                  request.urgency === 'high' ? 'bg-red-100 text-red-800' :
                  request.urgency === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                  'bg-blue-100 text-blue-800'
                }`}>
                  {request.urgency === 'high' ? '긴급' :
                   request.urgency === 'medium' ? '보통' : '낮음'}
                </span>
                <span className="text-xs text-gray-500">
                  {new Date(request.timestamp).toLocaleTimeString('ko-KR')}
                </span>
              </div>
            </div>

            <div>
              <h3 className="font-semibold mb-2">👤 발신자 정보</h3>
              <div className="bg-gray-50 rounded p-3 text-sm">
                <p><strong>URI:</strong> {request.context?.callerInfo?.uri ?? '—'}</p>
                {request.context?.callerInfo?.name && (
                  <p><strong>이름:</strong> {request.context.callerInfo.name}</p>
                )}
              </div>
            </div>

            <div>
              <h3 className="font-semibold mb-2">💬 이전 대화 내역</h3>
              <div className="bg-gray-50 rounded p-3 max-h-48 overflow-y-auto">
                {!(request.context?.previousMessages?.length) ? (
                  <p className="text-gray-500 text-sm">이전 대화 없음</p>
                ) : (
                  <div className="space-y-2 text-sm">
                    {(request.context?.previousMessages ?? []).map((msg: any, idx: number) => (
                      <div key={idx}>
                        <span className="font-semibold">
                          {msg.role === 'user' ? '사용자' : 'AI'}:
                        </span>{' '}
                        {msg.content}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div>
              <h3 className="font-semibold mb-2">🔍 RAG 검색 결과</h3>
              <div className="bg-gray-50 rounded p-3 max-h-48 overflow-y-auto">
                {!(request.context?.ragResults?.length) ? (
                  <p className="text-gray-500 text-sm">검색 결과 없음</p>
                ) : (
                  <div className="space-y-2 text-sm">
                    {(request.context?.ragResults ?? []).map((result: any, idx: number) => (
                      <div key={idx} className="border-l-2 border-blue-400 pl-2">
                        <p>{result.text}</p>
                        <p className="text-xs text-gray-500">
                          유사도: {(result.score * 100).toFixed(1)}%
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right: Response */}
          <div className="space-y-4">
            <div>
              <label className="block font-semibold mb-2">
                💡 답변 작성
                <span className="text-red-500">*</span>
              </label>
              <textarea
                value={responseText}
                onChange={(e) => setResponseText(e.target.value)}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-orange-500 focus:border-transparent"
                placeholder="AI에게 전달할 답변을 작성하세요...&#10;&#10;예: 내일 오후 2시에 본사 3층 회의실에서 미팅이 있습니다."
                rows={10}
              />
              <p className="text-sm text-gray-500 mt-2">
                💡 <strong>Tip:</strong> AI가 자연스럽게 다듬어서 발화합니다. 
                핵심 정보만 간결하게 작성하세요.
              </p>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                {error}
              </div>
            )}

            <div className="border-t pt-4">
              <label className="flex items-center gap-2 mb-3">
                <input
                  type="checkbox"
                  checked={saveToKB}
                  onChange={(e) => setSaveToKB(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="font-semibold">이 답변을 지식 베이스에 저장</span>
              </label>

              {saveToKB && (
                <div>
                  <label className="block text-sm font-medium mb-1">카테고리</label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded"
                  >
                    <option value="faq">FAQ</option>
                    <option value="schedule">일정</option>
                    <option value="policy">정책</option>
                    <option value="contact">연락처</option>
                    <option value="other">기타</option>
                  </select>
                </div>
              )}
            </div>

            <div className="flex gap-3">
              <button
                onClick={handleSubmit}
                disabled={!responseText || isSubmitting}
                className="flex-1 bg-orange-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-orange-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? '전송 중...' : '✅ 전송 (AI가 다듬어서 발화)'}
              </button>
              <button
                onClick={onClose}
                className="px-6 py-3 border border-gray-300 rounded-lg font-semibold hover:bg-gray-50 transition"
              >
                취소
              </button>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm">
              <p className="font-semibold mb-1">⏱️ 응답 시간 가이드</p>
              <ul className="list-disc list-inside space-y-1 text-gray-700">
                <li>목표: 30초 이내</li>
                <li>양호: 30-60초</li>
                <li>주의: 60초 이상</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

