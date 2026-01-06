/**
 * Operator Status Toggle Component
 * 
 * Dashboard 운영자 상태 토글 컴포넌트
 */

'use client';

import { useEffect } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { AlertTriangle } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useOperatorStore, OperatorStatus } from '@/store/useOperatorStore';

export function OperatorStatusToggle() {
  const router = useRouter();
  const {
    status,
    unresolvedHITLCount,
    fetchStatus,
    updateStatus,
    isLoading,
  } = useOperatorStore();

  useEffect(() => {
    // 컴포넌트 마운트 시 운영자 상태 조회
    fetchStatus();
  }, [fetchStatus]);

  const handleStatusToggle = async (checked: boolean) => {
    const newStatus = checked ? OperatorStatus.AVAILABLE : OperatorStatus.AWAY;
    await updateStatus(newStatus);
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
              onClick={() => {
                // TODO: 부재중 메시지 수정 다이얼로그 표시
                console.log('Show away message dialog');
              }}
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
    </Card>
  );
}

