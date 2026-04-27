"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiJson } from "@/lib/api";
import type { ContactFolderRow } from "@/lib/contactFolders";
import { groupFoldersByParent } from "@/lib/contactFolders";
import { sourceDetailLabel, type ContactRow } from "@/lib/contactTree";

type Props = {
  owner: string;
  contact: ContactRow | null;
  folders?: ContactFolderRow[];
  /** 서버 기본 미분류 폴더 id — 셀렉트·API null 과 동기화 */
  defaultUnfiledFolderId?: string | null;
  /** 트리에서 폴더만 선택된 경우 새 연락처 기본 폴더 */
  defaultFolderId?: string | null;
  onRefresh: () => Promise<void>;
  onBanner: (msg: string | null) => void;
  /** 삭제 후 선택 해제 */
  onClearSelection: () => void;
  onMobileBack?: () => void;
  showMobileBack?: boolean;
  /** 선택 없음·신규 폼일 때 매칭 번호 프리필(Call Dock 등) */
  prefillNewPhone?: string | null;
};

function folderSelectOptions(folders: ContactFolderRow[]): { id: string; label: string }[] {
  const byParent = groupFoldersByParent(folders);
  const out: { id: string; label: string }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const f of byParent.get(parent) ?? []) {
      const pad = depth > 0 ? `${"—".repeat(depth)} ` : "";
      out.push({ id: f.id, label: `${pad}${f.name}` });
      walk(f.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export function ContactDetailPanel({
  owner,
  contact,
  folders = [],
  defaultUnfiledFolderId = null,
  defaultFolderId = null,
  onRefresh,
  onBanner,
  onClearSelection,
  onMobileBack,
  showMobileBack,
  prefillNewPhone,
}: Props) {
  const [newPhone, setNewPhone] = useState("");
  const [newName, setNewName] = useState("");
  const [newMemo, setNewMemo] = useState("");
  const [newFolderId, setNewFolderId] = useState<string | null>(null);
  const [savingNew, setSavingNew] = useState(false);

  const [ePhone, setEPhone] = useState("");
  const [eName, setEName] = useState("");
  const [eMemo, setEMemo] = useState("");
  const [eFolderId, setEFolderId] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const folderOpts = useMemo(() => folderSelectOptions(folders), [folders]);
  const unfiledOpt = useMemo(
    () => (defaultUnfiledFolderId || "").trim(),
    [defaultUnfiledFolderId]
  );

  useEffect(() => {
    if (contact) {
      setEPhone(contact.canonical_phone);
      setEName(contact.display_name);
      setEMemo(contact.memo || "");
      setEFolderId(contact.folder_id ?? null);
    }
  }, [contact]);

  useEffect(() => {
    if (contact) return;
    if (!defaultFolderId) {
      setNewFolderId(null);
      return;
    }
    if (!unfiledOpt) {
      setNewFolderId(defaultFolderId);
      return;
    }
    setNewFolderId(defaultFolderId === unfiledOpt ? null : defaultFolderId);
  }, [contact, defaultFolderId, unfiledOpt]);

  useEffect(() => {
    if (contact || !prefillNewPhone?.trim()) return;
    setNewPhone((prev) => (prev.trim() ? prev : prefillNewPhone.trim()));
  }, [contact, prefillNewPhone]);

  const addContact = useCallback(async () => {
    if (!owner || !newPhone.trim() || !newName.trim()) {
      onBanner("번호(매칭 키)와 표시 이름을 입력하세요.");
      return;
    }
    setSavingNew(true);
    onBanner(null);
    const res = await apiJson<ContactRow>(`/api/caller-contacts`, {
      method: "POST",
      body: {
        owner,
        canonical_phone: newPhone.trim(),
        display_name: newName.trim(),
        memo: newMemo.trim(),
        folder_id: newFolderId,
      },
    });
    setSavingNew(false);
    if (!res.ok) {
      onBanner(res.message);
      return;
    }
    setNewPhone("");
    setNewName("");
    setNewMemo("");
    if (!defaultFolderId) setNewFolderId(null);
    else if (!unfiledOpt) setNewFolderId(defaultFolderId);
    else setNewFolderId(defaultFolderId === unfiledOpt ? null : defaultFolderId);
    onBanner("저장했습니다.");
    await onRefresh();
  }, [
    owner,
    newPhone,
    newName,
    newMemo,
    newFolderId,
    defaultFolderId,
    unfiledOpt,
    onBanner,
    onRefresh,
  ]);

  const saveEdit = useCallback(async () => {
    if (!owner || !contact) return;
    if (!eName.trim()) {
      onBanner("표시 이름을 입력하세요.");
      return;
    }
    if (!ePhone.trim()) {
      onBanner("매칭 번호를 입력하세요.");
      return;
    }
    setSavingEdit(true);
    onBanner(null);
    const res = await apiJson<ContactRow>(
      `/api/caller-contacts/${encodeURIComponent(contact.id)}`,
      {
        method: "PATCH",
        body: {
          owner,
          display_name: eName.trim(),
          memo: eMemo.trim(),
          canonical_phone: ePhone.trim(),
          folder_id: eFolderId,
        },
      }
    );
    setSavingEdit(false);
    if (!res.ok) {
      onBanner(res.message);
      return;
    }
    onBanner("수정했습니다.");
    await onRefresh();
  }, [owner, contact, eName, eMemo, ePhone, eFolderId, onBanner, onRefresh]);

  const remove = useCallback(async () => {
    if (!owner || !contact || !confirm("삭제할까요?")) return;
    onBanner(null);
    const res = await apiJson<{ ok: boolean }>(
      `/api/caller-contacts/${encodeURIComponent(contact.id)}?owner=${encodeURIComponent(owner)}`,
      { method: "DELETE" }
    );
    if (!res.ok) {
      onBanner(res.message);
      return;
    }
    onClearSelection();
    onBanner("삭제했습니다.");
    await onRefresh();
  }, [owner, contact, onBanner, onClearSelection, onRefresh]);

  if (!contact) {
    return (
      <div className="space-y-4">
        {showMobileBack && onMobileBack ? (
          <button
            type="button"
            onClick={onMobileBack}
            className="text-sm text-indigo-600 hover:text-indigo-800 lg:hidden"
          >
            ← 목록으로
          </button>
        ) : null}
        <div>
          <h2 className="text-base font-semibold text-gray-900">새 연락처</h2>
          <p className="mt-1 text-xs text-gray-600">
            왼쪽 목록에서 항목을 선택하면 수정할 수 있습니다.{" "}
            <strong>매칭 번호</strong>는 통화 기록·발신 CID와 같은 숫자 조각을 권장합니다.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            type="text"
            value={newPhone}
            onChange={(e) => setNewPhone(e.target.value)}
            placeholder="매칭 번호 (needle)"
            className="border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
          />
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="표시 이름"
            className="border border-gray-300 rounded-md px-3 py-2 text-sm"
          />
        </div>
        <input
          type="text"
          value={newMemo}
          onChange={(e) => setNewMemo(e.target.value)}
          placeholder="메모 (선택)"
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
        />
        <label className="block text-xs text-gray-600">
          폴더
          <select
            value={newFolderId ?? (unfiledOpt || "")}
            onChange={(e) => {
              const v = e.target.value;
              if (!unfiledOpt) setNewFolderId(v ? v : null);
              else if (!v || v === unfiledOpt) setNewFolderId(null);
              else setNewFolderId(v);
            }}
            className="mt-0.5 w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm bg-white"
          >
            <option value={unfiledOpt || ""}>미분류</option>
            {folderOpts.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={savingNew}
          onClick={() => void addContact()}
          className="px-4 py-2 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {savingNew ? "저장 중…" : "추가"}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {showMobileBack && onMobileBack ? (
        <button
          type="button"
          onClick={onMobileBack}
          className="text-sm text-indigo-600 hover:text-indigo-800 lg:hidden"
        >
          ← 목록으로
        </button>
      ) : null}

      <div className="rounded-lg border border-gray-100 bg-gray-50/80 p-3 text-sm">
        <p className="font-medium text-gray-900">{contact.display_name}</p>
        <p className="text-xs font-mono text-gray-600 mt-0.5">{contact.canonical_phone}</p>
        {contact.memo ? <p className="text-xs text-gray-500 mt-2">{contact.memo}</p> : null}
        <p className="text-[11px] text-gray-400 mt-2">
          {sourceDetailLabel(contact.source)}
          {contact.llm_confidence != null
            ? ` · conf ${Number(contact.llm_confidence).toFixed(2)}`
            : ""}
        </p>
      </div>

      <div>
        <h2 className="text-base font-semibold text-gray-900">편집</h2>
        <p className="mt-1 text-xs text-gray-600">
          저장 시 <strong>수동</strong>으로 표시되어 자동 생성이 덮어쓰지 않습니다.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs text-gray-600">
          매칭 번호
          <input
            type="text"
            value={ePhone}
            onChange={(e) => setEPhone(e.target.value)}
            className="mt-0.5 w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm font-mono"
          />
        </label>
        <label className="block text-xs text-gray-600">
          표시 이름
          <input
            type="text"
            value={eName}
            onChange={(e) => setEName(e.target.value)}
            className="mt-0.5 w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
          />
        </label>
      </div>
      <label className="block text-xs text-gray-600">
        메모
        <input
          type="text"
          value={eMemo}
          onChange={(e) => setEMemo(e.target.value)}
          className="mt-0.5 w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
        />
      </label>
      <label className="block text-xs text-gray-600">
        폴더
        <select
          value={eFolderId ?? (unfiledOpt || "")}
          onChange={(e) => {
            const v = e.target.value;
            if (!unfiledOpt) setEFolderId(v ? v : null);
            else if (!v || v === unfiledOpt) setEFolderId(null);
            else setEFolderId(v);
          }}
          className="mt-0.5 w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm bg-white"
        >
          <option value={unfiledOpt || ""}>미분류</option>
          {folderOpts.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          disabled={savingEdit}
          onClick={() => void saveEdit()}
          className="px-3 py-1.5 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {savingEdit ? "저장 중…" : "저장"}
        </button>
        <button
          type="button"
          disabled={savingEdit}
          onClick={() => void remove()}
          className="px-3 py-1.5 rounded-md text-sm text-rose-700 border border-rose-200 bg-white hover:bg-rose-50 disabled:opacity-50"
        >
          삭제
        </button>
      </div>
    </div>
  );
}
