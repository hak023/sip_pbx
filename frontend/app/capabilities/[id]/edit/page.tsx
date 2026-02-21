/**
 * 서비스 수정 페이지
 *
 * 기존 AI Capability를 수정
 */

'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { ArrowLeft, Save, Plus, X, Trash2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const RESPONSE_TYPES = [
  { value: 'info', label: '📄 정보 안내' },
  { value: 'api_call', label: '🔗 API 연동' },
  { value: 'transfer', label: '📞 상담원 연결' },
  { value: 'collect', label: '📝 정보 수집' },
];

export default function EditCapabilityPage() {
  const router = useRouter();
  const params = useParams();
  const capId = params.id as string;

  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [keywordInput, setKeywordInput] = useState('');

  const [form, setForm] = useState({
    display_name: '',
    text: '',
    category: '',
    response_type: 'info',
    keywords: [] as string[],
    priority: 50,
    is_active: true,
    api_endpoint: '',
    api_method: 'GET',
    transfer_to: '',
  });

  useEffect(() => {
    const fetchCapability = async () => {
      try {
        const token = localStorage.getItem('access_token');
        const res = await axios.get(`${API_URL}/api/capabilities/`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const cap = res.data.items.find(
          (c: { id: string }) => c.id === capId
        );
        if (cap) {
          setForm({
            display_name: cap.display_name || '',
            text: cap.text || '',
            category: cap.category || '',
            response_type: cap.response_type || 'info',
            keywords: cap.keywords || [],
            priority: cap.priority || 50,
            is_active: cap.is_active ?? true,
            api_endpoint: cap.api_endpoint || '',
            api_method: cap.api_method || 'GET',
            transfer_to: cap.transfer_to || '',
          });
        } else {
          toast.error('서비스를 찾을 수 없습니다');
          router.push('/capabilities');
        }
      } catch {
        toast.error('서비스 조회 실패');
      } finally {
        setIsLoading(false);
      }
    };
    fetchCapability();
  }, [capId, router]);

  const handleAddKeyword = () => {
    const kw = keywordInput.trim();
    if (kw && !form.keywords.includes(kw)) {
      setForm({ ...form, keywords: [...form.keywords, kw] });
      setKeywordInput('');
    }
  };

  const handleRemoveKeyword = (idx: number) => {
    setForm({ ...form, keywords: form.keywords.filter((_, i) => i !== idx) });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.display_name.trim() || !form.text.trim() || !form.category.trim()) {
      toast.error('필수 항목을 입력해주세요');
      return;
    }

    setIsSubmitting(true);
    try {
      const token = localStorage.getItem('access_token');
      const body: Record<string, unknown> = {
        display_name: form.display_name,
        text: form.text,
        category: form.category,
        response_type: form.response_type,
        keywords: form.keywords,
        priority: form.priority,
        is_active: form.is_active,
      };

      if (form.response_type === 'api_call') {
        body.api_endpoint = form.api_endpoint;
        body.api_method = form.api_method;
      }
      if (form.response_type === 'transfer') {
        body.transfer_to = form.transfer_to;
      }

      await axios.put(`${API_URL}/api/capabilities/${capId}`, body, {
        headers: { Authorization: `Bearer ${token}` },
      });

      toast.success('서비스가 수정되었습니다');
      router.push('/capabilities');
    } catch {
      toast.error('서비스 수정 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    try {
      const token = localStorage.getItem('access_token');
      await axios.delete(`${API_URL}/api/capabilities/${capId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      toast.success('서비스가 삭제되었습니다');
      router.push('/capabilities');
    } catch {
      toast.error('삭제 실패');
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-500">로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => router.push('/capabilities')}
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                뒤로
              </Button>
              <h1 className="text-2xl font-bold text-gray-900">
                ✏️ 서비스 수정
              </h1>
            </div>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowDeleteDialog(true)}
            >
              <Trash2 className="w-4 h-4 mr-2" />
              삭제
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Card>
          <CardHeader>
            <CardTitle>서비스 정보 수정</CardTitle>
            <CardDescription>ID: {capId}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Display Name */}
              <div>
                <Label htmlFor="display_name">서비스명 *</Label>
                <Input
                  id="display_name"
                  value={form.display_name}
                  onChange={(e) =>
                    setForm({ ...form, display_name: e.target.value })
                  }
                  className="mt-2"
                  required
                />
              </div>

              {/* Category + Response Type */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>카테고리 *</Label>
                  <Input
                    value={form.category}
                    onChange={(e) =>
                      setForm({ ...form, category: e.target.value })
                    }
                    className="mt-2"
                    required
                  />
                </div>
                <div>
                  <Label>응답 유형 *</Label>
                  <Select
                    value={form.response_type}
                    onValueChange={(v) =>
                      setForm({ ...form, response_type: v })
                    }
                  >
                    <SelectTrigger className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RESPONSE_TYPES.map((rt) => (
                        <SelectItem key={rt.value} value={rt.value}>
                          {rt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Text */}
              <div>
                <Label>안내 내용 *</Label>
                <Textarea
                  value={form.text}
                  onChange={(e) => setForm({ ...form, text: e.target.value })}
                  rows={5}
                  className="mt-2"
                  required
                />
              </div>

              {/* Keywords */}
              <div>
                <Label>키워드</Label>
                <div className="mt-2 flex gap-2">
                  <Input
                    value={keywordInput}
                    onChange={(e) => setKeywordInput(e.target.value)}
                    onKeyDown={(e) => {
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
                {form.keywords.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {form.keywords.map((kw, i) => (
                      <Badge key={i} variant="secondary">
                        {kw}
                        <button
                          type="button"
                          onClick={() => handleRemoveKeyword(i)}
                          className="ml-1 hover:text-red-600"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* Conditional fields */}
              {form.response_type === 'api_call' && (
                <Card className="bg-purple-50 border-purple-200">
                  <CardContent className="pt-6 space-y-4">
                    <h3 className="font-semibold text-purple-900">
                      🔗 API 연동 설정
                    </h3>
                    <div>
                      <Label>API URL</Label>
                      <Input
                        value={form.api_endpoint}
                        onChange={(e) =>
                          setForm({ ...form, api_endpoint: e.target.value })
                        }
                        className="mt-1"
                      />
                    </div>
                    <div>
                      <Label>HTTP 메서드</Label>
                      <Select
                        value={form.api_method}
                        onValueChange={(v) =>
                          setForm({ ...form, api_method: v })
                        }
                      >
                        <SelectTrigger className="mt-1">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="GET">GET</SelectItem>
                          <SelectItem value="POST">POST</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </CardContent>
                </Card>
              )}

              {form.response_type === 'transfer' && (
                <Card className="bg-green-50 border-green-200">
                  <CardContent className="pt-6 space-y-4">
                    <h3 className="font-semibold text-green-900">
                      📞 상담원 연결 설정
                    </h3>
                    <div>
                      <Label>연결 대상</Label>
                      <Input
                        value={form.transfer_to}
                        onChange={(e) =>
                          setForm({ ...form, transfer_to: e.target.value })
                        }
                        className="mt-1"
                      />
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Priority & Active */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label>우선순위</Label>
                  <Input
                    type="number"
                    min={1}
                    max={99}
                    value={form.priority}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        priority: parseInt(e.target.value) || 50,
                      })
                    }
                    className="mt-2"
                  />
                </div>
                <div className="flex items-end gap-3 pb-2">
                  <Label>활성화</Label>
                  <Switch
                    checked={form.is_active}
                    onCheckedChange={(v) => setForm({ ...form, is_active: v })}
                  />
                  <span className="text-sm">
                    {form.is_active ? '🟢 활성' : '🔴 비활성'}
                  </span>
                </div>
              </div>

              {/* Buttons */}
              <div className="flex gap-3 pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.push('/capabilities')}
                  disabled={isSubmitting}
                >
                  취소
                </Button>
                <Button type="submit" disabled={isSubmitting} className="flex-1">
                  {isSubmitting ? (
                    '처리 중...'
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

      {/* Delete Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>서비스 삭제</DialogTitle>
            <DialogDescription>
              정말로 이 서비스를 삭제하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
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
