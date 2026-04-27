"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ContactDetailPanel } from "@/components/contacts/ContactDetailPanel";
import { ContactFolderTree } from "@/components/contacts/ContactFolderTree";
import { ContactsLayout } from "@/components/contacts/ContactsLayout";
import { apiJson } from "@/lib/api";
import type { ContactFolderRow } from "@/lib/contactFolders";
import { defaultUnfiledFolderId } from "@/lib/contactFolders";
import type { ContactRow } from "@/lib/contactTree";
import { getTenantOwner } from "@/lib/tenant";

function urlSearchNeedle(searchParams: URLSearchParams): string {
  return (
    searchParams.get("needle")?.trim() ||
    searchParams.get("q")?.trim() ||
    ""
  );
}

function normalizeContactRows(raw: ContactRow[]): ContactRow[] {
  return raw.map((r) => ({ ...r, folder_id: r.folder_id ?? null }));
}

function CallerContactsPageInner() {
  const searchParams = useSearchParams();
  const [owner, setOwner] = useState("");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<ContactRow[]>([]);
  const [folders, setFolders] = useState<ContactFolderRow[]>([]);
  const [serverDefaultUnfiledId, setServerDefaultUnfiledId] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [treeCollapsed, setTreeCollapsed] = useState(false);
  const [prefillNewPhone, setPrefillNewPhone] = useState<string | null>(null);
  const [lastFetchOk, setLastFetchOk] = useState(true);
  const appliedUrlFocusRef = useRef(false);

  useEffect(() => {
    setOwner(getTenantOwner());
  }, []);

  const needleFromUrl = useMemo(() => urlSearchNeedle(searchParams), [searchParams]);

  useEffect(() => {
    appliedUrlFocusRef.current = false;
    setPrefillNewPhone(null);
  }, [needleFromUrl]);

  useEffect(() => {
    const n = urlSearchNeedle(searchParams);
    if (n) setQ(n);
  }, [searchParams]);

  const loadContacts = useCallback(async () => {
    if (!owner) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setBanner(null);
    const params = new URLSearchParams({ owner, limit: "200", offset: "0" });
    if (q.trim()) params.set("q", q.trim());
    const res = await apiJson<{ total: number; items: ContactRow[] }>(
      `/api/caller-contacts?${params.toString()}`
    );
    setLoading(false);
    if (!res.ok) {
      setLastFetchOk(false);
      setBanner(res.message);
      setItems([]);
      setTotal(0);
      return;
    }
    setLastFetchOk(true);
    setItems(normalizeContactRows(res.data.items || []));
    setTotal(res.data.total ?? 0);
  }, [owner, q]);

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
    if (q.trim() && effectiveUnfiledId) {
      setExpandedIds(new Set([effectiveUnfiledId, ...folders.map((f) => f.id)]));
    }
  }, [q, folders, effectiveUnfiledId]);

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

  useEffect(() => {
    if (loading) return;
    const needle = needleFromUrl;
    if (!needle.trim() || appliedUrlFocusRef.current) return;
    if (items.length === 1) {
      appliedUrlFocusRef.current = true;
      setSelectedId(items[0].id);
      setPrefillNewPhone(null);
      return;
    }
    if (items.length === 0 && q.trim() === needle.trim() && lastFetchOk) {
      appliedUrlFocusRef.current = true;
      setPrefillNewPhone(needle.trim());
    }
  }, [loading, items, needleFromUrl, q, lastFetchOk]);

  const selectedContact = useMemo(
    () => items.find((c) => c.id === selectedId) ?? null,
    [items, selectedId]
  );

  const onToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }, []);

  const onSelectContact = useCallback((id: string) => {
    setSelectedId(id);
    setSelectedFolderId(null);
  }, []);

  const onSelectFolder = useCallback((id: string | null) => {
    setSelectedFolderId(id);
    setSelectedId(null);
  }, []);

  const onMoveContact = useCallback(
    async (contactId: string, folderId: string | null) => {
      const fid =
        folderId ??
        (effectiveUnfiledId || null);
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
    const parent =
      selectedFolderId ||
      effectiveUnfiledId ||
      null;
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

  const renameFolder = useCallback(async () => {
    if (!selectedFolderId || !owner) return;
    const f = folders.find((x) => x.id === selectedFolderId);
    const name = window.prompt("폴더 이름", f?.name || "");
    if (!name?.trim()) return;
    const res = await apiJson(`/api/contact-folders/${selectedFolderId}`, {
      method: "PATCH",
      body: { owner, name: name.trim() },
    });
    if (!res.ok) {
      setBanner(res.message);
      return;
    }
    await loadFolders();
    setBanner(null);
  }, [owner, selectedFolderId, folders, loadFolders]);

  const deleteFolder = useCallback(async () => {
    if (!selectedFolderId || !owner) return;
    if (effectiveUnfiledId && selectedFolderId === effectiveUnfiledId) {
      setBanner("기본 미분류 폴더는 삭제할 수 없습니다.");
      return;
    }
    if (!window.confirm("이 폴더를 삭제할까요? 하위 폴더·연락처는 상위(또는 미분류)로 옮겨집니다.")) return;
    const res = await apiJson(`/api/contact-folders/${selectedFolderId}?owner=${encodeURIComponent(owner)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      setBanner(res.message);
      return;
    }
    setSelectedFolderId(null);
    await load();
  }, [owner, selectedFolderId, effectiveUnfiledId, load]);

  if (!owner) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 max-w-xl mx-auto mt-8">
        로그인 후 테넌트(owner)가 설정되어야 합니다.
      </div>
    );
  }

  return (
    <div className="w-full px-4 py-8">
      <div className="max-w-6xl mx-auto mb-4">
        <Link href="/dashboard" className="text-sm text-indigo-600 hover:text-indigo-800">
          ← 대시보드
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-gray-900">연락처</h1>
        <p className="mt-2 text-sm text-gray-600 max-w-2xl">
          왼쪽에서 <strong>폴더</strong>를 만들고 연락처를 끌어 넣어 정리할 수 있습니다. 출처는 행 옆 배지로만 표시됩니다.
          이름·메모·번호를 저장하면 <strong>수동</strong>으로 표시되어 자동 생성이 덮어쓰지 않습니다.
        </p>
      </div>

      {banner && (
        <div className="max-w-6xl mx-auto mb-4">
          <div
            className={`rounded-lg border px-4 py-2 text-sm ${
              banner === "저장했습니다." ||
              banner === "수정했습니다." ||
              banner === "삭제했습니다."
                ? "border-green-200 bg-green-50 text-green-900"
                : "border-amber-200 bg-amber-50 text-amber-900"
            }`}
          >
            {banner}
          </div>
        </div>
      )}

      <ContactsLayout
        treeCollapsed={treeCollapsed}
        onToggleTreeCollapse={() => setTreeCollapsed((c) => !c)}
        toolbar={
          <div className="max-w-6xl mx-auto flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void createFolder()}
                className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50"
              >
                새 폴더
              </button>
              <button
                type="button"
                disabled={!selectedFolderId}
                onClick={() => void renameFolder()}
                className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-40"
              >
                폴더 이름 변경
              </button>
              <button
                type="button"
                disabled={!selectedFolderId}
                onClick={() => void deleteFolder()}
                className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-800 hover:bg-rose-100 disabled:opacity-40"
              >
                폴더 삭제
              </button>
              <span className="text-xs text-gray-500 tabular-nums">전체 {total}건</span>
            </div>
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="검색…"
              className="border border-gray-300 rounded-md px-3 py-1.5 text-sm min-w-[12rem] flex-1 sm:flex-none"
            />
          </div>
        }
        tree={
          loading ? (
            <p className="text-sm text-gray-500 px-2 py-4">불러오는 중…</p>
          ) : (
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
              filterActive={!!q.trim()}
            />
          )
        }
        detail={
          <ContactDetailPanel
            owner={owner}
            contact={selectedContact}
            folders={folders}
            defaultUnfiledFolderId={effectiveUnfiledId}
            onRefresh={load}
            onBanner={setBanner}
            onClearSelection={() => setSelectedId(null)}
            prefillNewPhone={selectedContact ? null : prefillNewPhone}
            defaultFolderId={selectedFolderId ?? effectiveUnfiledId}
          />
        }
      />
    </div>
  );
}

export default function CallerContactsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-600 max-w-6xl mx-auto">불러오는 중…</div>}>
      <CallerContactsPageInner />
    </Suspense>
  );
}
