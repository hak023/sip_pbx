/**
 * Add Knowledge Page
 * 
 * 새로운 지식을 Vector DB에 추가
 */

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
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
import { ArrowLeft, Save, X, Plus } from 'lucide-react';
import { getCurrentUserId } from '@/lib/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CATEGORIES = [
  { value: 'faq', label: 'FAQ', icon: '❓' },
  { value: 'support', label: '고객 지원', icon: '🆘' },
  { value: 'product', label: '제품 정보', icon: '📦' },
  { value: 'policy', label: '정책', icon: '📋' },
  { value: 'manual', label: '수동 추가', icon: '✍️' },
];

export default function AddKnowledgePage() {
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  const [formData, setFormData] = useState({
    text: '',
    category: 'faq',
    keywords: [] as string[],
  });

  const [keywordInput, setKeywordInput] = useState('');

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
      const token = localStorage.getItem('access_token');
      await axios.post(
        `${API_URL}/api/knowledge`,
        {
          text: formData.text,
          category: formData.category,
          keywords: formData.keywords,
          metadata: {
            source: 'manual',
            addedBy: getCurrentUserId(),
          },
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      toast.success('지식이 추가되었습니다');
      router.push('/knowledge');
    } catch (error) {
      console.error('Failed to add knowledge:', error);
      toast.error('지식 추가 실패');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.push('/knowledge')}
            >
              <ArrowLeft className="w-4 h-4 mr-2" />
              뒤로
            </Button>
            <h1 className="text-2xl font-bold text-gray-900">✍️ 지식 추가</h1>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Card>
          <CardHeader>
            <CardTitle>새로운 지식 추가</CardTitle>
            <CardDescription>
              AI가 활용할 수 있는 새로운 지식을 Vector DB에 추가합니다
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
                  placeholder="예: 영업시간은 평일 오전 9시부터 오후 6시까지입니다. 주말과 공휴일은 휴무입니다."
                  rows={6}
                  className="mt-2"
                  required
                />
                <p className="text-sm text-gray-500 mt-1">
                  {formData.text.length}자
                  {formData.text.length > 0 && formData.text.length < 20 && (
                    <span className="text-orange-600 ml-2">
                      ⚠️ 너무 짧습니다 (최소 20자 권장)
                    </span>
                  )}
                  {formData.text.length > 500 && (
                    <span className="text-orange-600 ml-2">
                      ⚠️ 너무 깁니다 (최대 500자 권장)
                    </span>
                  )}
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

                <p className="text-sm text-gray-500 mt-1">
                  예: 영업시간, 운영시간, 오픈 시간
                </p>
              </div>

              {/* Preview */}
              {formData.text && formData.keywords.length > 0 && (
                <div className="border rounded-lg p-4 bg-blue-50">
                  <h3 className="font-semibold mb-2 text-blue-900">✨ 미리보기</h3>
                  <div className="space-y-2">
                    <div>
                      <span className="text-sm font-medium text-blue-700">카테고리:</span>
                      <span className="ml-2 text-sm text-blue-900">
                        {CATEGORIES.find((c) => c.value === formData.category)?.label}
                      </span>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-blue-700">내용:</span>
                      <p className="text-sm text-blue-900 mt-1">{formData.text}</p>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-blue-700">키워드:</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {formData.keywords.map((kw, i) => (
                          <Badge key={i} variant="outline">
                            {kw}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
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
                    formData.keywords.length === 0
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

        {/* Help Card */}
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="text-lg">💡 작성 가이드</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            <p>
              <strong>1. 명확하고 구체적으로 작성</strong>
              <br />
              "영업시간은 평일 9시~6시" 보다는 "영업시간은 평일 오전 9시부터 오후
              6시까지입니다. 주말과 공휴일은 휴무입니다." 처럼 구체적으로 작성하세요.
            </p>
            <p>
              <strong>2. 키워드를 풍부하게</strong>
              <br />
              사용자가 물어볼 수 있는 다양한 표현을 키워드로 추가하세요. (예:
              "영업시간", "운영시간", "오픈시간", "몇시부터")
            </p>
            <p>
              <strong>3. 적절한 분량</strong>
              <br />
              너무 짧으면 정보가 부족하고, 너무 길면 검색 성능이 떨어집니다. 100-300자
              정도가 적당합니다.
            </p>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

