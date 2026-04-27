"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiJson } from "@/lib/api";
import { getTenantOwner } from "@/lib/tenant";
import { useWebSocket } from "@/hooks/useWebSocket";
import { wsClient } from "@/lib/websocket";

type ChatThread = {
  thread_id: string;
  owner: string;
  last_time?: string;
  message_count?: number;
  inbound_count?: number;
  last_body?: string;
  last_direction?: string;
};

type ChatMessageRow = {
  id: number;
  thread_id: string;
  owner: string;
  direction: string;
  from_phone: string;
  to_phone: string;
  body: string;
  status: string;
  error_code?: string;
  created_at: string;
};

type SendResponse = {
  success: boolean;
  to_phone: string;
  body: string;
  message_id: number;
  error_code?: string;
  detail?: string;
};

/** SIP From/Request-URI 등에서 내선만 뽑아 스레드 id 와 비교 */
function normPeer(u: string | undefined | null): string {
  const s = (u || "").trim();
  if (!s) return "";
  const noScheme = s.replace(/^sip:/i, "").replace(/^sips:/i, "");
  return noScheme.split("@")[0].replace(/[<>"]/g, "").trim();
}

export default function ChatManagementPage() {
  useWebSocket();
  const [owner, setOwner] = useState("");
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [selectedThreadId, setSelectedThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageRow[]>([]);
  const [inputBody, setInputBody] = useState("");
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [retryingId, setRetryingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roomModalOpen, setRoomModalOpen] = useState(false);
  const [newPeerInput, setNewPeerInput] = useState("");
  const selectedThreadIdRef = useRef<string | null>(null);

  useEffect(() => {
    setOwner(getTenantOwner());
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !owner) return;
    const thread = new URLSearchParams(window.location.search).get("thread")?.trim();
    if (thread) setSelectedThreadId(thread);
  }, [owner]);

  useEffect(() => {
    selectedThreadIdRef.current = selectedThreadId;
  }, [selectedThreadId]);

  const loadThreads = useCallback(async () => {
    if (!owner) {
      setThreads([]);
      return;
    }
    setLoadingThreads(true);
    setError(null);
    const res = await apiJson<ChatThread[]>(`/api/chat/threads?owner=${encodeURIComponent(owner)}`);
    if (!res.ok) {
      setError(res.message);
      setThreads([]);
    } else {
      setThreads(res.data);
    }
    setLoadingThreads(false);
  }, [owner]);

  const loadMessages = useCallback(async () => {
    if (!owner || !selectedThreadId) {
      setMessages([]);
      return;
    }
    setLoadingMessages(true);
    setError(null);
    const res = await apiJson<ChatMessageRow[]>(
      `/api/chat/messages?thread_id=${encodeURIComponent(selectedThreadId)}&owner=${encodeURIComponent(owner)}`
    );
    if (!res.ok) {
      setError(res.message);
      setMessages([]);
    } else {
      setMessages(res.data);
    }
    setLoadingMessages(false);
  }, [owner, selectedThreadId]);

  useEffect(() => {
    void loadThreads();
  }, [loadThreads]);

  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  useEffect(() => {
    if (!owner) return;
    const onSipMessage = (data: {
      from_uri?: string;
      to_user?: string;
      body?: string;
      call_id?: string;
    }) => {
      void loadThreads();
      const sel = selectedThreadIdRef.current;
      if (!sel) return;
      const fp = normPeer(data.from_uri);
      const tp = normPeer(data.to_user);
      const sn = normPeer(sel);
      if (fp === sn || tp === sn) void loadMessages();
    };
    wsClient.on("sip_message_received", onSipMessage);
    return () => {
      wsClient.off("sip_message_received", onSipMessage);
    };
  }, [owner, loadThreads, loadMessages]);

  const openRoom = () => {
    const peer = newPeerInput.trim();
    if (!peer) return;
    setSelectedThreadId(peer);
    setRoomModalOpen(false);
    setNewPeerInput("");
    setInputBody("");
    setThreads((prev) => {
      if (prev.some((t) => t.thread_id === peer)) return prev;
      return [
        {
          thread_id: peer,
          owner,
          last_body: "",
          last_time: "",
          message_count: 0,
          inbound_count: 0,
          last_direction: "",
        },
        ...prev,
      ];
    });
  };

  const sendChat = async () => {
    if (!owner || !selectedThreadId || !inputBody.trim() || sending) return;
    setSending(true);
    setError(null);
    const res = await apiJson<SendResponse>("/api/chat/send", {
      method: "POST",
      body: {
        to_phone: selectedThreadId,
        body: inputBody.trim(),
        owner,
      },
    });
    setSending(false);
    if (!res.ok) {
      setError(res.message);
      return;
    }
    const data = res.data;
    if (!data.success) {
      setError(data.detail || data.error_code || "전송 실패");
    } else {
      setInputBody("");
    }
    await loadMessages();
    await loadThreads();
  };

  const retryOne = async (messageId: number) => {
    if (!owner || retryingId != null) return;
    setRetryingId(messageId);
    setError(null);
    const res = await apiJson<SendResponse>(
      `/api/chat/retry/${messageId}?owner=${encodeURIComponent(owner)}`,
      { method: "POST" }
    );
    setRetryingId(null);
    if (!res.ok) {
      setError(res.message);
      return;
    }
    if (!res.data.success) {
      setError(res.data.detail || res.data.error_code || "재전송 실패");
    }
    await loadMessages();
    await loadThreads();
  };

  if (!owner) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        로그인 후 테넌트(owner)가 설정되어야 채팅을 사용할 수 있습니다.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 h-full min-h-0 max-w-5xl mx-auto w-full">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 shrink-0">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">채팅 관리</h1>
          <p className="mt-1 text-sm text-gray-600">
            로그인 테넌트 <span className="font-mono text-indigo-700">{owner}</span> 기준입니다. 발신 SIP From은 테넌트(내선)와 동일한 REGISTER 사용자명을 씁니다. SIP MESSAGE AI 자동응답은{" "}
            <Link href="/settings/chat-relay" className="text-indigo-600 underline font-medium">
              채팅·SIP MESSAGE 설정
            </Link>
            에서 켤 수 있습니다. 상대는 SIP에 <strong>REGISTER</strong> 된 내선만 받을 수 있으며, 전송 결과는 상대 UA의 최종 SIP 응답(예: 200 OK) 기준입니다.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setRoomModalOpen(true)}
            className="px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700"
          >
            대화방 만들기
          </button>
          <button
            type="button"
            onClick={() => void loadThreads()}
            disabled={loadingThreads}
            className="px-4 py-2 rounded-md text-sm font-medium border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            새로고침
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800 shrink-0">{error}</div>
      )}

      {roomModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">대화방 만들기</h2>
            <p className="text-sm text-gray-600">상대 착신번호(내선)를 입력하면 해당 상대와의 대화방이 열립니다.</p>
            <label className="block text-sm font-medium text-gray-700">
              착신번호 / 내선
              <input
                type="text"
                value={newPeerInput}
                onChange={(e) => setNewPeerInput(e.target.value)}
                placeholder="예: 1004"
                className="mt-1 w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRoomModalOpen(false)}
                className="px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-md"
              >
                취소
              </button>
              <button
                type="button"
                onClick={openRoom}
                disabled={!newPeerInput.trim()}
                className="px-4 py-2 text-sm font-medium bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
              >
                열기
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-1 min-h-0 gap-4">
        <aside className="w-56 shrink-0 border border-gray-200 rounded-lg bg-white overflow-y-auto">
          <div className="px-3 py-2 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase">
            대화방
          </div>
          {loadingThreads && <p className="p-3 text-xs text-gray-500">불러오는 중…</p>}
          {!loadingThreads && threads.length === 0 && (
            <p className="p-3 text-xs text-gray-500">대화가 없습니다. 대화방 만들기로 시작하세요.</p>
          )}
          <ul className="divide-y divide-gray-100">
            {threads.map((t) => (
              <li key={t.thread_id}>
                <button
                  type="button"
                  onClick={() => setSelectedThreadId(t.thread_id)}
                  className={`w-full text-left px-3 py-2.5 text-sm hover:bg-indigo-50 ${
                    selectedThreadId === t.thread_id ? "bg-indigo-50 text-indigo-800 font-medium" : "text-gray-800"
                  }`}
                >
                  <div className="font-mono">{t.thread_id}</div>
                  {t.last_body && (
                    <div className="text-xs text-gray-500 truncate mt-0.5">{t.last_body}</div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="flex-1 flex flex-col min-w-0 border border-gray-200 rounded-lg bg-white min-h-[420px]">
          {!selectedThreadId ? (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-500 p-6">
              왼쪽에서 대화방을 선택하거나「대화방 만들기」로 상대 번호를 입력하세요.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-gray-100 shrink-0">
                <h2 className="text-sm font-semibold text-gray-900">
                  상대: <span className="font-mono text-indigo-700">{selectedThreadId}</span>
                </h2>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
                {loadingMessages && <p className="text-sm text-gray-500">메시지 불러오는 중…</p>}
                {!loadingMessages &&
                  messages.map((m) => {
                    const out = m.direction === "outbound";
                    return (
                      <div key={m.id} className={`flex ${out ? "justify-end" : "justify-start"}`}>
                        <div
                          className={`max-w-[85%] rounded-lg px-3 py-2 text-sm shadow-sm ${
                            out ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-900"
                          }`}
                        >
                          <p className="whitespace-pre-wrap break-words">{m.body}</p>
                          <div
                            className={`mt-1.5 flex flex-wrap items-center gap-2 text-[10px] ${
                              out ? "text-indigo-100" : "text-gray-500"
                            }`}
                          >
                            <span>{m.created_at}</span>
                            {out && (
                              <span
                                className={
                                  m.status === "sent"
                                    ? "text-emerald-200 font-medium"
                                    : "text-amber-200 font-medium"
                                }
                              >
                                {m.status === "sent" ? "전송됨" : "실패"}
                              </span>
                            )}
                            {out && m.status === "failed" && m.error_code && (
                              <span className="opacity-90">({m.error_code})</span>
                            )}
                            {out && m.status === "failed" && (
                              <button
                                type="button"
                                onClick={() => void retryOne(m.id)}
                                disabled={retryingId === m.id}
                                className="ml-1 px-2 py-0.5 rounded border border-white/40 hover:bg-white/10 font-medium"
                              >
                                {retryingId === m.id ? "재전송…" : "재전송"}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
              </div>
              <div className="p-3 border-t border-gray-100 shrink-0 flex gap-2">
                <textarea
                  value={inputBody}
                  onChange={(e) => setInputBody(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return;
                    if (e.key !== "Enter" || e.shiftKey) return;
                    e.preventDefault();
                    void sendChat();
                  }}
                  rows={2}
                  placeholder="메시지 입력… Enter 전송 · Shift+Enter 줄바꿈 (SIP MESSAGE)"
                  className="flex-1 text-sm border border-gray-300 rounded-md px-3 py-2 resize-none focus:ring-2 focus:ring-indigo-500"
                />
                <button
                  type="button"
                  onClick={() => void sendChat()}
                  disabled={sending || !inputBody.trim()}
                  className="self-end px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                >
                  {sending ? "전송…" : "전송"}
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
