/**
 * Call History Page
 * 
 * 통화 이력 페이지 (미처리 HITL 필터 포함)
 */

'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import axios from 'axios';
import { toast } from 'sonner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { format } from 'date-fns';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface CallHistoryItem {
  call_id: string;
  caller_id: string;
  callee_id: string;
  start_time: string;
  end_time?: string;
  hitl_status?: string;
  user_question?: string;
  ai_confidence?: number;
  timestamp?: string;
}

interface CallDetail {
  call_info: any;
  transcripts: Array<{
    speaker: string;
    text: string;
    timestamp: string;
  }>;
  hitl_request?: any;
}

export default function CallHistoryPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const filterParam = searchParams?.get('filter') || 'all';

  const [activeTab, setActiveTab] = useState<string>(filterParam);
  const [callHistory, setCallHistory] = useState<CallHistoryItem[]>([]);
  const [unresolvedCount, setUnresolvedCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [selectedCall, setSelectedCall] = useState<CallDetail | null>(null);
  const [showCallDetail, setShowCallDetail] = useState(false);
  const [operatorNote, setOperatorNote] = useState('');
  const [followUpRequired, setFollowUpRequired] = useState(false);

  useEffect(() => {
    fetchCallHistory(activeTab);
  }, [activeTab]);

  const fetchCallHistory = async (filter: string) => {
    setIsLoading(true);
    try {
      const token = localStorage.getItem('access_token');
      // 로그인된 테넌트의 착신번호(owner)로 필터링
      let callee: string | undefined;
      try {
        const tenantStr = localStorage.getItem('tenant');
        if (tenantStr) {
          const tenant = JSON.parse(tenantStr);
          callee = tenant.owner;
        }
      } catch {}
      
      const response = await axios.get(`${API_URL}/api/call-history`, {
        params: {
          page: 1,
          limit: 50,
          unresolved_hitl: filter === 'all' ? undefined : filter,
          callee,
        },
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      setCallHistory(response.data.items);

      // 미처리 카운트 업데이트
      if (filter === 'unresolved') {
        setUnresolvedCount(response.data.total);
      }
    } catch (error) {
      console.error('Failed to fetch call history:', error);
      toast.error('통화 이력 조회 실패');
    } finally {
      setIsLoading(false);
    }
  };

  const showCallDetailDialog = async (callId: string) => {
    try {
      const token = localStorage.getItem('access_token');
      const response = await axios.get(`${API_URL}/api/call-history/${callId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      setSelectedCall(response.data);
      setOperatorNote('');
      setFollowUpRequired(false);
      setShowCallDetail(true);
    } catch (error) {
      console.error('Failed to fetch call detail:', error);
      toast.error('통화 상세 조회 실패');
    }
  };

  const handleSaveNote = async () => {
    if (!selectedCall || !operatorNote.trim()) {
      toast.error('메모를 입력해주세요');
      return;
    }

    try {
      const token = localStorage.getItem('access_token');
      await axios.post(
        `${API_URL}/api/call-history/${selectedCall.call_info.call_id}/note`,
        {
          operator_note: operatorNote,
          follow_up_required: followUpRequired,
          follow_up_phone: selectedCall.call_info.caller_id,
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      toast.success('메모가 저장되었습니다');
      setShowCallDetail(false);
      fetchCallHistory(activeTab);
    } catch (error) {
      console.error('Failed to save note:', error);
      toast.error('메모 저장 실패');
    }
  };

  const handleResolve = async () => {
    if (!selectedCall) return;

    try {
      const token = localStorage.getItem('access_token');
      await axios.put(
        `${API_URL}/api/call-history/${selectedCall.call_info.call_id}/resolve`,
        {},
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      toast.success('처리 완료되었습니다');
      setShowCallDetail(false);
      fetchCallHistory(activeTab);
    } catch (error) {
      console.error('Failed to resolve:', error);
      toast.error('처리 완료 실패');
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <h1 className="text-2xl font-bold text-gray-900">📋 통화 이력</h1>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <Card>
          <CardHeader>
            <CardTitle>통화 이력 관리</CardTitle>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList className="mb-4">
                <TabsTrigger value="all">전체 통화</TabsTrigger>
                <TabsTrigger value="unresolved">
                  미처리 HITL
                  {unresolvedCount > 0 && (
                    <Badge variant="destructive" className="ml-2">
                      {unresolvedCount}
                    </Badge>
                  )}
                </TabsTrigger>
                <TabsTrigger value="noted">메모 작성됨</TabsTrigger>
                <TabsTrigger value="resolved">처리 완료</TabsTrigger>
              </TabsList>

              <TabsContent value={activeTab}>
                {isLoading ? (
                  <div className="text-center py-8">로딩 중...</div>
                ) : callHistory.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    통화 이력이 없습니다
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            통화 시각
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            발신자
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            질문
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            AI 신뢰도
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            상태
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            액션
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {callHistory.map((call) => (
                          <tr key={call.call_id} className="hover:bg-gray-50">
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {format(new Date(call.start_time), 'yyyy-MM-dd HH:mm:ss')}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                              {call.caller_id}
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-900 max-w-md truncate">
                              {call.user_question || '-'}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                              {call.ai_confidence !== undefined ? (
                                <Badge
                                  variant={
                                    call.ai_confidence < 0.5
                                      ? 'destructive'
                                      : call.ai_confidence < 0.7
                                      ? 'secondary'
                                      : 'default'
                                  }
                                >
                                  {(call.ai_confidence * 100).toFixed(0)}%
                                </Badge>
                              ) : (
                                '-'
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                              {call.hitl_status ? (
                                <Badge variant="outline">{call.hitl_status}</Badge>
                              ) : (
                                '-'
                              )}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                              <Button
                                size="sm"
                                onClick={() => showCallDetailDialog(call.call_id)}
                              >
                                상세 보기
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </main>

      {/* Call Detail Dialog */}
      <Dialog open={showCallDetail} onOpenChange={setShowCallDetail}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>통화 상세 - {selectedCall?.call_info.call_id}</DialogTitle>
            <DialogDescription>
              발신자: {selectedCall?.call_info.caller_id} | 시각:{' '}
              {selectedCall && format(new Date(selectedCall.call_info.start_time), 'yyyy-MM-dd HH:mm:ss')}
            </DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-4">
            {/* 왼쪽: HITL 요청 정보 */}
            <div>
              {selectedCall?.hitl_request && (
                <>
                  <h3 className="font-semibold mb-2">사용자 질문</h3>
                  <div className="bg-gray-100 p-3 rounded mb-4">
                    {selectedCall.hitl_request.user_question}
                  </div>

                  <h3 className="font-semibold mb-2">AI 신뢰도</h3>
                  <Badge
                    variant={
                      selectedCall.hitl_request.ai_confidence < 0.5
                        ? 'destructive'
                        : 'secondary'
                    }
                    className="mb-4"
                  >
                    {(selectedCall.hitl_request.ai_confidence * 100).toFixed(0)}%
                  </Badge>
                </>
              )}
            </div>

            {/* 오른쪽: 통화 전체 내용 */}
            <div>
              <h3 className="font-semibold mb-2">통화 전체 내용 (STT)</h3>
              <ScrollArea className="h-64 border rounded p-2 bg-gray-50">
                {selectedCall?.transcripts.map((t, i) => (
                  <div
                    key={i}
                    className={`mb-2 ${t.speaker === 'user' ? 'text-right' : ''}`}
                  >
                    <span
                      className={`inline-block p-2 rounded text-sm ${
                        t.speaker === 'user' ? 'bg-blue-100' : 'bg-gray-200'
                      }`}
                    >
                      {t.speaker === 'user' ? '발신자' : 'AI'}: {t.text}
                    </span>
                  </div>
                ))}
              </ScrollArea>
            </div>
          </div>

          {/* 하단: 메모 작성 */}
          <div className="mt-4">
            <Label htmlFor="operator-note">운영자 메모</Label>
            <Textarea
              id="operator-note"
              value={operatorNote}
              onChange={(e) => setOperatorNote(e.target.value)}
              placeholder="이 통화에 대한 메모를 작성하세요..."
              rows={3}
              className="mt-2"
            />

            <div className="flex items-center gap-2 mt-2">
              <Checkbox
                id="follow-up"
                checked={followUpRequired}
                onCheckedChange={(checked) => setFollowUpRequired(!!checked)}
              />
              <Label htmlFor="follow-up">후속 조치 필요 (고객에게 전화)</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCallDetail(false)}>
              취소
            </Button>
            <Button onClick={handleSaveNote}>메모 저장</Button>
            {followUpRequired && (
              <Button variant="default" onClick={handleResolve}>
                처리 완료
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

