/**
 * 지식 추출 리뷰 대시보드
 *
 * 통화에서 자동 추출된 지식을 리뷰(승인/거절/편집)
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Check,
  X,
  Edit,
  Trash2,
  FileText,
  HelpCircle,
  Tag,
  ArrowLeft,
  BarChart3,
} from 'lucide-react';
import { useRouter } from 'next/navigation';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ExtractionEntry {
  id: string;
  doc_type: string;
  text: string;
  category: string;
  confidence_score: number;
  review_status: string;
  hallucination_check: string;
  dedup_status: string;
  extraction_call_id: string;
  extraction_timestamp: string;
  pipeline_version: string;
  owner: string;
  question?: string;
  source_speaker?: string;
  entity_type?: string;
  normalized_value?: string;
  usage_count: number;
  keywords: string;
  reviewed_by?: string;
  reviewed_at?: string;
}

interface ExtractionStats {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  auto_approved: number;
  by_doc_type: Record<string, number>;
  avg_confidence: number;
}

const DOC_TYPE_INFO: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  knowledge: { label: '지식', icon: <FileText className="w-4 h-4" />, color: 'bg-blue-100 text-blue-700' },
  qa_pair: { label: 'QA 쌍', icon: <HelpCircle className="w-4 h-4" />, color: 'bg-purple-100 text-purple-700' },
  entity: { label: '엔티티', icon: <Tag className="w-4 h-4" />, color: 'bg-orange-100 text-orange-700' },
};

const STATUS_INFO: Record<string, { label: string; color: string }> = {
  pending: { label: '대기중', color: 'bg-yellow-100 text-yellow-700' },
  approved: { label: '승인됨', color: 'bg-green-100 text-green-700' },
  rejected: { label: '거절됨', color: 'bg-red-100 text-red-700' },
  edited: { label: '편집됨', color: 'bg-blue-100 text-blue-700' },
};

export default function ExtractionsPage() {
  const router = useRouter();
  const [entries, setEntries] = useState<ExtractionEntry[]>([]);
  const [stats, setStats] = useState<ExtractionStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('pending');

  // Edit dialog
  const [editEntry, setEditEntry] = useState<ExtractionEntry | null>(null);
  const [editText, setEditText] = useState('');
  const [showEditDialog, setShowEditDialog] = useState(false);

  // Delete dialog
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      const headers = { Authorization: `Bearer ${token}` };

      const reviewFilter = activeTab === 'all' ? undefined : activeTab;
      
      // 로그인된 테넌트의 착신번호(owner)로 필터링
      let owner: string | undefined;
      try {
        const tenantStr = localStorage.getItem('tenant');
        if (tenantStr) {
          const tenant = JSON.parse(tenantStr);
          owner = tenant.owner;
        }
      } catch {}

      const [entriesRes, statsRes] = await Promise.all([
        axios.get(`${API_URL}/api/extractions/`, {
          params: { review_status: reviewFilter, limit: 200, owner },
          headers,
        }),
        axios.get(`${API_URL}/api/extractions/stats`, {
          params: { owner },
          headers,
        }),
      ]);

      setEntries(entriesRes.data.items);
      setStats(statsRes.data);
    } catch (error) {
      console.error('Failed to fetch extractions:', error);
      toast.error('추출 목록 조회 실패');
    } finally {
      setIsLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleReview = async (id: string, action: string, text?: string) => {
    try {
      const token = localStorage.getItem('access_token');
      await axios.patch(
        `${API_URL}/api/extractions/${id}/review`,
        {
          action,
          edited_text: text,
          reviewer: 'operator',
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      toast.success(
        action === 'approve'
          ? '승인되었습니다'
          : action === 'reject'
            ? '거절되었습니다'
            : '편집 저장됨'
      );
      fetchData();
    } catch {
      toast.error('처리 실패');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const token = localStorage.getItem('access_token');
      await axios.delete(`${API_URL}/api/extractions/${deleteTarget}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success('삭제되었습니다');
      setShowDeleteDialog(false);
      setDeleteTarget(null);
      fetchData();
    } catch {
      toast.error('삭제 실패');
    }
  };

  const openEditDialog = (entry: ExtractionEntry) => {
    setEditEntry(entry);
    setEditText(entry.text);
    setShowEditDialog(true);
  };

  const docTypeInfo = (dt: string) => DOC_TYPE_INFO[dt] || DOC_TYPE_INFO.knowledge;
  const statusInfo = (s: string) => STATUS_INFO[s] || STATUS_INFO.pending;

  const approvalRate =
    stats && stats.total > 0
      ? (((stats.approved + (stats.auto_approved || 0)) / stats.total) * 100).toFixed(1)
      : '0';

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="ghost" size="sm" onClick={() => router.push('/dashboard')}>
                <ArrowLeft className="w-4 h-4 mr-2" />
                대시보드
              </Button>
              <h1 className="text-2xl font-bold text-gray-900">📋 지식 추출 리뷰</h1>
            </div>
            <Button variant="outline" size="sm" onClick={fetchData}>
              <BarChart3 className="w-4 h-4 mr-2" />
              새로고침
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-6 gap-4">
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold">{stats.total}</p>
                <p className="text-xs text-gray-500">전체</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold text-yellow-600">{stats.pending}</p>
                <p className="text-xs text-gray-500">대기중</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold text-green-600">{stats.approved}</p>
                <p className="text-xs text-gray-500">승인</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold text-red-600">{stats.rejected}</p>
                <p className="text-xs text-gray-500">거절</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold text-blue-600">{approvalRate}%</p>
                <p className="text-xs text-gray-500">승인률</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6 text-center">
                <p className="text-2xl font-bold">{stats.avg_confidence.toFixed(2)}</p>
                <p className="text-xs text-gray-500">평균 신뢰도</p>
              </CardContent>
            </Card>
          </div>
        )}

        {/* List */}
        <Card>
          <CardHeader>
            <CardTitle>추출 항목</CardTitle>
            <CardDescription>
              통화에서 자동 추출된 지식을 검토하고 승인/거절합니다
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="mb-4">
                <TabsTrigger value="pending">
                  🟡 대기중 {stats ? `(${stats.pending})` : ''}
                </TabsTrigger>
                <TabsTrigger value="approved">🟢 승인됨</TabsTrigger>
                <TabsTrigger value="rejected">🔴 거절됨</TabsTrigger>
                <TabsTrigger value="all">전체</TabsTrigger>
              </TabsList>

              <TabsContent value={activeTab}>
                {isLoading ? (
                  <div className="text-center py-8">로딩 중...</div>
                ) : entries.length === 0 ? (
                  <div className="text-center py-12 text-gray-500">
                    {activeTab === 'pending'
                      ? '대기중인 항목이 없습니다'
                      : '항목이 없습니다'}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {entries.map((entry) => {
                      const dt = docTypeInfo(entry.doc_type);
                      const st = statusInfo(entry.review_status);
                      return (
                        <div
                          key={entry.id}
                          className="border rounded-lg p-4 hover:bg-gray-50 transition"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1">
                              {/* Badges */}
                              <div className="flex items-center gap-2 mb-2 flex-wrap">
                                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${dt.color}`}>
                                  {dt.icon}
                                  {dt.label}
                                </span>
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${st.color}`}>
                                  {st.label}
                                </span>
                                <Badge variant="outline" className="text-xs">
                                  신뢰도 {(entry.confidence_score * 100).toFixed(0)}%
                                </Badge>
                                {entry.hallucination_check === 'passed' && (
                                  <Badge variant="outline" className="text-xs text-green-600">
                                    환각검증 통과
                                  </Badge>
                                )}
                                {entry.dedup_status === 'near_duplicate' && (
                                  <Badge variant="outline" className="text-xs text-orange-600">
                                    유사 문서 존재
                                  </Badge>
                                )}
                              </div>

                              {/* Content */}
                              {entry.doc_type === 'qa_pair' && entry.question ? (
                                <div className="space-y-1">
                                  <p className="text-sm font-medium text-purple-700">
                                    Q: {entry.question}
                                  </p>
                                  <p className="text-sm text-gray-700">
                                    A:{' '}
                                    {entry.text.replace(/^Q:.*\nA:\s*/, '')}
                                  </p>
                                </div>
                              ) : entry.doc_type === 'entity' ? (
                                <div>
                                  <p className="text-sm">
                                    <span className="font-medium text-orange-700">
                                      [{entry.entity_type}]
                                    </span>{' '}
                                    {entry.text}
                                    {entry.normalized_value && (
                                      <span className="text-gray-500 ml-2">
                                        → {entry.normalized_value}
                                      </span>
                                    )}
                                  </p>
                                </div>
                              ) : (
                                <p className="text-sm text-gray-700">{entry.text}</p>
                              )}

                              {/* Meta */}
                              <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                                <span>통화 #{entry.extraction_call_id.slice(0, 8)}</span>
                                <span>{entry.category}</span>
                                {entry.extraction_timestamp && (
                                  <span>
                                    {new Date(entry.extraction_timestamp).toLocaleString()}
                                  </span>
                                )}
                                {entry.reviewed_by && (
                                  <span>리뷰: {entry.reviewed_by}</span>
                                )}
                              </div>
                            </div>

                            {/* Actions */}
                            <div className="flex gap-1 shrink-0">
                              {entry.review_status === 'pending' && (
                                <>
                                  <Button
                                    size="sm"
                                    variant="default"
                                    className="bg-green-600 hover:bg-green-700"
                                    onClick={() => handleReview(entry.id, 'approve')}
                                  >
                                    <Check className="w-4 h-4" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => openEditDialog(entry)}
                                  >
                                    <Edit className="w-4 h-4" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    onClick={() => handleReview(entry.id, 'reject')}
                                  >
                                    <X className="w-4 h-4" />
                                  </Button>
                                </>
                              )}
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  setDeleteTarget(entry.id);
                                  setShowDeleteDialog(true);
                                }}
                              >
                                <Trash2 className="w-4 h-4 text-gray-400" />
                              </Button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </main>

      {/* Edit Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>추출 내용 편집</DialogTitle>
            <DialogDescription>
              내용을 수정한 후 저장하면 &quot;편집됨&quot; 상태로 승인됩니다.
            </DialogDescription>
          </DialogHeader>

          {editEntry && (
            <div className="space-y-4">
              <div>
                <p className="text-sm font-medium mb-1">원본:</p>
                <ScrollArea className="h-24 border rounded p-3 bg-gray-50 text-sm">
                  {editEntry.text}
                </ScrollArea>
              </div>
              <div>
                <p className="text-sm font-medium mb-1">편집:</p>
                <Textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  rows={4}
                />
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)}>
              취소
            </Button>
            <Button
              onClick={() => {
                if (editEntry) {
                  handleReview(editEntry.id, 'edit', editText);
                  setShowEditDialog(false);
                }
              }}
            >
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>항목 삭제</DialogTitle>
            <DialogDescription>
              이 추출 항목을 영구 삭제하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowDeleteDialog(false);
                setDeleteTarget(null);
              }}
            >
              취소
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
