/**
 * Operator Status Store
 * 
 * 운영자 상태 관리 Zustand Store
 */

import { create } from 'zustand';
import axios from 'axios';
import { toast } from 'sonner';

export enum OperatorStatus {
  AVAILABLE = 'available',
  AWAY = 'away',
  BUSY = 'busy',
  OFFLINE = 'offline',
}

interface OperatorState {
  status: OperatorStatus;
  awayMessage: string;
  statusChangedAt: Date | null;
  unresolvedHITLCount: number;
  isLoading: boolean;
}

interface OperatorActions {
  fetchStatus: () => Promise<void>;
  updateStatus: (status: OperatorStatus, awayMessage?: string) => Promise<void>;
  incrementUnresolvedCount: () => void;
  decrementUnresolvedCount: () => void;
}

type OperatorStore = OperatorState & OperatorActions;

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const useOperatorStore = create<OperatorStore>((set, get) => ({
  // State
  status: OperatorStatus.OFFLINE,
  awayMessage: '죄송합니다. 확인 후 별도로 안내드리겠습니다.',
  statusChangedAt: null,
  unresolvedHITLCount: 0,
  isLoading: false,

  // Actions
  fetchStatus: async () => {
    set({ isLoading: true });
    
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`${API_URL}/api/operator/status`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      set({
        status: response.data.status,
        awayMessage: response.data.away_message,
        statusChangedAt: new Date(response.data.status_changed_at),
        unresolvedHITLCount: response.data.unresolved_hitl_count,
        isLoading: false,
      });
    } catch (error) {
      console.error('Failed to fetch operator status:', error);
      toast.error('운영자 상태 조회 실패');
      set({ isLoading: false });
    }
  },

  updateStatus: async (status: OperatorStatus, awayMessage?: string) => {
    set({ isLoading: true });

    try {
      const token = localStorage.getItem('token');
      const response = await axios.put(
        `${API_URL}/api/operator/status`,
        {
          status,
          away_message: awayMessage || get().awayMessage,
        },
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );

      set({
        status: response.data.status,
        awayMessage: response.data.away_message,
        statusChangedAt: new Date(response.data.status_changed_at),
        unresolvedHITLCount: response.data.unresolved_hitl_count,
        isLoading: false,
      });

      // 상태 변경 알림
      if (status === OperatorStatus.AVAILABLE) {
        toast.success('🟢 대기중 상태로 변경되었습니다');
      } else if (status === OperatorStatus.AWAY) {
        toast.info('🔴 부재중 상태로 변경되었습니다');
      }
    } catch (error) {
      console.error('Failed to update operator status:', error);
      toast.error('운영자 상태 변경 실패');
      set({ isLoading: false });
    }
  },

  incrementUnresolvedCount: () => {
    set((state) => ({
      unresolvedHITLCount: state.unresolvedHITLCount + 1,
    }));
  },

  decrementUnresolvedCount: () => {
    set((state) => ({
      unresolvedHITLCount: Math.max(0, state.unresolvedHITLCount - 1),
    }));
  },
}));

