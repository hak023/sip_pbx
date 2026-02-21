/**
 * Edit Knowledge Page
 * 
 * 기존 지식 수정
 */

'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ArrowLeft, Save, X, Plus, Trash2 } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { getCurrentUserId } from '@/lib/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CATEGORIES = [
  { value: 'faq', label: 'FAQ', icon: '❓' },
  { value: 'support', label: '고객 지원', icon: '🆘' },
  { value: 'product', label: '제품 정보', icon: '📦' },
  { value: 'policy', label: '정책', icon: '📋' },
  { value: 'hitl', label: 'HITL 저장', icon: '👤' },
  { value: 'manual', label: '수동 추가', icon: '✍️' },
];

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

export default function EditKnowledgePage() {
  const router = useRouter();
  const params = useParams();
  const entryId = params?.id as string;

  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  
  const [originalData, setOriginalData] = useState<KnowledgeEntry | null>(null);
  const [formData, setFormData] = useState({
    text: '',
    category: 'faq',
    keywords: [] as string[],
  });

  const [keywordInput, setKeywordInput] = useState('');

  useEffect(() => {
    if (entryId) {
      fetchKnowledge();
    }
  }, [entryId]);

  const fetchKnowledge = async () => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`${API_URL}/api/knowledge/${entryId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const data = response.data;
      setOriginalData(data);
      setFormData({
        text: data.text,
        category: data.category,
        keywords: data.keywords,
      });
    } catch (error) {
      console.error('Failed to fetch knowledge:', error);
      toast.error('지식 조회 실패');
      router.push('/knowledge');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddKeyword = () => {
    const keyword = keywordInput.trim();
    if (keyword && !formData.keywords.includes(keyword)) {
      setFormData({
        ...formData,
        keywords: [...formData.keywords, keyword],
      });
      setKeywordInput('');
    }
  };

  const handleRemoveKeyword = (index: number) => {
    setFormData({
      ...formData,
      keywords: formData.keywords.filter((_, i) => i !== index),
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!formData.text.trim()) {
      toast.error('지식 내용을 입력해주세요');
      return;
    }

    if (formData.keywords.length === 0) {
      toast.error('최소 1개 이상의 키워드를 입력해주세요');
      return;
    }

    setIsSubmitting(true);

    try {
      const token = localStorage.getItem('token');
      await axios.put(
        `${API_URL}/api/knowledge/${entryId}`,
        {
          text: formData.text,
          category: formData.category,
          keywords: formData.keywords,
          metadata: {
            ...originalData?.metadata,
            updatedBy: getCurrentUserId(),
          },
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      toast.success('지식이 수정되었습니다');
      router.push('/knowledge');
    } catch (error) {
      console.error('Failed to update knowledge:', error);
      toast.error('지식 수정 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    setIsDeleting(true);

    try {
      const token = localStorage.getItem('token');
      await axios.delete(`${API_URL}/api/knowledge/${entryId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      toast.success('지식이 삭제되었습니다');
      router.push('/knowledge');
    } catch (error) {
      console.error('Failed to delete knowledge:', error);
      toast.error('삭제 실패');
    } finally {
      setIsDeleting(false);
    }
  };

  const hasChanges = () => {
    if (!originalData) return false;
    return (
      formData.text !== originalData.text ||
      formData.category !== originalData.category ||
      JSON.stringify(formData.keywords) !== JSON.stringify(originalData.keywords)
    );
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white shadow-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
            <Skeleton className="h-8 w-48" />
          </div>
        </header>
        <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Card>
            <CardContent className="pt-6 space-y-4">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-10 w-full" />
            </CardContent>
          </Card>
        </main>
      </div>
    );
  }

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
                onClick={() => router.push('/knowledge')}
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                뒤로
              </Button>
              <h1 className="text-2xl font-bold text-gray-900">✏️ 지식 수정</h1>
            </div>
            
            {/* Delete Button */}
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" disabled={isDeleting}>
                  <Trash2 className="w-4 h-4 mr-2" />
                  삭제
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>정말 삭제하시겠습니까?</AlertDialogTitle>
                  <AlertDialogDescription>
                    이 작업은 되돌릴 수 없습니다. 지식이 Vector DB에서 영구적으로 삭제됩니다.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>취소</AlertDialogCancel>
                  <AlertDialogAction onClick={handleDelete}>
                    삭제
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Metadata Card */}
        {originalData && (
          <Card className="mb-6 bg-gray-50">
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-600">ID:</span>
                  <span className="ml-2 font-mono">{originalData.id}</span>
                </div>
                <div>
                  <span className="text-gray-600">출처:</span>
                  <span className="ml-2">{originalData.metadata.source}</span>
                </div>
                <div>
                  <span className="text-gray-600">생성:</span>
                  <span className="ml-2">{new Date(originalData.created_at).toLocaleString()}</span>
                </div>
                {originalData.updated_at && (
                  <div>
                    <span className="text-gray-600">수정:</span>
                    <span className="ml-2">{new Date(originalData.updated_at).toLocaleString()}</span>
                  </div>
                )}
                {originalData.metadata.usageCount && (
                  <div>
                    <span className="text-gray-600">사용 횟수:</span>
                    <span className="ml-2 font-semibold">{originalData.metadata.usageCount}회</span>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>지식 편집</CardTitle>
            <CardDescription>
              기존 지식의 내용, 카테고리, 키워드를 수정할 수 있습니다
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Category */}
              <div>
                <Label htmlFor="category">카테고리 *</Label>
                <Select
                  value={formData.category}
                  onValueChange={(value) =>
                    setFormData({ ...formData, category: value })
                  }
                >
                  <SelectTrigger className="mt-2">
                    <SelectValue placeholder="카테고리 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map((cat) => (
                      <SelectItem key={cat.value} value={cat.value}>
                        {cat.icon} {cat.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Text Content */}
              <div>
                <Label htmlFor="text">지식 내용 *</Label>
                <Textarea
                  id="text"
                  value={formData.text}
                  onChange={(e) =>
                    setFormData({ ...formData, text: e.target.value })
                  }
                  rows={6}
                  className="mt-2"
                  required
                />
                <p className="text-sm text-gray-500 mt-1">
                  {formData.text.length}자
                </p>
              </div>

              {/* Keywords */}
              <div>
                <Label htmlFor="keywords">키워드 * (최소 1개)</Label>
                <div className="mt-2 flex gap-2">
                  <Input
                    id="keywords"
                    type="text"
                    value={keywordInput}
                    onChange={(e) => setKeywordInput(e.target.value)}
                    onKeyPress={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleAddKeyword();
                      }
                    }}
                    placeholder="키워드 입력 후 Enter"
                  />
                  <Button
                    type="button"
                    onClick={handleAddKeyword}
                    disabled={!keywordInput.trim()}
                  >
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>

                {formData.keywords.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {formData.keywords.map((keyword, index) => (
                      <Badge key={index} variant="secondary" className="text-sm">
                        {keyword}
                        <button
                          type="button"
                          onClick={() => handleRemoveKeyword(index)}
                          className="ml-2 hover:text-red-600"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* Change Indicator */}
              {hasChanges() && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                  <p className="text-sm text-yellow-800">
                    ⚠️ 변경 사항이 있습니다. 저장하시겠습니까?
                  </p>
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex gap-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.push('/knowledge')}
                  disabled={isSubmitting}
                >
                  취소
                </Button>
                <Button
                  type="submit"
                  disabled={
                    isSubmitting ||
                    !formData.text.trim() ||
                    formData.keywords.length === 0 ||
                    !hasChanges()
                  }
                  className="flex-1"
                >
                  {isSubmitting ? (
                    <>처리 중...</>
                  ) : (
                    <>
                      <Save className="w-4 h-4 mr-2" />
                      저장
                    </>
                  )}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

