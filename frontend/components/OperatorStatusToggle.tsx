/**
 * Operator Status Toggle Component
 * 
 * Dashboard 운영자 상태 토글 컴포넌트
 */

'use client';

import { useEffect, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { AlertTriangle } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useOperatorStore, OperatorStatus } from '@/store/useOperatorStore';

const DEFAULT_AWAY_MESSAGE = '죄송합니다. 확인 후 별도로 안내드리겠습니다.';

export function OperatorStatusToggle() {
  const router = useRouter();
  const {
    status,
    awayMessage,
    unresolvedHITLCount,
    fetchStatus,
    updateStatus,
    isLoading,
  } = useOperatorStore();

  const [isAwayMessageOpen, setIsAwayMessageOpen] = useState(false);
  const [draftAwayMessage, setDraftAwayMessage] = useState(awayMessage || DEFAULT_AWAY_MESSAGE);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    if (isAwayMessageOpen) {
      setDraftAwayMessage(awayMessage || DEFAULT_AWAY_MESSAGE);
    }
  }, [isAwayMessageOpen, awayMessage]);

  const handleStatusToggle = async (checked: boolean) => {
    const newStatus = checked ? OperatorStatus.AVAILABLE : OperatorStatus.AWAY;
    await updateStatus(newStatus);
  };

  const handleSaveAwayMessage = async () => {
    const message = draftAwayMessage.trim() || DEFAULT_AWAY_MESSAGE;
    await updateStatus(OperatorStatus.AWAY, message);
    setIsAwayMessageOpen(false);
  };

  const isAvailable = status === OperatorStatus.AVAILABLE;

  return (
    <Card className="col-span-12">
      <CardContent className="flex items-center justify-between p-4">
        {/* 왼쪽: 상태 토글 */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">운영자 상태:</span>
            <Badge variant={isAvailable ? 'default' : 'secondary'}>
              {isAvailable ? '🟢 대기중' : '🔴 부재중'}
            </Badge>
          </div>
          <Switch
            checked={isAvailable}
            onCheckedChange={handleStatusToggle}
            disabled={isLoading}
          />
          {!isAvailable && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsAwayMessageOpen(true)}
            >
              ✏️ 메시지 수정
            </Button>
          )}
        </div>

        {/* 오른쪽: 미처리 HITL 알림 */}
        {unresolvedHITLCount > 0 && (
          <Alert variant="destructive" className="flex-1 ml-4 max-w-2xl">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>미처리 HITL 요청 {unresolvedHITLCount}건</AlertTitle>
            <AlertDescription>
              부재중에 발생한 HITL 요청이 있습니다.{' '}
              <Button
                variant="link"
                className="p-0 h-auto text-destructive-foreground underline"
                onClick={() => router.push('/call-history?filter=unresolved')}
              >
                확인하기 →
              </Button>
            </AlertDescription>
          </Alert>
        )}
      </CardContent>

      {/* 부재중 메시지 수정 다이얼로그 */}
      <Dialog open={isAwayMessageOpen} onOpenChange={setIsAwayMessageOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>부재중 안내 메시지</DialogTitle>
            <DialogDescription>
              통화자가 부재중일 때 재생될 안내 문구입니다. 저장 시 부재중 상태가 유지됩니다.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="away-message">메시지</Label>
              <Textarea
                id="away-message"
                value={draftAwayMessage}
                onChange={(e) => setDraftAwayMessage(e.target.value)}
                placeholder={DEFAULT_AWAY_MESSAGE}
                rows={4}
                className="resize-none"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAwayMessageOpen(false)}>
              취소
            </Button>
            <Button onClick={handleSaveAwayMessage} disabled={isLoading}>
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

