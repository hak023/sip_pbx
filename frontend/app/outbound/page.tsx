"use client";

import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";

interface OutboundCall {
  outbound_id: string;
  call_id?: string;
  caller_number: string;
  callee_number: string;
  purpose: string;
  questions: string[];
  state: string;
  started_at?: string;
  answered_at?: string;
  completed_at?: string;
  attempt_count: number;
  failure_reason?: string;
}

interface OutboundStats {
  total_calls: number;
  completed_count: number;
  task_completed_count: number;
  success_rate: number;
  avg_duration_seconds: number;
  no_answer_count: number;
  busy_count: number;
  active_count: number;
  queue_size: number;
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("ko-KR", {
      dateStyle: "short",
      timeStyle: "medium",
    });
  } catch {
    return iso;
  }
}

function StateBadge({ state }: { state: string }) {
  const color =
    state === "completed"
      ? "bg-green-100 text-green-800"
      : state === "connected"
        ? "bg-blue-100 text-blue-800"
        : state === "ringing"
          ? "bg-purple-100 text-purple-800"
          : state === "dialing"
            ? "bg-indigo-100 text-indigo-800"
            : state === "failed" || state === "rejected"
              ? "bg-red-100 text-red-800"
              : state === "no_answer"
                ? "bg-amber-100 text-amber-800"
                : state === "busy"
                  ? "bg-orange-100 text-orange-800"
                  : state === "cancelled"
                    ? "bg-gray-100 text-gray-800"
                    : "bg-slate-100 text-slate-700";

  const label =
    state === "completed"
      ? "완료"
      : state === "connected"
        ? "통화 중"
        : state === "ringing"
          ? "벨 울리는 중"
          : state === "dialing"
            ? "발신 중"
            : state === "failed"
              ? "실패"
              : state === "rejected"
                ? "거절됨"
                : state === "no_answer"
                  ? "무응답"
                  : state === "busy"
                    ? "통화중"
                    : state === "cancelled"
                      ? "취소됨"
                      : state;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}
    >
      {label}
    </span>
  );
}

export default function OutboundPage() {
  const [activeCalls, setActiveCalls] = useState<OutboundCall[]>([]);
  const [history, setHistory] = useState<OutboundCall[]>([]);
  const [stats, setStats] = useState<OutboundStats | null>(null);
  const [loading, setLoading] = useState(false);

  const [callerNumber, setCallerNumber] = useState("1000");
  const [calleeNumber, setCalleeNumber] = useState("");
  const [purpose, setPurpose] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);
  const [displayName, setDisplayName] = useState("AI 비서");
  const [maxDuration, setMaxDuration] = useState(300);
  const [retryOnNoAnswer, setRetryOnNoAnswer] = useState(true);

  const [creating, setCreating] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [activeRes, historyRes, statsRes] = await Promise.all([
        apiJson<{ items: OutboundCall[] }>("/api/outbound/active", { method: "GET" }),
        apiJson<{ items: OutboundCall[] }>("/api/outbound/history?limit=50", { method: "GET" }),
        apiJson<OutboundStats>("/api/outbound/stats", { method: "GET" }),
      ]);

      if (activeRes.ok) setActiveCalls(activeRes.data?.items || []);
      if (historyRes.ok) setHistory(historyRes.data?.items || []);
      if (statsRes.ok) setStats(statsRes.data || null);
    } catch (e) {
      console.error("[outbound] fetchData error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleCreate = async () => {
    if (!calleeNumber.trim()) {
      alert("착신번호를 입력하세요.");
      return;
    }
    if (!purpose.trim()) {
      alert("통화 목적을 입력하세요.");
      return;
    }

    const filteredQuestions = questions.filter((q) => q.trim());
    if (filteredQuestions.length === 0) {
      alert("최소 1개 이상의 질문을 입력하세요.");
      return;
    }

    setCreating(true);
    try {
      const res = await apiJson<{ success: boolean; outbound_id: string; message: string }>(
        "/api/outbound/create",
        {
          method: "POST",
          body: {
            caller_number: callerNumber,
            callee_number: calleeNumber,
            purpose,
            questions: filteredQuestions,
            caller_display_name: displayName,
            max_duration: maxDuration,
            retry_on_no_answer: retryOnNoAnswer,
          },
        }
      );

      if (res.ok && res.data) {
        alert(`아웃바운드 콜이 생성되었습니다.\nID: ${res.data.outbound_id}`);
        setCalleeNumber("");
        setPurpose("");
        setQuestions([""]);
        fetchData();
      } else {
        alert(`생성 실패: ${res.error || "알 수 없는 오류"}`);
      }
    } catch (e: any) {
      alert(`생성 실패: ${e?.message || e}`);
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async (outboundId: string) => {
    if (!window.confirm("이 아웃바운드 콜을 취소하시겠습니까?")) return;

    try {
      const res = await apiJson<{ success: boolean; message: string }>(
        "/api/outbound/cancel",
        {
          method: "POST",
          body: { outbound_id: outboundId, reason: "operator_cancel" },
        }
      );

      if (res.ok) {
        alert("취소되었습니다.");
        fetchData();
      } else {
        alert(`취소 실패: ${res.error}`);
      }
    } catch (e: any) {
      alert(`취소 실패: ${e?.message || e}`);
    }
  };

  const handleRetry = async (outboundId: string) => {
    if (!window.confirm("이 아웃바운드 콜을 재시도하시겠습니까?")) return;

    try {
      const res = await apiJson<{ success: boolean; new_outbound_id: string; message: string }>(
        "/api/outbound/retry",
        {
          method: "POST",
          body: { outbound_id: outboundId },
        }
      );

      if (res.ok && res.data) {
        alert(`재시도가 시작되었습니다.\n새 ID: ${res.data.new_outbound_id}`);
        fetchData();
      } else {
        alert(`재시도 실패: ${res.error}`);
      }
    } catch (e: any) {
      alert(`재시도 실패: ${e?.message || e}`);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold text-gray-900">아웃바운드 콜 관리</h1>
          <a
            href="/dashboard"
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            대시보드로 돌아가기
          </a>
        </div>

        {/* 통계 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">총 콜 수</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{stats.total_calls}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">완료율</p>
              <p className="text-2xl font-bold text-green-600 mt-1">
                {Math.round(stats.success_rate * 100)}%
              </p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">활성 콜</p>
              <p className="text-2xl font-bold text-blue-600 mt-1">{stats.active_count}</p>
            </div>
            <div className="bg-white p-4 rounded-lg shadow">
              <p className="text-xs text-gray-500 uppercase tracking-wide">대기열</p>
              <p className="text-2xl font-bold text-purple-600 mt-1">{stats.queue_size}</p>
            </div>
          </div>
        )}

        {/* 콜 생성 폼 */}
        <div className="bg-white p-6 rounded-lg shadow mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">새 아웃바운드 콜 생성</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                발신번호 (AI 봇)
              </label>
              <input
                type="text"
                value={callerNumber}
                onChange={(e) => setCallerNumber(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="1000"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                착신번호 (고객) <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={calleeNumber}
                onChange={(e) => setCalleeNumber(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="01012345678"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                발신자 표시 이름
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="AI 비서"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                최대 통화 시간 (초)
              </label>
              <input
                type="number"
                value={maxDuration}
                onChange={(e) => setMaxDuration(Number(e.target.value))}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                min={30}
                max={1800}
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                통화 목적 <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="예: 서비스 만족도 조사"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                질문 목록 <span className="text-red-500">*</span>
              </label>
              {questions.map((q, idx) => (
                <div key={idx} className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={q}
                    onChange={(e) => {
                      const next = [...questions];
                      next[idx] = e.target.value;
                      setQuestions(next);
                    }}
                    className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder={`질문 ${idx + 1}`}
                  />
                  {questions.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setQuestions(questions.filter((_, i) => i !== idx))}
                      className="px-3 py-2 text-sm text-red-600 border border-red-300 rounded-md hover:bg-red-50"
                    >
                      삭제
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={() => setQuestions([...questions, ""])}
                className="px-3 py-2 text-sm text-indigo-600 border border-indigo-300 rounded-md hover:bg-indigo-50"
              >
                + 질문 추가
              </button>
            </div>
            <div className="md:col-span-2">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={retryOnNoAnswer}
                  onChange={(e) => setRetryOnNoAnswer(e.target.checked)}
                  className="rounded"
                />
                무응답 시 자동 재시도
              </label>
            </div>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating}
            className={`mt-4 w-full px-4 py-3 rounded-md text-sm font-semibold text-white transition-colors ${
              creating
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {creating ? "생성 중..." : "아웃바운드 콜 생성"}
          </button>
        </div>

        {/* 활성 콜 */}
        <section className="mb-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            활성 콜 ({activeCalls.length}건)
          </h2>
          {activeCalls.length === 0 ? (
            <div className="bg-white p-6 rounded-lg shadow text-center text-gray-500">
              활성 아웃바운드 콜이 없습니다.
            </div>
          ) : (
            <div className="space-y-3">
              {activeCalls.map((call) => (
                <div
                  key={call.outbound_id}
                  className="bg-white p-4 rounded-lg shadow border border-gray-200 hover:border-indigo-300"
                >
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      <p className="font-mono text-xs text-gray-500">{call.outbound_id}</p>
                      <p className="text-sm font-semibold text-gray-900 mt-1">
                        {call.caller_number} → {call.callee_number}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-2">
                      <StateBadge state={call.state} />
                      <button
                        type="button"
                        onClick={() => handleCancel(call.outbound_id)}
                        className="px-3 py-1 text-xs text-red-600 border border-red-300 rounded hover:bg-red-50"
                      >
                        취소
                      </button>
                    </div>
                  </div>
                  <div className="text-sm text-gray-700">
                    <p>
                      <span className="font-medium">목적:</span> {call.purpose}
                    </p>
                    <p>
                      <span className="font-medium">시작:</span> {formatDateTime(call.started_at)}
                    </p>
                    {call.answered_at && (
                      <p>
                        <span className="font-medium">응답:</span> {formatDateTime(call.answered_at)}
                      </p>
                    )}
                    {call.failure_reason && (
                      <p className="text-red-600">
                        <span className="font-medium">실패 사유:</span> {call.failure_reason}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 콜 이력 */}
        <section>
          <h2 className="text-lg font-semibold text-gray-900 mb-3">
            콜 이력 (최근 {history.length}건)
          </h2>
          {history.length === 0 ? (
            <div className="bg-white p-6 rounded-lg shadow text-center text-gray-500">
              아웃바운드 콜 이력이 없습니다.
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      ID
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      착신번호
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      목적
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      상태
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      시작 시간
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      완료 시간
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      액션
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {history.map((call) => (
                    <tr key={call.outbound_id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-xs font-mono text-gray-700">
                        {call.outbound_id.slice(0, 12)}...
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">{call.callee_number}</td>
                      <td className="px-4 py-3 text-sm text-gray-700 max-w-xs truncate">
                        {call.purpose}
                      </td>
                      <td className="px-4 py-3">
                        <StateBadge state={call.state} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {formatDateTime(call.started_at)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {formatDateTime(call.completed_at)}
                      </td>
                      <td className="px-4 py-3">
                        {call.state === "no_answer" ||
                        call.state === "busy" ||
                        call.state === "failed" ||
                        call.state === "rejected" ? (
                          <button
                            type="button"
                            onClick={() => handleRetry(call.outbound_id)}
                            className="px-3 py-1 text-xs text-indigo-600 border border-indigo-300 rounded hover:bg-indigo-50"
                          >
                            재시도
                          </button>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
