"use client";

import { useCallback, useEffect, useState } from "react";
import { getTenantOwner } from "@/lib/tenant";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface GcalStatus {
  connected: boolean;
  owner: string;
  calendar_id?: string;
  connected_at?: string;
  updated_at?: string;
}

interface SyncResult {
  ok: boolean;
  synced: number;
  failed: number;
  skipped: number;
}

/** 설정 · 일반 설정 — Google OAuth(Calendar) 등 외부 연동 */
export default function GeneralSettingsPage() {
  const owner = getTenantOwner();
  const [gcalStatus, setGcalStatus] = useState<GcalStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/google/oauth/status?owner=${encodeURIComponent(owner)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GcalStatus = await res.json();
      setGcalStatus(data);
    } catch (e: unknown) {
      setError(`연동 상태 조회 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, [owner]);

  useEffect(() => {
    fetchStatus();

    const params = new URLSearchParams(window.location.search);
    if (params.get("gcal_connected") === "1") {
      setSuccessMsg("Google Calendar 연동이 완료되었습니다.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("gcal_error")) {
      setError(`Google OAuth 오류: ${params.get("gcal_error")}`);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [fetchStatus]);

  const handleConnect = () => {
    window.location.href = `${API_BASE}/api/google/oauth/start?owner=${encodeURIComponent(owner)}`;
  };

  const handleDisconnect = async () => {
    if (!confirm("Google Calendar 연동을 해제하시겠습니까?\n기존 이벤트 매핑 정보가 삭제됩니다.")) return;
    setDisconnecting(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/google/oauth/disconnect?owner=${encodeURIComponent(owner)}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSuccessMsg("Google Calendar 연동이 해제되었습니다.");
      await fetchStatus();
    } catch (e: unknown) {
      setError(`연동 해제 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDisconnecting(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setError(null);
    setSyncResult(null);
    setSuccessMsg(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/google/calendar/sync?owner=${encodeURIComponent(owner)}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data: SyncResult = await res.json();
      setSyncResult(data);
      setSuccessMsg(
        `동기화 완료: ${data.synced}건 성공, ${data.failed}건 실패`
      );
    } catch (e: unknown) {
      setError(`동기화 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSyncing(false);
    }
  };

  const formatDate = (s?: string) => {
    if (!s) return "-";
    try {
      return new Date(s).toLocaleString("ko-KR");
    } catch {
      return s;
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-2xl mx-auto space-y-6">
        <div>
          <p className="text-xs font-medium text-indigo-600 uppercase tracking-wide">설정</p>
          <h1 className="text-2xl font-bold text-gray-900 mt-0.5">일반 설정</h1>
          <p className="mt-1 text-sm text-gray-500">
            Google 계정 연동(OAuth) 등 외부 서비스와 연결합니다. 통화 연결음(Suno 생성)은 설정 메뉴의
            전용 화면에서 하고, <strong>착신 제어</strong>의 «통화 연결음» 탭에서 시간 스케줄별로 적용할 음원을 지정합니다.
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 flex items-start gap-2">
            <span className="shrink-0 mt-0.5">⚠️</span>
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 flex items-start gap-2">
            <span className="shrink-0 mt-0.5">✅</span>
            <span>{successMsg}</span>
          </div>
        )}

        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center gap-3 border-b border-gray-100 bg-gray-50 px-6 py-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white border border-gray-200 shadow-sm">
              <svg viewBox="0 0 48 48" className="h-6 w-6" xmlns="http://www.w3.org/2000/svg">
                <rect width="48" height="48" rx="8" fill="#4285F4" />
                <rect x="10" y="10" width="28" height="28" rx="2" fill="white" />
                <rect x="10" y="10" width="28" height="8" rx="2" fill="#4285F4" />
                <text x="24" y="34" textAnchor="middle" fontSize="14" fontWeight="bold" fill="#4285F4">
                  {new Date().getDate()}
                </text>
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-gray-900">Google Calendar</h2>
              <p className="text-xs text-gray-500">예약을 Google Calendar에 자동 동기화 (OAuth 로그인)</p>
            </div>
            <div className="ml-auto">
              {loading ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-500">
                  확인 중…
                </span>
              ) : gcalStatus?.connected ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                  연동됨
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-500">
                  <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
                  미연동
                </span>
              )}
            </div>
          </div>

          <div className="px-6 py-5 space-y-4">
            {gcalStatus?.connected && (
              <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-sm space-y-1.5">
                <div className="flex gap-2">
                  <span className="w-24 shrink-0 text-gray-500">캘린더 ID</span>
                  <span className="font-medium text-gray-800">{gcalStatus.calendar_id || "primary"}</span>
                </div>
                <div className="flex gap-2">
                  <span className="w-24 shrink-0 text-gray-500">연동일</span>
                  <span className="text-gray-700">{formatDate(gcalStatus.connected_at)}</span>
                </div>
                <div className="flex gap-2">
                  <span className="w-24 shrink-0 text-gray-500">마지막 갱신</span>
                  <span className="text-gray-700">{formatDate(gcalStatus.updated_at)}</span>
                </div>
              </div>
            )}

            {!gcalStatus?.connected && (
              <ul className="space-y-1.5 text-sm text-gray-600">
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 text-blue-400">•</span>
                  Google 계정으로 로그인하여 예약을 캘린더에 자동 등록
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 text-blue-400">•</span>
                  예약 생성·변경·취소 시 Google Calendar 실시간 반영
                </li>
                <li className="flex items-start gap-2">
                  <span className="mt-0.5 text-blue-400">•</span>
                  기존 예약 일괄 동기화 지원
                </li>
              </ul>
            )}

            {syncResult && (
              <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-sm">
                <p className="font-medium text-blue-800 mb-1">일괄 동기화 결과</p>
                <div className="flex gap-4 text-blue-700">
                  <span>성공 <strong>{syncResult.synced}</strong>건</span>
                  <span>실패 <strong>{syncResult.failed}</strong>건</span>
                  <span>건너뜀 <strong>{syncResult.skipped}</strong>건</span>
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-3 pt-1">
              {gcalStatus?.connected ? (
                <>
                  <button
                    type="button"
                    onClick={handleSync}
                    disabled={syncing}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {syncing ? (
                      <>
                        <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                        동기화 중…
                      </>
                    ) : (
                      <>🔄 미래 예약 일괄 동기화</>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={handleDisconnect}
                    disabled={disconnecting}
                    className="inline-flex items-center gap-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {disconnecting ? "해제 중…" : "연동 해제"}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={handleConnect}
                  className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 transition-colors"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93V18h2v1.93c-2.63-.47-4.86-2.12-6.03-4.44L8.8 14.5l1.73 1H11v-3H9v1H7.93C7.44 11.41 7 9.76 7 8h2c0 1.45.47 2.79 1.26 3.88L11 10.57V5h2v5.57l.74 1.31C14.53 10.79 15 9.45 15 8h2c0 1.76-.44 3.41-.93 5.5H15v-1h-2v3h1.47l1.73-1 1.83 1.49C15.86 17.88 13.63 19.53 11 20v-2.07z" fill="currentColor" />
                  </svg>
                  Google 계정 연동
                </button>
              )}
            </div>
          </div>

          {!gcalStatus?.connected && (
            <div className="border-t border-gray-100 bg-amber-50 px-6 py-3">
              <p className="text-xs text-amber-700">
                연동 전 <code className="bg-amber-100 px-1 rounded">config/config.yaml</code>의{" "}
                <code className="bg-amber-100 px-1 rounded">google_calendar</code> 또는 환경 변수{" "}
                <code className="bg-amber-100 px-1 rounded">GCAL_CLIENT_ID</code> /{" "}
                <code className="bg-amber-100 px-1 rounded">GCAL_CLIENT_SECRET</code>을 설정하세요.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
