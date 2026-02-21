'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function NewOutboundCallPage() {
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({
    caller_number: '',
    callee_number: '',
    caller_display_name: '',
    purpose: '',
    questions: [''],
    max_duration: 180,
    retry_on_no_answer: true,
  });

  const addQuestion = () => {
    setForm({ ...form, questions: [...form.questions, ''] });
  };

  const removeQuestion = (index: number) => {
    if (form.questions.length <= 1) return;
    const updated = form.questions.filter((_, i) => i !== index);
    setForm({ ...form, questions: updated });
  };

  const updateQuestion = (index: number, value: string) => {
    const updated = [...form.questions];
    updated[index] = value;
    setForm({ ...form, questions: updated });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const validQuestions = form.questions.filter((q) => q.trim() !== '');
    if (validQuestions.length === 0) {
      alert('확인 사항을 최소 1개 입력해주세요.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await axios.post(`${API_BASE}/api/outbound/`, {
        caller_number: form.caller_number,
        callee_number: form.callee_number,
        purpose: form.purpose,
        questions: validQuestions,
        caller_display_name: form.caller_display_name || undefined,
        max_duration: form.max_duration || 0,
        retry_on_no_answer: form.retry_on_no_answer,
      });

      alert(`발신 요청이 생성되었습니다. (${res.data.outbound_id})`);
      router.push('/outbound');
    } catch (err: any) {
      const msg = err?.response?.data?.detail || '요청에 실패했습니다.';
      alert(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center gap-4">
            <a href="/outbound" className="text-gray-500 hover:text-gray-700 text-sm">
              &larr; 목록으로
            </a>
            <h1 className="text-xl font-bold text-gray-900">AI 아웃바운드 콜 요청</h1>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow p-6 space-y-6">
          {/* 발신번호 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              발신번호 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={form.caller_number}
              onChange={(e) => setForm({ ...form, caller_number: e.target.value })}
              placeholder="070-1234-5678"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* 착신번호 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              착신번호 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={form.callee_number}
              onChange={(e) => setForm({ ...form, callee_number: e.target.value })}
              placeholder="010-9876-5432"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* 발신자 표시명 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              발신자 표시명
            </label>
            <input
              type="text"
              value={form.caller_display_name}
              onChange={(e) => setForm({ ...form, caller_display_name: e.target.value })}
              placeholder="ABC 주식회사"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">AI가 전화할 때 &quot;{form.caller_display_name || '회사'} AI 비서입니다&quot;로 소개합니다.</p>
          </div>

          {/* 통화 목적 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              통화 목적 <span className="text-red-500">*</span>
            </label>
            <textarea
              required
              rows={2}
              value={form.purpose}
              onChange={(e) => setForm({ ...form, purpose: e.target.value })}
              placeholder="내일 오후 2시 미팅 일정 확인"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {/* 확인 필요 사항 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              확인 필요 사항 <span className="text-red-500">*</span>
            </label>
            <div className="space-y-2">
              {form.questions.map((q, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-sm text-gray-400 w-6 text-right">{i + 1}.</span>
                  <input
                    type="text"
                    value={q}
                    onChange={(e) => updateQuestion(i, e.target.value)}
                    placeholder={`확인 사항 ${i + 1}`}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                  {form.questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeQuestion(i)}
                      className="text-red-400 hover:text-red-600 text-sm px-2"
                    >
                      삭제
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={addQuestion}
              className="mt-2 text-sm text-blue-600 hover:text-blue-800"
            >
              + 항목 추가
            </button>
          </div>

          {/* 고급 설정 */}
          <details className="border-t pt-4">
            <summary className="text-sm font-medium text-gray-600 cursor-pointer">고급 설정</summary>
            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-sm text-gray-600 mb-1">최대 통화 시간 (초)</label>
                <input
                  type="number"
                  min={30}
                  max={1800}
                  value={form.max_duration}
                  onChange={(e) => setForm({ ...form, max_duration: parseInt(e.target.value) || 180 })}
                  className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="retry"
                  checked={form.retry_on_no_answer}
                  onChange={(e) => setForm({ ...form, retry_on_no_answer: e.target.checked })}
                  className="rounded border-gray-300"
                />
                <label htmlFor="retry" className="text-sm text-gray-600">미응답 시 자동 재시도</label>
              </div>
            </div>
          </details>

          {/* 제출 */}
          <div className="flex items-center gap-4 pt-4 border-t">
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition-colors"
            >
              {submitting ? '요청 중...' : '발신 요청'}
            </button>
            <a
              href="/outbound"
              className="px-6 py-2.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              취소
            </a>
          </div>
        </form>
      </main>
    </div>
  );
}
