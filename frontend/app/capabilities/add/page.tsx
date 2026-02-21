/**
 * 서비스 추가 페이지
 *
 * AI Capability를 VectorDB에 추가
 */

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
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
import { ArrowLeft, Save, Plus, X } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const RESPONSE_TYPES = [
  { value: 'info', label: '📄 정보 안내', desc: 'VectorDB 내용으로 TTS 응답' },
  {
    value: 'api_call',
    label: '🔗 API 연동',
    desc: '외부 API 호출 후 결과 안내',
  },
  {
    value: 'transfer',
    label: '📞 상담원 연결',
    desc: 'SIP 호 전환으로 상담원 연결',
  },
  {
    value: 'collect',
    label: '📝 정보 수집',
    desc: '멀티턴 질문으로 정보 수집',
  },
];

export default function AddCapabilityPage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
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
    phone_display: '',
  });

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
    if (!form.display_name.trim()) {
      toast.error('서비스명을 입력해주세요');
      return;
    }
    if (!form.text.trim()) {
      toast.error('안내 내용을 입력해주세요');
      return;
    }
    if (!form.category.trim()) {
      toast.error('카테고리를 입력해주세요');
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

      if (form.response_type === 'api_call' && form.api_endpoint) {
        body.api_endpoint = form.api_endpoint;
        body.api_method = form.api_method;
      }
      if (form.response_type === 'transfer' && form.transfer_to) {
        body.transfer_to = form.transfer_to;
        if (form.phone_display) {
          body.phone_display = form.phone_display;
        }
      }

      await axios.post(`${API_URL}/api/capabilities/`, body, {
        headers: { Authorization: `Bearer ${token}` },
      });

      toast.success('서비스가 추가되었습니다');
      router.push('/capabilities');
    } catch (error) {
      console.error('Failed to add capability:', error);
      toast.error('서비스 추가 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
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
              ➕ 서비스 추가
            </h1>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Card>
          <CardHeader>
            <CardTitle>새 AI 서비스 등록</CardTitle>
            <CardDescription>
              AI가 전화 상담 시 안내할 수 있는 서비스를 등록합니다
            </CardDescription>
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
                  placeholder="예: 매장 주차 안내"
                  className="mt-2"
                  required
                />
                <p className="text-xs text-gray-500 mt-1">
                  가이드 멘트에 표시되는 이름입니다
                </p>
              </div>

              {/* Category + Response Type */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="category">카테고리 *</Label>
                  <Input
                    id="category"
                    value={form.category}
                    onChange={(e) =>
                      setForm({ ...form, category: e.target.value })
                    }
                    placeholder="예: parking, hours, menu"
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
                  <p className="text-xs text-gray-500 mt-1">
                    {
                      RESPONSE_TYPES.find((r) => r.value === form.response_type)
                        ?.desc
                    }
                  </p>
                </div>
              </div>

              {/* Text */}
              <div>
                <Label htmlFor="text">안내 내용 *</Label>
                <Textarea
                  id="text"
                  value={form.text}
                  onChange={(e) => setForm({ ...form, text: e.target.value })}
                  placeholder="예: 지하 1~3층에 고객 전용 주차장이 있으며, 2시간 무료 주차가 가능합니다."
                  rows={5}
                  className="mt-2"
                  required
                />
                <p className="text-xs text-gray-500 mt-1">
                  {form.text.length}자 · AI가 이 내용을 바탕으로 답변합니다
                </p>
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

              {/* Response type specific fields */}
              {form.response_type === 'api_call' && (
                <Card className="bg-purple-50 border-purple-200">
                  <CardContent className="pt-6 space-y-4">
                    <h3 className="font-semibold text-purple-900">
                      🔗 API 연동 설정
                    </h3>
                    <div>
                      <Label>API URL *</Label>
                      <Input
                        value={form.api_endpoint}
                        onChange={(e) =>
                          setForm({ ...form, api_endpoint: e.target.value })
                        }
                        placeholder="예: https://your-api.example.com/data"
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
                      📞 호 연결 설정
                    </h3>
                    <div>
                      <Label>연결 대상 (SIP URI, 내선번호 또는 전화번호) *</Label>
                      <Input
                        value={form.transfer_to}
                        onChange={(e) =>
                          setForm({ ...form, transfer_to: e.target.value })
                        }
                        placeholder="sip:8001@pbx.local, 8001, 또는 02-1234-5678"
                        className="mt-1"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        내선번호(예: 8001), SIP URI(예: sip:dev@pbx.local), 외부번호(예: +821012345678) 지원
                      </p>
                    </div>
                    <div>
                      <Label>표시 번호 (발신자에게 안내할 번호)</Label>
                      <Input
                        value={form.phone_display}
                        onChange={(e) =>
                          setForm({ ...form, phone_display: e.target.value })
                        }
                        placeholder="8001"
                        className="mt-1"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        AI가 발신자에게 안내할 때 표시되는 번호 (비어있으면 연결 대상 값 사용)
                      </p>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Priority & Active */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="priority">우선순위 (1=최우선)</Label>
                  <Input
                    id="priority"
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
                  <span className="text-sm text-gray-600">
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
    </div>
  );
}
