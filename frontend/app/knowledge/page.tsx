/**
 * Knowledge Base Management Page
 * 
 * Vector DB에 저장된 지식 항목 조회 및 관리
 */

'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogDescription, 
  DialogFooter 
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Search, Plus, Edit, Trash2, Save, X } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface KnowledgeEntry {
  id: string;
  text: string;
  category: string;
  keywords: string[];
  metadata: {
    source: string;
    usageCount?: number;
    lastUsed?: string;
  };
  created_at: string;
  updated_at?: string;
}

const CATEGORIES = [
  { value: 'all', label: '전체', icon: '📚' },
  { value: 'faq', label: 'FAQ', icon: '❓' },
  { value: 'support', label: '고객 지원', icon: '🆘' },
  { value: 'product', label: '제품 정보', icon: '📦' },
  { value: 'policy', label: '정책', icon: '📋' },
  { value: 'hitl', label: 'HITL 저장', icon: '👤' },
];

export default function KnowledgePage() {
  const router = useRouter();
  const [activeCategory, setActiveCategory] = useState('all');
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeEntry[]>([]);
  const [filteredList, setFilteredList] = useState<KnowledgeEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  
  const [selectedEntry, setSelectedEntry] = useState<KnowledgeEntry | null>(null);
  const [showDetailDialog, setShowDetailDialog] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  useEffect(() => {
    fetchKnowledge();
  }, []);

  useEffect(() => {
    filterKnowledge();
  }, [activeCategory, searchQuery, knowledgeList]);

  const fetchKnowledge = async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      const tenantData = localStorage.getItem('tenant');
      const owner = tenantData ? JSON.parse(tenantData).owner : undefined;
      const response = await axios.get(`${API_URL}/api/knowledge`, {
        params: {
          page: 1,
          limit: 100,
          category: activeCategory === 'all' ? undefined : activeCategory,
          owner,
        },
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      setKnowledgeList(response.data.items);
    } catch (error) {
      console.error('Failed to fetch knowledge:', error);
      toast.error('지식 베이스 조회 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const filterKnowledge = () => {
    let filtered = knowledgeList;

    // 카테고리 필터
    if (activeCategory !== 'all') {
      filtered = filtered.filter(k => k.category === activeCategory);
    }

    // 검색 필터
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(k => 
        k.text.toLowerCase().includes(query) ||
        k.keywords.some(kw => kw.toLowerCase().includes(query))
      );
    }

    setFilteredList(filtered);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;

    try {
      const token = localStorage.getItem('access_token');
      await axios.delete(`${API_URL}/api/knowledge/${deleteTarget}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      toast.success('지식이 삭제되었습니다');
      setShowDeleteDialog(false);
      setDeleteTarget(null);
      fetchKnowledge();
    } catch (error) {
      console.error('Failed to delete knowledge:', error);
      toast.error('삭제 실패');
    }
  };

  const getCategoryInfo = (category: string) => {
    return CATEGORIES.find(c => c.value === category) || CATEGORIES[0];
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-900">📚 지식 베이스</h1>
            <Button onClick={() => router.push('/knowledge/add')}>
              <Plus className="w-4 h-4 mr-2" />
              지식 추가
            </Button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Card>
          <CardHeader>
            <CardTitle>지식 관리</CardTitle>
            <CardDescription>
              Vector DB에 저장된 지식을 조회, 수정, 삭제할 수 있습니다
            </CardDescription>
          </CardHeader>
          <CardContent>
            {/* Search Bar */}
            <div className="mb-6">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-5 h-5" />
                <Input
                  type="text"
                  placeholder="텍스트 또는 키워드로 검색..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10"
                />
              </div>
            </div>

            {/* Category Tabs */}
            <Tabs value={activeCategory} onValueChange={setActiveCategory}>
              <TabsList className="mb-4">
                {CATEGORIES.map(cat => (
                  <TabsTrigger key={cat.value} value={cat.value}>
                    {cat.icon} {cat.label}
                  </TabsTrigger>
                ))}
              </TabsList>

              <TabsContent value={activeCategory}>
                {/* Stats */}
                <div className="mb-4 flex items-center gap-4 text-sm text-gray-600">
                  <span>전체: {knowledgeList.length}개</span>
                  <span>표시: {filteredList.length}개</span>
                </div>

                {/* Knowledge List */}
                {isLoading ? (
                  <div className="text-center py-8">로딩 중...</div>
                ) : filteredList.length === 0 ? (
                  <div className="text-center py-12">
                    <p className="text-gray-500 mb-4">
                      {searchQuery ? '검색 결과가 없습니다' : '지식이 없습니다'}
                    </p>
                    <Button onClick={() => router.push('/knowledge/add')}>
                      <Plus className="w-4 h-4 mr-2" />
                      첫 번째 지식 추가하기
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {filteredList.map((entry) => {
                      const catInfo = getCategoryInfo(entry.category);
                      return (
                        <div
                          key={entry.id}
                          className="border rounded-lg p-4 hover:bg-gray-50 transition"
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <div className="flex items-center gap-2 mb-2">
                                <Badge variant="outline">
                                  {catInfo.icon} {catInfo.label}
                                </Badge>
                                <Badge variant="secondary">
                                  {entry.metadata.source}
                                </Badge>
                                {entry.metadata.usageCount && (
                                  <Badge variant="default">
                                    사용 {entry.metadata.usageCount}회
                                  </Badge>
                                )}
                              </div>
                              <p className="text-sm text-gray-700 mb-2 line-clamp-2">
                                {entry.text}
                              </p>
                              {entry.keywords.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {entry.keywords.slice(0, 5).map((kw, i) => (
                                    <span
                                      key={i}
                                      className="text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded"
                                    >
                                      {kw}
                                    </span>
                                  ))}
                                  {entry.keywords.length > 5 && (
                                    <span className="text-xs text-gray-500">
                                      +{entry.keywords.length - 5}
                                    </span>
                                  )}
                                </div>
                              )}
                            </div>
                            <div className="flex gap-2 ml-4">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setSelectedEntry(entry);
                                  setShowDetailDialog(true);
                                }}
                              >
                                <Edit className="w-4 h-4" />
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => router.push(`/knowledge/${entry.id}/edit`)}
                              >
                                수정
                              </Button>
                              <Button
                                size="sm"
                                variant="destructive"
                                onClick={() => {
                                  setDeleteTarget(entry.id);
                                  setShowDeleteDialog(true);
                                }}
                              >
                                <Trash2 className="w-4 h-4" />
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

      {/* Detail Dialog */}
      <Dialog open={showDetailDialog} onOpenChange={setShowDetailDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>지식 상세</DialogTitle>
            <DialogDescription>ID: {selectedEntry?.id}</DialogDescription>
          </DialogHeader>

          {selectedEntry && (
            <div className="space-y-4">
              <div>
                <h3 className="font-semibold mb-2">카테고리</h3>
                <Badge variant="outline">
                  {getCategoryInfo(selectedEntry.category).icon}{' '}
                  {getCategoryInfo(selectedEntry.category).label}
                </Badge>
              </div>

              <div>
                <h3 className="font-semibold mb-2">내용</h3>
                <ScrollArea className="h-32 border rounded p-3 bg-gray-50">
                  {selectedEntry.text}
                </ScrollArea>
              </div>

              <div>
                <h3 className="font-semibold mb-2">키워드</h3>
                <div className="flex flex-wrap gap-2">
                  {selectedEntry.keywords.map((kw, i) => (
                    <Badge key={i} variant="secondary">
                      {kw}
                    </Badge>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="font-semibold mb-2">메타데이터</h3>
                <div className="text-sm space-y-1">
                  <p>출처: {selectedEntry.metadata.source}</p>
                  {selectedEntry.metadata.usageCount && (
                    <p>사용 횟수: {selectedEntry.metadata.usageCount}회</p>
                  )}
                  {selectedEntry.metadata.lastUsed && (
                    <p>마지막 사용: {new Date(selectedEntry.metadata.lastUsed).toLocaleString()}</p>
                  )}
                  <p>생성: {new Date(selectedEntry.created_at).toLocaleString()}</p>
                  {selectedEntry.updated_at && (
                    <p>수정: {new Date(selectedEntry.updated_at).toLocaleString()}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDetailDialog(false)}>
              닫기
            </Button>
            <Button onClick={() => {
              if (selectedEntry) {
                router.push(`/knowledge/${selectedEntry.id}/edit`);
              }
            }}>
              수정하기
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>지식 삭제</DialogTitle>
            <DialogDescription>
              정말로 이 지식을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
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

