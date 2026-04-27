"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, UserRound, X } from "lucide-react";
import { ContactFolderTree } from "@/components/contacts/ContactFolderTree";
import { apiJson } from "@/lib/api";
import { logToAppLog } from "@/lib/clientAppLog";
import type { ContactFolderRow } from "@/lib/contactFolders";
import { defaultUnfiledFolderId } from "@/lib/contactFolders";
import type { ContactRow } from "@/lib/contactTree";
import { getTenantOwner } from "@/lib/tenant";
import { useActiveContactsDockStore } from "@/store/useActiveContactsDockStore";

const CONTACTS_DOCK_LOG = "contacts-dock";

function normalizeContactRows(raw: ContactRow[]): ContactRow[] {
  return raw.map((r) => ({ ...r, folder_id: r.folder_id ?? null }));
}

export function GlobalContactsDock() {
  const router = useRouter();
  const needle = useActiveContactsDockStore((s) => s.needle);
  const peerLabel = useActiveContactsDockStore((s) => s.peerLabel);
  const relatedCallId = useActiveContactsDockStore((s) => s.relatedCallId);
  const listQuery = useActiveContactsDockStore((s) => s.listQuery);
  const dockExpanded = useActiveContactsDockStore((s) => s.dockExpanded);
  const userMinimized = useActiveContactsDockStore((s) => s.userMinimized);
  const setDockExpanded = useActiveContactsDockStore((s) => s.setDockExpanded);
  const setUserMinimized = useActiveContactsDockStore((s) => s.setUserMinimized);
  const setListQuery = useActiveContactsDockStore((s) => s.setListQuery);
  const dismiss = useActiveContactsDockStore((s) => s.dismiss);

  const [owner, setOwner] = useState("");
  const [items, setItems] = useState<ContactRow[]>([]);
  const [folders, setFolders] = useState<ContactFolderRow[]>([]);
  const [serverDefaultUnfiledId, setServerDefaultUnfiledId] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setOwner(getTenantOwner());
  }, []);

  const loadContacts = useCallback(async () => {
    if (!owner) {
      setItems([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    setLoading(true);
    setBanner(null);
    const params = new URLSearchParams({ owner, limit: "200", offset: "0" });
    const q = listQuery.trim();
    if (q) params.set("q", q);
    const res = await apiJson<{ total: number; items: ContactRow[] }>(
      `/api/caller-contacts?${params.toString()}`
    );
    setLoading(false);
    if (!res.ok) {
      setBanner(res.message);
      setItems([]);
      setTotal(0);
      return;
    }
    setItems(normalizeContactRows(res.data.items || []));
    setTotal(res.data.total ?? 0);
  }, [owner, listQuery]);

  const loadFolders = useCallback(async () => {
    if (!owner) return;
    const res = await apiJson<{
      items: ContactFolderRow[];
      default_unfiled_folder_id?: string | null;
    }>(`/api/contact-folders?owner=${encodeURIComponent(owner)}`);
    if (res.ok) {
      setFolders(res.data.items || []);
      setServerDefaultUnfiledId(
        (res.data.default_unfiled_folder_id as string | null | undefined) ??
          defaultUnfiledFolderId(owner)
      );
    }
  }, [owner]);

  const load = useCallback(async () => {
    await Promise.all([loadContacts(), loadFolders()]);
  }, [loadContacts, loadFolders]);

  useEffect(() => {
    void load();
  }, [load]);

  const folderKey = useMemo(() => folders.map((f) => f.id).join("|"), [folders]);
  const effectiveUnfiledId = useMemo(
    () => (owner ? serverDefaultUnfiledId || defaultUnfiledFolderId(owner) : ""),
    [owner, serverDefaultUnfiledId]
  );

  useEffect(() => {
    if (!effectiveUnfiledId) return;
    setExpandedIds((prev) => {
      const n = new Set(prev);
      n.add(effectiveUnfiledId);
      folders.forEach((f) => n.add(f.id));
      return n;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- 폴더 id 집합 변화는 folderKey로만 반응
  }, [folderKey, effectiveUnfiledId]);

  useEffect(() => {
    if (listQuery.trim() && effectiveUnfiledId) {
      setExpandedIds(new Set([effectiveUnfiledId, ...folders.map((f) => f.id)]));
    }
  }, [listQuery, folders, effectiveUnfiledId]);

  useEffect(() => {
    if (selectedId && !items.some((i) => i.id === selectedId)) {
      setSelectedId(null);
    }
  }, [items, selectedId]);

  useEffect(() => {
    if (selectedFolderId && !folders.some((f) => f.id === selectedFolderId)) {
      setSelectedFolderId(null);
    }
  }, [folders, selectedFolderId]);

  const onToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }, []);

  const onSelectContact = useCallback(
    (id: string) => {
      setSelectedId(id);
      setSelectedFolderId(null);
      const c = items.find((i) => i.id === id);
      const phone = c?.canonical_phone?.trim();
      if (!phone) return;
      logToAppLog(
        "contacts_dock_row_navigate",
        { contact_id: id, related_call_id: relatedCallId },
        CONTACTS_DOCK_LOG
      );
      router.push(`/contacts?needle=${encodeURIComponent(phone)}`);
    },
    [items, relatedCallId, router]
  );

  const onSelectFolder = useCallback((id: string | null) => {
    setSelectedFolderId(id);
    setSelectedId(null);
  }, []);

  const onMoveContact = useCallback(
    async (contactId: string, folderId: string | null) => {
      const fid = folderId ?? (effectiveUnfiledId || null);
      const res = await apiJson<ContactRow>(`/api/caller-contacts/${contactId}`, {
        method: "PATCH",
        body: { owner, folder_id: fid },
      });
      if (!res.ok) {
        setBanner(res.message);
        return;
      }
      await load();
    },
    [owner, load, effectiveUnfiledId]
  );

  const onMoveFolder = useCallback(
    async (folderId: string, newParentId: string | null) => {
      const res = await apiJson(`/api/contact-folders/${folderId}`, {
        method: "PATCH",
        body: { owner, parent_id: newParentId },
      });
      if (!res.ok) {
        setBanner(res.message);
        return;
      }
      await loadFolders();
    },
    [owner, loadFolders]
  );

  const createFolder = useCallback(async () => {
    const name = window.prompt("새 폴더 이름", "새 폴더");
    if (!name?.trim() || !owner) return;
    const parent = selectedFolderId || effectiveUnfiledId || null;
    const res = await apiJson(`/api/contact-folders`, {
      method: "POST",
      body: {
        owner,
        name: name.trim(),
        parent_id: parent,
      },
    });
    if (!res.ok) {
      setBanner(res.message);
      return;
    }
    await loadFolders();
    setBanner(null);
  }, [owner, selectedFolderId, effectiveUnfiledId, loadFolders]);

  const fullPageHref = useMemo(() => {
    const n = needle.trim();
    if (n) return `/contacts?needle=${encodeURIComponent(n)}`;
    const q = listQuery.trim();
    if (q) return `/contacts?q=${encodeURIComponent(q)}`;
    return "/contacts";
  }, [needle, listQuery]);

  const headerSubtitle = needle.trim() ? peerLabel : "관리 연락처";
  const headerCaption = needle.trim() ? "CID에서 연 연락처" : "테넌트 연락처 목록";

  const pillLabel = useMemo(() => {
    if (loading && items.length === 0 && total === 0) return "연락처";
    if (total > 0) return `연락처 · ${total}건`;
    return "연락처";
  }, [loading, items.length, total]);

  if (userMinimized) {
    return (
      <div className="flex w-full items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setUserMinimized(false);
            setDockExpanded(true);
          }}
          className="flex items-center gap-2 rounded-full border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-900 shadow-lg hover:bg-indigo-100"
        >
          <UserRound className="h-4 w-4 shrink-0" aria-hidden />
          {pillLabel}
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-full max-h-[min(48vh,360px)] flex-col rounded-xl border border-slate-200 bg-white shadow-2xl ring-1 ring-slate-900/5">
      <div className="flex shrink-0 items-start justify-between gap-2 rounded-t-xl border-b border-slate-100 bg-gradient-to-r from-indigo-50 to-white px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-indigo-700">
              <UserRound className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-slate-500">{headerCaption}</p>
              <p className="truncate text-sm font-semibold text-slate-900" title={headerSubtitle}>
                {headerSubtitle}
              </p>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
            aria-expanded={dockExpanded}
            aria-label={dockExpanded ? "접기" : "펼치기"}
            onClick={() => setDockExpanded(!dockExpanded)}
          >
            {dockExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          </button>
          <button
            type="button"
            className="rounded-md p-1.5 text-slate-500 hover:bg-rose-50 hover:text-rose-700"
            aria-label="최소화"
            onClick={() => {
              dismiss();
              setBanner(null);
            }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {dockExpanded && (
        <>
          <div className="shrink-0 space-y-2 border-b border-slate-100 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void createFolder()}
                className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-medium text-slate-800 hover:bg-slate-50"
              >
                새 폴더
              </button>
              <span className="text-[11px] text-slate-400 tabular-nums">전체 {total}건</span>
            </div>
            <label className="sr-only" htmlFor="contacts-dock-q">
              연락처 검색
            </label>
            <input
              id="contacts-dock-q"
              type="search"
              value={listQuery}
              onChange={(e) => setListQuery(e.target.value)}
              placeholder="이름·번호 검색…"
              className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-900 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-300"
            />
            {!owner ? (
              <p className="text-xs text-amber-800">로그인 후 테넌트(owner)가 설정되어야 목록을 불러옵니다.</p>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 py-2 text-sm">
            {banner ? (
              <p className="rounded-md border border-amber-100 bg-amber-50 px-2 py-1 text-xs text-amber-900">
                {banner}
              </p>
            ) : null}
            {loading ? (
              <p className="text-xs text-slate-500">불러오는 중…</p>
            ) : owner ? (
              <ContactFolderTree
                folders={folders}
                contacts={items}
                defaultUnfiledFolderId={effectiveUnfiledId}
                selectedContactId={selectedId}
                selectedFolderId={selectedFolderId}
                expandedIds={expandedIds}
                onToggleExpand={onToggleExpand}
                onSelectContact={onSelectContact}
                onSelectFolder={onSelectFolder}
                onMoveContact={onMoveContact}
                onMoveFolder={onMoveFolder}
                filterActive={!!listQuery.trim()}
                compact
              />
            ) : null}
            {!loading && owner ? (
              <p className="text-[11px] text-slate-400 tabular-nums">표시 {items.length} / 전체 {total}건</p>
            ) : null}
          </div>

          <div className="shrink-0 space-y-2 border-t border-slate-100 px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                className="text-xs text-slate-500 hover:text-slate-800"
                onClick={() => setUserMinimized(true)}
              >
                최소화
              </button>
              <Link
                href={fullPageHref}
                className="text-xs text-indigo-700 underline hover:text-indigo-900"
                onClick={() =>
                  logToAppLog(
                    "contacts_dock_full_page_link",
                    {
                      needle_len: needle.trim().length,
                      q_len: listQuery.trim().length,
                      related_call_id: relatedCallId,
                    },
                    CONTACTS_DOCK_LOG
                  )
                }
              >
                연락처 전체 화면
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
