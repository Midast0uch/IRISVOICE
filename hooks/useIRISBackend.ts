/**
 * React Query hooks for IRISVOICE backend data
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { irisApi } from "@/lib/iris-api";

const STALE = 10_000; // 10 s

export function useBackendOnline() {
  return useQuery({
    queryKey: ["iris", "online"],
    queryFn: () => irisApi.isOnline(),
    refetchInterval: 30_000, // reduced from 5s — backend pushes updates via WS system_status
    staleTime: 0,
  });
}

export function useGitStatus() {
  return useQuery({
    queryKey: ["iris", "git", "status"],
    queryFn: () => irisApi.getGitStatus(),
    refetchInterval: 60_000, // reduced from 15s
    staleTime: STALE,
    retry: false,
  });
}

export function useGitLog(limit = 20) {
  return useQuery({
    queryKey: ["iris", "git", "log", limit],
    queryFn: () => irisApi.getGitLog(limit),
    refetchInterval: 60_000, // reduced from 30s
    staleTime: STALE,
    retry: false,
  });
}

export function useCommitAll() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) => irisApi.commitAll(message),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["iris", "git"] });
    },
  });
}

export function useRollback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: string) => irisApi.rollback(target),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["iris", "git"] });
    },
  });
}

export function usePendingWrites() {
  return useQuery({
    queryKey: ["iris", "diff", "pending"],
    queryFn: () => irisApi.getPendingWrites(),
    refetchInterval: 30_000, // reduced from 5s
    staleTime: 0,
    retry: false,
  });
}

export function useApproveWrite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (_id?: string) => irisApi.approveWrite(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["iris", "diff"] });
      qc.invalidateQueries({ queryKey: ["iris", "git"] });
    },
  });
}

export function useRejectWrite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (_id?: string) => irisApi.rejectWrite(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["iris", "diff"] });
    },
  });
}

export function useProjects() {
  return useQuery({
    queryKey: ["iris", "projects"],
    queryFn: () => irisApi.getProjects(),
    staleTime: 60_000,
    retry: false,
  });
}
