/**
 * AI 서비스 관리 페이지
 *
 * VectorDB의 capability 항목을 관리 (CRUD, 순서 변경, 활성/비활성 토글)
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Plus,
  Edit,
  Trash2,
  RefreshCw,
  GripVertical,
  Phone,
  FileText,
  Link,
  ClipboardList,
  ArrowLeft,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Capability {
  id: string;
  display_name: string;
  text: string;
  category: string;
  response_type: string;
  keywords: string[];
  priority: number;
  is_active: boolean;
  owner?: string;
  api_endpoint?: string;
  api_method?: string;
  transfer_to?: string;
  created_at: string;
}

interface GuideText {
  text: string;
  capability_count: number;
  cached: boolean;
  generated_at: string;
}

const RESPONSE_TYPE_INFO: Record<
  string,
  { label: string; icon: React.ReactNode; color: string }
> = {
  info: {
    label: '정보안내',
    icon: <FileText className="w-4 h-4" />,
    color: 'bg-blue-100 text-blue-700',
  },
  api_call: {
    label: 'API연동',
    icon: <Link className="w-4 h-4" />,
    color: 'bg-purple-100 text-purple-700',
  },
  transfer: {
    label: '상담원연결',
    icon: <Phone className="w-4 h-4" />,
    color: 'bg-green-100 text-green-700',
  },
  collect: {
    label: '정보수집',
    icon: <ClipboardList className="w-4 h-4" />,
    color: 'bg-orange-100 text-orange-700',
  },
};

export default function CapabilitiesPage() {
  const router = useRouter();
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [guideText, setGuideText] = useState<GuideText | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('all');

  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const fetchCapabilities = useCallback(async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      const tenantData = localStorage.getItem('tenant');
      const owner = tenantData ? JSON.parse(tenantData).owner : undefined;
      const headers = { Authorization: `Bearer ${token}` };

      const [capRes, guideRes] = await Promise.all([
        axios.get(`${API_URL}/api/capabilities/`, { headers, params: { owner } }),
        axios.get(`${API_URL}/api/capabilities/guide-text`, { headers, params: { owner } }),
      ]);

      setCapabilities(capRes.data.items);
      setGuideText(guideRes.data);
    } catch (error) {
      console.error('Failed to fetch capabilities:', error);
      toast.error('서비스 목록 조회 실패');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCapabilities();
  }, [fetchCapabilities]);

  const handleToggle = async (capId: string) => {
    try {
      const token = localStorage.getItem('access_token');
      await axios.patch(`${API_URL}/api/capabilities/${capId}/toggle`, null, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success('상태가 변경되었습니다');
      fetchCapabilities();
    } catch {
      toast.error('상태 변경 실패');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      const token = localStorage.getItem('access_token');
      await axios.delete(`${API_URL}/api/capabilities/${deleteTarget}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success('서비스가 삭제되었습니다');
      setShowDeleteDialog(false);
      setDeleteTarget(null);
      fetchCapabilities();
    } catch {
      toast.error('삭제 실패');
    }
  };

  const handleRefreshGuide = async () => {
    try {
      const token = localStorage.getItem('access_token');
      const res = await axios.post(
        `${API_URL}/api/capabilities/guide-text/refresh`,
        null,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setGuideText(res.data);
      toast.success('가이드 멘트가 새로고침되었습니다');
    } catch {
      toast.error('가이드 멘트 새로고침 실패');
    }
  };

  const filteredCapabilities =
    activeTab === 'all'
      ? capabilities
      : capabilities.filter((c) => c.response_type === activeTab);

  const activeCount = capabilities.filter((c) => c.is_active).length;
  const inactiveCount = capabilities.length - activeCount;

  const typeInfo = (rt: string) =>
    RESPONSE_TYPE_INFO[rt] || RESPONSE_TYPE_INFO.info;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push('/dashboard')}
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                대시보드
              </Button>
              <h1 className="text-2xl font-bold text-gray-900">
                🤖 AI 서비스 관리
              </h1>
            </div>
            <Button onClick={() => router.push('/capabilities/add')}>
              <Plus className="w-4 h-4 mr-2" />
              서비스 추가
            </Button>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Guide Text Preview */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg">📋 가이드 멘트 미리보기</CardTitle>
              <Button variant="outline" size="sm" onClick={handleRefreshGuide}>
                <RefreshCw className="w-4 h-4 mr-2" />
                새로고침
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {guideText ? (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-blue-900 font-medium">
                  &quot;{guideText.text}&quot;
                </p>
                <p className="text-xs text-blue-500 mt-2">
                  서비스 {guideText.capability_count}개 ·{' '}
                  {guideText.cached ? '캐시됨' : '새로 생성'} ·{' '}
                  {new Date(guideText.generated_at).toLocaleString()}
                </p>
              </div>
            ) : (
              <p className="text-gray-500">가이드 멘트를 불러오는 중...</p>
            )}
          </CardContent>
        </Card>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4">
          <Card>
            <CardContent className="pt-6 text-center">
              <p className="text-3xl font-bold">{capabilities.length}</p>
              <p className="text-sm text-gray-500">전체 서비스</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <p className="text-3xl font-bold text-green-600">{activeCount}</p>
              <p className="text-sm text-gray-500">활성</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <p className="text-3xl font-bold text-gray-400">
                {inactiveCount}
              </p>
              <p className="text-sm text-gray-500">비활성</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-6 text-center">
              <p className="text-3xl font-bold text-blue-600">
                {
                  new Set(capabilities.map((c) => c.response_type)).size
                }
              </p>
              <p className="text-sm text-gray-500">응답 유형</p>
            </CardContent>
          </Card>
        </div>

        {/* Service List */}
        <Card>
          <CardHeader>
            <CardTitle>서비스 목록</CardTitle>
            <CardDescription>
              AI가 안내할 수 있는 서비스를 관리합니다. 우선순위가 낮을수록 먼저
              안내됩니다.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="mb-4">
                <TabsTrigger value="all">전체</TabsTrigger>
                <TabsTrigger value="info">📄 정보안내</TabsTrigger>
                <TabsTrigger value="api_call">🔗 API연동</TabsTrigger>
                <TabsTrigger value="transfer">📞 상담원연결</TabsTrigger>
                <TabsTrigger value="collect">📝 정보수집</TabsTrigger>
              </TabsList>

              <TabsContent value={activeTab}>
                {isLoading ? (
                  <div className="text-center py-8">로딩 중...</div>
                ) : filteredCapabilities.length === 0 ? (
                  <div className="text-center py-12">
                    <p className="text-gray-500 mb-4">등록된 서비스가 없습니다</p>
                    <Button onClick={() => router.push('/capabilities/add')}>
                      <Plus className="w-4 h-4 mr-2" />
                      첫 번째 서비스 추가
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {/* Table Header */}
                    <div className="grid grid-cols-12 gap-4 px-4 py-2 text-xs font-medium text-gray-500 uppercase border-b">
                      <div className="col-span-1">순서</div>
                      <div className="col-span-1">활성</div>
                      <div className="col-span-3">서비스명</div>
                      <div className="col-span-2">유형</div>
                      <div className="col-span-2">카테고리</div>
                      <div className="col-span-3 text-right">동작</div>
                    </div>

                    {filteredCapabilities.map((cap) => {
                      const rt = typeInfo(cap.response_type);
                      return (
                        <div
                          key={cap.id}
                          className={`grid grid-cols-12 gap-4 items-center px-4 py-3 rounded-lg border transition ${
                            cap.is_active
                              ? 'bg-white hover:bg-gray-50'
                              : 'bg-gray-100 opacity-60'
                          }`}
                        >
                          {/* Priority */}
                          <div className="col-span-1 flex items-center gap-1 text-gray-400">
                            <GripVertical className="w-4 h-4" />
                            <span className="font-mono text-sm">
                              {cap.priority}
                            </span>
                          </div>

                          {/* Active toggle */}
                          <div className="col-span-1">
                            <Switch
                              checked={cap.is_active}
                              onCheckedChange={() => handleToggle(cap.id)}
                            />
                          </div>

                          {/* Name */}
                          <div className="col-span-3">
                            <p className="font-medium text-gray-900">
                              {cap.display_name}
                            </p>
                            <p className="text-xs text-gray-500 truncate mt-0.5">
                              {cap.text.slice(0, 60)}
                              {cap.text.length > 60 ? '...' : ''}
                            </p>
                          </div>

                          {/* Type */}
                          <div className="col-span-2">
                            <span
                              className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${rt.color}`}
                            >
                              {rt.icon}
                              {rt.label}
                            </span>
                          </div>

                          {/* Category */}
                          <div className="col-span-2">
                            <Badge variant="outline">{cap.category}</Badge>
                          </div>

                          {/* Actions */}
                          <div className="col-span-3 flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                router.push(`/capabilities/${cap.id}/edit`)
                              }
                            >
                              <Edit className="w-4 h-4 mr-1" />
                              편집
                            </Button>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => {
                                setDeleteTarget(cap.id);
                                setShowDeleteDialog(true);
                              }}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
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

      {/* Delete Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>서비스 삭제</DialogTitle>
            <DialogDescription>
              정말로 이 서비스를 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
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
