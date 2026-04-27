"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";

type ChatRelaySettings = {
  owner: string;
  sip_username: string;
  updated_at: string;
  message_ai_reply_enabled: boolean;
  message_ai_reply_prefix: string;
};

export default function ChatRelaySettingsPage() {
  const [owner, setOwner] = useState("");
  const [updatedAt, setUpdatedAt] = useState("");
  const [messageAiReplyEnabled, setMessageAiReplyEnabled] = useState(false);
  const [messageAiReplyPrefix, setMessageAiReplyPrefix] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    setOwner(getTenantOwner());
  }, []);

  const load = useCallback(async () => {
    if (!owner) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setBanner(null);
    const res = await apiJson<ChatRelaySettings>(`/api/chat/relay?owner=${encodeURIComponent(owner)}`);
    if (!res.ok) {
      setBanner(res.message);
      setUpdatedAt("");
      setMessageAiReplyEnabled(false);
      setMessageAiReplyPrefix("");
    } else {
      const d = res.data;
      setUpdatedAt(d.updated_at || "");
      setMessageAiReplyEnabled(!!d.message_ai_reply_enabled);
      setMessageAiReplyPrefix(typeof d.message_ai_reply_prefix === "string" ? d.message_ai_reply_prefix : "");
    }
    setLoading(false);
  }, [owner]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!owner) return;
    setSaving(true);
    setBanner(null);
    const res = await apiJson<ChatRelaySettings>(`/api/chat/relay?owner=${encodeURIComponent(owner)}`, {
      method: "PUT",
      body: {
        sip_username: "",
        message_ai_reply_enabled: messageAiReplyEnabled,
        message_ai_reply_prefix: messageAiReplyPrefix.trim() ? messageAiReplyPrefix.trim() : null,
      },
    });
    setSaving(false);
    if (!res.ok) {
      setBanner(res.message);
      return;
    }
    const d = res.data;
    setUpdatedAt(d.updated_at || "");
    setMessageAiReplyEnabled(!!d.message_ai_reply_enabled);
    setMessageAiReplyPrefix(typeof d.message_ai_reply_prefix === "string" ? d.message_ai_reply_prefix : "");
    setBanner("저장했습니다.");
  };

  if (!owner) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 max-w-xl mx-auto mt-8">
        로그인 후 테넌트(owner)가 설정되어야 합니다.
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto w-full px-4 py-8 space-y-6">
      <div>
        <Link href="/chat" className="text-sm text-indigo-600 hover:text-indigo-800">
          ← 채팅 관리
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-gray-900">채팅·SIP MESSAGE 설정</h1>
        <p className="mt-2 text-sm text-gray-600">
          <strong>SIP MESSAGE(채팅) AI 자동응답</strong>을 설정합니다. (지식베이스 페르소나가 아닌 이{" "}
          <strong>설정</strong> 메뉴입니다.)
        </p>
      </div>

      {banner && (
        <div
          className={`rounded-lg border px-4 py-2 text-sm ${
            banner === "저장했습니다."
              ? "border-green-200 bg-green-50 text-green-900"
              : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {banner}
        </div>
      )}

      <div className="rounded-xl border border-amber-100 bg-amber-50/50 p-6 space-y-4 shadow-sm">
        <h2 className="text-base font-semibold text-amber-950">SIP MESSAGE(채팅) AI 자동응답</h2>
        <p className="text-xs text-gray-700 leading-relaxed">
          착신 내선으로 들어오는 SIP 텍스트 메시지에 대해 LangGraph 에이전트로 자동 답장합니다. 답장 앞에는 접두어가 붙으며,
          PBX는 루프 방지용 헤더를 사용합니다.
        </p>
        {loading ? (
          <p className="text-sm text-gray-500">불러오는 중…</p>
        ) : (
          <div className="space-y-3">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={messageAiReplyEnabled}
                onChange={(e) => setMessageAiReplyEnabled(e.target.checked)}
                className="rounded border-gray-300"
              />
              <span className="text-sm font-medium text-gray-800">SIP MESSAGE 수신 시 AI 자동응답 사용</span>
            </label>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">자동응답 표시 접두 (선택)</label>
              <input
                type="text"
                value={messageAiReplyPrefix}
                onChange={(e) => setMessageAiReplyPrefix(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="비우면 기본: [AI 자동응답]"
                disabled={!messageAiReplyEnabled}
              />
              <p className="text-xs text-gray-500 mt-1">
                자동응답이 켜져 있을 때만 적용됩니다. 비어 있으면 서버 기본 접두가 사용됩니다.
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white px-6 py-4 shadow-sm flex flex-wrap items-center justify-between gap-3">
        {updatedAt ? <p className="text-xs text-gray-500">마지막 저장: {updatedAt}</p> : <span />}
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || loading}
          className="px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? "저장 중…" : "저장"}
        </button>
      </div>
    </div>
  );
}
