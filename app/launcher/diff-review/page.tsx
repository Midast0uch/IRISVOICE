"use client";

import { Activity, Check, X, FileCode, Wifi, WifiOff, GitMerge, Trash2, AlertTriangle } from "lucide-react";
import { useState } from "react";
import { SectionHeader, StatusBadge } from "@/components/launcher/DashboardPrimitives";
import { LiquidIcon } from "@/components/launcher/LiquidIcon";
import { Button } from "@/components/ui/button";
import { PageTransition } from "@/components/launcher/PageTransition";
import GitHubGate from "@/components/launcher/GitHubGate";
import { motion, AnimatePresence } from "framer-motion";
import { usePendingWrites, useApproveWrite, useRejectWrite, useBackendOnline } from "@/hooks/useIRISBackend";
import { useRouter } from "next/navigation";

const DiffReviewPage = () => {
  const router = useRouter();
  const { data: online } = useBackendOnline();
  const { data, isLoading, error, refetch } = usePendingWrites();
  const approve = useApproveWrite();
  const reject = useRejectWrite();
  const [actionInProgress, setActionInProgress] = useState<"approve" | "reject" | null>(null);

  const pendingWrites = data?.pending ?? [];

  // Count total additions and deletions across all files
  let totalAdds = 0;
  let totalDels = 0;
  for (const pw of pendingWrites) {
    for (const line of pw.diff.split("\n")) {
      if (line.startsWith("+") && !line.startsWith("+++")) totalAdds++;
      else if (line.startsWith("-") && !line.startsWith("---")) totalDels++;
    }
  }

  const handleApproveAll = async () => {
    setActionInProgress("approve");
    try {
      // approveWrite sends { id } but backend ignores id and operates on full worktree
      await approve.mutateAsync(pendingWrites[0]?.id ?? "__all__");
      await refetch();
    } finally {
      setActionInProgress(null);
    }
  };

  const handleDiscardAll = async () => {
    setActionInProgress("reject");
    try {
      await reject.mutateAsync(pendingWrites[0]?.id ?? "__all__");
      await refetch();
    } finally {
      setActionInProgress(null);
    }
  };

  return (
    <GitHubGate>
      <PageTransition variant="blur">
        <div className="space-y-10">
          <SectionHeader
            title="Diff Review"
            description="Review agent changes before they are merged into the main repository. All changes are sandboxed in an isolated worktree branch."
            action={
              <div className="flex items-center gap-2">
                {online === false ? (
                  <span className="flex items-center gap-1 text-[10px] font-mono text-warning">
                    <WifiOff className="h-3 w-3" />IRIS offline
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-[10px] font-mono text-success">
                    <Wifi className="h-3 w-3" />Live
                  </span>
                )}
              </div>
            }
          />

          {isLoading && (
            <div className="text-xs font-mono text-muted-foreground animate-pulse">Loading pending writes…</div>
          )}

          {error && (
            <div className="glass-card rounded-2xl p-4 border-destructive/20">
              <p className="text-xs font-mono text-destructive">
                Failed to load pending writes — is IRIS backend running?
              </p>
            </div>
          )}

          {/* ── Action bar (only when there are pending writes) ── */}
          {!isLoading && !error && pendingWrites.length > 0 && (
            <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
              <div className="flex flex-wrap gap-2">
                <StatusBadge status="warning" label={`${pendingWrites.length} PENDING ${pendingWrites.length === 1 ? 'REVIEW' : 'REVIEWS'}`} />
                <span className="text-[10px] font-mono text-muted-foreground self-center">
                  +{totalAdds} / -{totalDels} lines across {pendingWrites.length} {pendingWrites.length === 1 ? 'file' : 'files'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  className="h-8 text-xs font-mono bg-success/15 border border-success/25 text-success hover:bg-success/25"
                  disabled={approve.isPending || actionInProgress !== null}
                  onClick={handleApproveAll}
                >
                  {approve.isPending ? (
                    <span className="animate-pulse">Merging…</span>
                  ) : (
                    <><GitMerge className="h-3.5 w-3.5 mr-1.5" />Approve All &amp; Merge</>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs font-mono border-destructive/25 text-destructive hover:bg-destructive/10"
                  disabled={reject.isPending || actionInProgress !== null}
                  onClick={handleDiscardAll}
                >
                  {reject.isPending ? (
                    <span className="animate-pulse">Discarding…</span>
                  ) : (
                    <><Trash2 className="h-3.5 w-3.5 mr-1.5" />Discard All</>
                  )}
                </Button>
              </div>
            </div>
          )}

          {/* ── Per-file diffs ── */}
          <div className="space-y-4">
            {pendingWrites.map((pw, i) => (
              <motion.div
                key={pw.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08, type: "spring" as const, stiffness: 300, damping: 25 }}
                className="glass-card rounded-2xl overflow-hidden border-warning/15"
              >
                <div className="flex items-center justify-between p-5 border-b border-border">
                  <div className="flex items-center gap-3">
                    <LiquidIcon color="warning" size="sm" bounce={false}>
                      <FileCode className="h-4 w-4" />
                    </LiquidIcon>
                    <div>
                      <p className="text-sm font-mono font-medium text-foreground">{pw.path}</p>
                      <p className="text-[10px] text-muted-foreground mt-0.5 tracking-wide">{pw.description}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {(() => { try { return new Date(pw.timestamp).toLocaleTimeString(); } catch { return pw.timestamp; } })()}
                  </span>
                </div>
                <div className="p-4 glass-subtle font-mono text-xs overflow-x-auto max-h-80 overflow-y-auto">
                  {pw.diff.split("\n").map((line, li) => {
                    let lineClass = "text-muted-foreground";
                    if (line.startsWith("+") && !line.startsWith("+++")) lineClass = "text-success";
                    else if (line.startsWith("-") && !line.startsWith("---")) lineClass = "text-destructive";
                    else if (line.startsWith("@@")) lineClass = "text-primary";
                    return (
                      <div
                        key={li}
                        className={`${lineClass} px-2 rounded whitespace-pre ${
                          line.startsWith("+") && !line.startsWith("+++")
                            ? "bg-success/5"
                            : line.startsWith("-") && !line.startsWith("---")
                            ? "bg-destructive/5"
                            : ""
                        }`}
                      >
                        {line}
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            ))}
          </div>

          {/* ── Empty state ── */}
          {!isLoading && !error && pendingWrites.length === 0 && (
            <div className="glass-card rounded-2xl p-10 text-center">
              <LiquidIcon color="neutral" size="lg" bounce={false} className="mx-auto mb-4 opacity-40">
                <Activity className="h-6 w-6" />
              </LiquidIcon>
              <p className="text-sm text-muted-foreground">No pending reviews</p>
              <p className="text-xs text-muted-foreground mt-1 tracking-wide">
                Agent changes will appear here for approval before merging
              </p>
            </div>
          )}

          {/* ── Warning about all-or-nothing approve/discard ── */}
          {!isLoading && !error && pendingWrites.length > 0 && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-warning/5 border border-warning/10">
              <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
              <p className="text-[10px] font-mono text-muted-foreground leading-relaxed">
                Approving merges ALL changes from the isolated worktree branch into the main repository.
                Discarding deletes the worktree and all pending changes permanently.
                This action affects every file shown above — individual file approval is not supported.
              </p>
            </div>
          )}
        </div>
      </PageTransition>
    </GitHubGate>
  );
};

export default DiffReviewPage;
