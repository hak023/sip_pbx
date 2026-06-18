"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { ChevronRight, Folder, FolderOpen, GripVertical } from "lucide-react";
import type { ContactFolderRow } from "@/lib/contactFolders";
import { folderWouldCycle, groupFoldersByParent } from "@/lib/contactFolders";
import { sourceGroupLabel, sourceGroupKey, type ContactRow } from "@/lib/contactTree";
import { cn } from "@/lib/utils";

type DragData =
  | { type: "contact"; contactId: string }
  | { type: "folder"; folderId: string };

function dropIdForFolder(folderId: string): string {
  return `folder-drop-${folderId}`;
}

function sourceDotClass(source: string | undefined): string {
  switch (source || "manual") {
    case "manual":
      return "bg-indigo-500";
    case "auto_llm":
      return "bg-violet-500";
    case "auto_booking_hint":
      return "bg-amber-500";
    default:
      return "bg-slate-400";
  }
}

type Props = {
  folders: ContactFolderRow[];
  contacts: ContactRow[];
  /** 서버가 보장하는 기본 미분류 폴더 id (루트 1개) */
  defaultUnfiledFolderId: string;
  selectedContactId: string | null;
  selectedFolderId: string | null;
  expandedIds: Set<string>;
  onToggleExpand: (id: string) => void;
  onSelectContact: (id: string) => void;
  onSelectFolder: (id: string | null) => void;
  onMoveContact: (contactId: string, folderId: string | null) => Promise<void>;
  onMoveFolder: (folderId: string, newParentId: string | null) => Promise<void>;
  filterActive: boolean;
  /** 도크 등 좁은 레이아웃 */
  compact?: boolean;
};

function DraggableContactRow({
  contact,
  selected,
  compact,
  onSelect,
}: {
  contact: ContactRow;
  selected: boolean;
  compact?: boolean;
  onSelect: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `drag-contact-${contact.id}`,
    data: { type: "contact", contactId: contact.id } satisfies DragData,
  });
  const style = transform
    ? { transform: `translate3d(${transform.x}px,${transform.y}px,0)` }
    : undefined;
  const sk = sourceGroupKey(contact.source);
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group flex items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 transition-colors",
        selected
          ? "border-indigo-200 bg-indigo-50/90 shadow-sm"
          : "hover:border-slate-200 hover:bg-slate-50/90",
        isDragging && "opacity-60 ring-2 ring-indigo-300/50"
      )}
    >
      <button
        type="button"
        className="mt-0.5 cursor-grab touch-none text-slate-400 hover:text-slate-600 active:cursor-grabbing"
        aria-label="끌어서 폴더에 넣기"
        {...listeners}
        {...attributes}
      >
        <GripVertical className={cn("shrink-0", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />
      </button>
      <button type="button" className="min-w-0 flex-1 text-left" onClick={onSelect}>
        <span className="flex items-center gap-2 min-w-0">
          <span
            className={cn("shrink-0 rounded-full", compact ? "h-1.5 w-1.5" : "h-2 w-2", sourceDotClass(contact.source))}
            title={contact.source}
            aria-hidden
          />
          <span className={cn("truncate font-medium text-slate-900", compact ? "text-xs" : "text-sm")}>
            {contact.display_name || "—"}
          </span>
          <span
            className={cn(
              "shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 font-normal text-slate-600",
              compact ? "text-[9px]" : "text-[10px]"
            )}
          >
            {sourceGroupLabel(sk)}
          </span>
        </span>
        <span className={cn("mt-0.5 block truncate font-mono text-slate-500", compact ? "text-[10px]" : "text-xs")}>
          {contact.canonical_phone}
        </span>
      </button>
    </div>
  );
}

function FolderDroppableRow({
  folder,
  depth,
  expanded,
  hasChildren,
  selected,
  compact,
  onToggle,
  onSelectFolder,
  folderDragHandle,
}: {
  folder: ContactFolderRow;
  depth: number;
  expanded: boolean;
  hasChildren: boolean;
  selected: boolean;
  compact?: boolean;
  onToggle: () => void;
  onSelectFolder: () => void;
  folderDragHandle: ReactNode;
}) {
  const dropId = dropIdForFolder(folder.id);
  const { isOver, setNodeRef } = useDroppable({
    id: dropId,
    data: { type: "droppable", folderId: folder.id },
  });
  const pad = 10 + depth * 14;
  return (
    <div ref={setNodeRef} className="relative">
      {depth > 0 ? (
        <div
          className="absolute left-0 top-0 bottom-0 w-px bg-gradient-to-b from-slate-200 via-slate-200/80 to-transparent rounded-full"
          style={{ marginLeft: Math.max(0, pad - 10) }}
          aria-hidden
        />
      ) : null}
      <div
        className={cn(
          "flex min-w-0 items-center gap-1 rounded-lg border px-1 py-1 transition-colors",
          selected
            ? "border-indigo-200 bg-indigo-50/80"
            : "border-transparent hover:bg-slate-50/90",
          isOver && "border-indigo-300 bg-indigo-50 ring-1 ring-indigo-200/60"
        )}
        style={{ paddingLeft: pad }}
      >
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100",
            !hasChildren && "invisible pointer-events-none"
          )}
          aria-label={expanded ? "접기" : "펼치기"}
        >
          <ChevronRight className={cn("h-4 w-4 transition-transform", expanded && "rotate-90")} />
        </button>
        {folderDragHandle}
        <button
          type="button"
          onClick={onSelectFolder}
          className="flex min-w-0 flex-1 items-center gap-2 py-0.5 text-left"
        >
          {expanded ? (
            <FolderOpen className={cn("shrink-0 text-amber-500/90", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />
          ) : (
            <Folder className={cn("shrink-0 text-amber-500/80", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />
          )}
          <span className={cn("truncate font-medium text-slate-800", compact ? "text-xs" : "text-sm")}>
            {folder.name}
          </span>
        </button>
      </div>
    </div>
  );
}

function FolderDragHandle({
  folderId,
  compact,
  disabled,
}: {
  folderId: string;
  compact?: boolean;
  disabled?: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `drag-folder-${folderId}`,
    data: { type: "folder", folderId } satisfies DragData,
    disabled: Boolean(disabled),
  });
  const style = transform
    ? { transform: `translate3d(${transform.x}px,${transform.y}px,0)` }
    : undefined;
  if (disabled) {
    return (
      <span
        className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center text-slate-200"
        aria-hidden
      >
        <GripVertical className={cn("shrink-0", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />
      </span>
    );
  }
  return (
    <button
      ref={setNodeRef}
      type="button"
      style={style}
      className={cn(
        "mt-0.5 cursor-grab touch-none rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 active:cursor-grabbing",
        isDragging && "opacity-60"
      )}
      aria-label="폴더 이동"
      {...listeners}
      {...attributes}
    >
      <GripVertical className={cn("shrink-0", compact ? "h-3.5 w-3.5" : "h-4 w-4")} />
    </button>
  );
}

export function ContactFolderTree({
  folders,
  contacts,
  defaultUnfiledFolderId,
  selectedContactId,
  selectedFolderId,
  expandedIds,
  onToggleExpand,
  onSelectContact,
  onSelectFolder,
  onMoveContact,
  onMoveFolder,
  filterActive,
  compact,
}: Props) {
  const [busy, setBusy] = useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const byParent = useMemo(() => groupFoldersByParent(folders), [folders]);

  const contactsByFolder = useMemo(() => {
    const m = new Map<string, ContactRow[]>();
    for (const c of contacts) {
      const fid = c.folder_id ?? null;
      if (!fid) continue;
      if (!m.has(fid)) m.set(fid, []);
      m.get(fid)!.push(c);
    }
    for (const arr of m.values()) {
      arr.sort(
        (a, b) =>
          (a.display_name || "").localeCompare(b.display_name || "", "ko") ||
          (a.canonical_phone || "").localeCompare(b.canonical_phone || "", "ko")
      );
    }
    return m;
  }, [contacts]);

  const parseDropFolderId = useCallback((overId: string): string | null => {
    if (overId.startsWith("folder-drop-")) return overId.slice("folder-drop-".length);
    return null;
  }, []);

  const onDragEnd = useCallback(
    async (e: DragEndEvent) => {
      const { active, over } = e;
      if (!over || busy) return;
      const data = active.data.current as DragData | undefined;
      if (!data) return;
      const overId = String(over.id);
      const targetFolderId = parseDropFolderId(overId);
      if (targetFolderId === null) return;

      if (data.type === "contact") {
        const cur = contacts.find((c) => c.id === data.contactId);
        const curFolder = cur?.folder_id ?? null;
        if (curFolder === targetFolderId) return;
        setBusy(true);
        try {
          await onMoveContact(data.contactId, targetFolderId);
        } finally {
          setBusy(false);
        }
        return;
      }
      if (data.type === "folder") {
        if (data.folderId === defaultUnfiledFolderId) return;
        let newParent: string | null = targetFolderId;
        if (newParent === data.folderId) return;
        if (newParent !== null && folderWouldCycle(folders, data.folderId, newParent)) {
          return;
        }
        setBusy(true);
        try {
          await onMoveFolder(data.folderId, newParent);
        } finally {
          setBusy(false);
        }
      }
    },
    [busy, contacts, folders, defaultUnfiledFolderId, onMoveContact, onMoveFolder, parseDropFolderId]
  );

  const renderFolder = (folder: ContactFolderRow, depth: number): React.ReactNode => {
    const childFolders = byParent.get(folder.id) ?? [];
    const folderContacts = contactsByFolder.get(folder.id) ?? [];
    const expanded = expandedIds.has(folder.id);
    const hasChildren = childFolders.length > 0 || folderContacts.length > 0;
    const selected = selectedFolderId === folder.id;
    const isDefaultUnfiled = folder.id === defaultUnfiledFolderId;

    return (
      <div key={folder.id} className="space-y-0.5">
        <FolderDroppableRow
          folder={folder}
          depth={depth}
          expanded={expanded}
          hasChildren={hasChildren}
          selected={selected}
          compact={compact}
          onToggle={() => onToggleExpand(folder.id)}
          onSelectFolder={() => onSelectFolder(folder.id)}
          folderDragHandle={
            <FolderDragHandle
              folderId={folder.id}
              compact={compact}
              disabled={isDefaultUnfiled}
            />
          }
        />
        {expanded ? (
          <div className="space-y-0.5">
            {childFolders.map((ch) => renderFolder(ch, depth + 1))}
            {folderContacts.map((c) => (
              <div key={c.id} style={{ paddingLeft: 10 + (depth + 1) * 14 }}>
                <DraggableContactRow
                  contact={c}
                  selected={selectedContactId === c.id}
                  compact={compact}
                  onSelect={() => onSelectContact(c.id)}
                />
              </div>
            ))}
          </div>
        ) : null}
      </div>
    );
  };

  const rootFolders = byParent.get(null) ?? [];
  const orphanContacts = useMemo(
    () =>
      contacts.filter(
        (c) => !(c.folder_id ?? null) || !folders.some((f) => f.id === (c.folder_id ?? ""))
      ),
    [contacts, folders]
  );
  const showEmpty = !filterActive && folders.length === 0 && contacts.length === 0;

  if (showEmpty) {
    return <p className="text-sm text-slate-500 px-2 py-6 text-center">등록된 연락처가 없습니다.</p>;
  }

  return (
    <DndContext sensors={sensors} onDragEnd={(e) => void onDragEnd(e)}>
      <div className={cn("select-none", compact ? "text-xs" : "text-sm")}>
        {rootFolders.length === 0 && !defaultUnfiledFolderId ? (
          <p className="text-sm text-amber-700 px-2">폴더를 불러오는 중입니다.</p>
        ) : (
          rootFolders.map((f) => renderFolder(f, 0))
        )}

        {orphanContacts.length > 0 ? (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/50 px-2 py-2 text-xs text-amber-900">
            <p className="font-medium">폴더가 없는 연락처 {orphanContacts.length}건</p>
            <p className="text-amber-800/90 mt-0.5">
              목록을 새로고침하거나, 서버 기본 미분류 폴더 생성 후 다시 열어 주세요.
            </p>
            <ul className="mt-1 space-y-1">
              {orphanContacts.map((c) => (
                <li key={c.id}>
                  <DraggableContactRow
                    contact={c}
                    selected={selectedContactId === c.id}
                    compact={compact}
                    onSelect={() => onSelectContact(c.id)}
                  />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {filterActive && contacts.length === 0 ? (
          <p className="px-2 py-4 text-center text-slate-500">검색 결과가 없습니다.</p>
        ) : null}
      </div>
    </DndContext>
  );
}
