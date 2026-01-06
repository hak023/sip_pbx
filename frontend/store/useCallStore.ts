import { create } from 'zustand';
import type { ActiveCall } from '@/types';

interface CallStore {
  activeCalls: ActiveCall[];
  addCall: (call: ActiveCall) => void;
  removeCall: (callId: string) => void;
  updateCall: (callId: string, updates: Partial<ActiveCall>) => void;
  updateCallState: (callId: string, state: string) => void;
}

export const useCallStore = create<CallStore>((set) => ({
  activeCalls: [],
  
  addCall: (call) =>
    set((state) => ({
      activeCalls: [...state.activeCalls, call],
    })),
  
  removeCall: (callId) =>
    set((state) => ({
      activeCalls: state.activeCalls.filter((call) => call.callId !== callId),
    })),
  
  updateCall: (callId, updates) =>
    set((state) => ({
      activeCalls: state.activeCalls.map((call) =>
        call.callId === callId ? { ...call, ...updates } : call
      ),
    })),
  
  updateCallState: (callId, newState) =>
    set((state) => ({
      activeCalls: state.activeCalls.map((call) =>
        call.callId === callId ? { ...call, status: newState as any } : call
      ),
    })),
}));

