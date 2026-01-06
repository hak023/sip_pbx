import { create } from 'zustand';
import type { HITLRequest } from '@/types';

interface HITLStore {
  requests: HITLRequest[];
  addRequest: (request: HITLRequest) => void;
  removeRequest: (callId: string) => void;
  updateRequest: (callId: string, updates: Partial<HITLRequest>) => void;
}

export const useHITLStore = create<HITLStore>((set) => ({
  requests: [],
  
  addRequest: (request) =>
    set((state) => ({
      requests: [...state.requests, request],
    })),
  
  removeRequest: (callId) =>
    set((state) => ({
      requests: state.requests.filter((req) => req.callId !== callId),
    })),
  
  updateRequest: (callId, updates) =>
    set((state) => ({
      requests: state.requests.map((req) =>
        req.callId === callId ? { ...req, ...updates } : req
      ),
    })),
}));

