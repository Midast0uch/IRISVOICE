"use client"

/**
 * The review of an edit, in the lens: one block per file, hunks with +/- lines, and per
 * hunk Keep / Undo; per file "Keep all" / "Undo all". Look: iris-strands.html
 * (`/* diff review *\/`, `openDiff`, `hunkHTML`).
 *
 * Undo sends `diff_undo` (lib/diffs/api.sendDiffUndo). A hunk reads "undone" ONLY after
 * the backend answered `diff_undo_result` ok (lib/diffs/undoStore); a refusal shows its
 * reason; `undoable: false` hides Undo and says why. A successful undo also tells IRIS
 * (backend), so the page says so.
 */
import React from "react"
import { sendDiffUndo, type EditDiff, type SendMessageFn } from "@/lib/diffs/api"
import {
  hunkPhase,
  markKept,
  markUndoPending,
  markUndoRefused,
  useUndoState,
} from "@/lib/diffs/undoStore"
import { DiffLines } from "@/components/chat/diff/DiffLines"
import { BAD, OK } from "@/components/chat/diff/DiffMark"

const MUTED = "rgba(230,233,242,.55)"
const HAIR = "rgba(160,190,255,.09)"

function SmallButton({
  children,
  onClick,
  warn,
  disabled,
  label,
}: {
  children: React.ReactNode
  onClick: () => void
  warn?: boolean
  disabled?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="rounded-md px-2 py-1.5 text-[11.5px] leading-none whitespace-nowrap disabled:opacity-40"
      style={{ background: "#0e1122", border: `1px solid ${HAIR}`, color: warn ? BAD : "#e6e9f2", cursor: disabled ? "default" : "pointer" }}
    >
      {children}
    </button>
  )
}

function DiffFile({ diff, sendMessage, index }: { diff: EditDiff; sendMessage?: SendMessageFn | null; index: number }) {
  const state = useUndoState(diff.diff_id)
  const wholeUndone = state.whole.phase === "undone"
  const wholePending = state.whole.phase === "pending"

  const undo = (hunkIndex?: number) => {
    const slot = typeof hunkIndex === "number" ? hunkIndex : null
    markUndoPending(diff.diff_id, slot)
    const sent = sendDiffUndo(sendMessage, diff.diff_id, hunkIndex)
    if (!sent) markUndoRefused(diff.diff_id, slot, "IRIS is not connected, so nothing was undone. Try again.")
  }

  const allUndone = wholeUndone || (diff.hunks.length > 0 && diff.hunks.every((_, i) => hunkPhase(state, i).phase === "undone"))

  return (
    <section
      className="mb-3 overflow-hidden rounded-lg font-mono"
      style={{ border: `1px solid ${HAIR}` }}
      data-diff-file={diff.diff_id}
      data-undone={allUndone ? "true" : "false"}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2 px-2.5 py-1.5 text-[12px]" style={{ background: "#080a16" }}>
        <b className="min-w-0 flex-1 truncate font-semibold" title={diff.path}>
          {diff.path}
          {index > 0 ? <span style={{ color: MUTED }}> · edit {index + 1}</span> : null}
        </b>
        <span style={{ color: OK }}>+{diff.added}</span>
        <span style={{ color: BAD }}>−{diff.removed}</span>
        {diff.undoable && !wholeUndone && (
          <>
            <SmallButton label={`Keep all changes in ${diff.path}`} onClick={() => diff.hunks.forEach((_, i) => markKept(diff.diff_id, i))}>
              Keep all
            </SmallButton>
            <SmallButton label={`Undo all changes in ${diff.path}`} warn disabled={wholePending} onClick={() => undo()}>
              {wholePending ? "Undoing…" : "Undo all"}
            </SmallButton>
          </>
        )}
      </div>

      {diff.new_file && !wholeUndone && (
        <p className="m-0 px-2.5 py-1 text-[11px]" style={{ color: MUTED }} data-diff-note="new-file">
          IRIS created this file. Undo all deletes it.
        </p>
      )}
      {!diff.undoable && (
        <p className="m-0 px-2.5 py-1 text-[11px]" style={{ color: MUTED }} data-diff-note="not-undoable">
          Undo is not available here: no copy of the file was kept for undo (it is over 2 MB), or IRIS no longer tracks this edit.
        </p>
      )}
      {diff.truncated && (
        <p className="m-0 px-2.5 py-1 text-[11px]" style={{ color: MUTED }} data-diff-note="truncated">
          {diff.hunks.length
            ? "This diff is cut: only the first lines are shown. The counts above are for the whole change."
            : "This file is too large to show a diff. It did change."}
        </p>
      )}
      {wholeUndone && (
        <p className="m-0 px-2.5 py-1 text-[11px]" style={{ color: OK }} data-diff-note="undone">
          undone{state.toldIris ? " · IRIS knows you did not want this change" : ""}
        </p>
      )}
      {state.whole.phase === "refused" && (
        <p role="alert" className="m-0 px-2.5 py-1 text-[11px]" style={{ color: BAD }} data-diff-refusal="file">
          Not undone: {state.whole.reason}
        </p>
      )}

      {diff.hunks.map((h, i) => {
        const hs = hunkPhase(state, i)
        const undone = hs.phase === "undone"
        return (
          <div
            key={i}
            className={`border-t ${undone ? "iris-hunk-undone" : ""}`}
            style={{ borderColor: HAIR }}
            data-hunk={i}
            data-hunk-state={hs.phase}
          >
            <div className="flex items-center gap-1.5 px-2.5 py-1 text-[10.5px]" style={{ background: "rgba(255,255,255,.02)", color: MUTED }}>
              <span className="min-w-0 flex-1 truncate">{h.header}</span>
              {undone ? (
                <span style={{ color: OK }} data-hunk-undone>undone</span>
              ) : diff.undoable ? (
                <>
                  {hs.kept && <span data-hunk-kept>kept</span>}
                  {!hs.kept && (
                    <SmallButton label={`Keep change ${i + 1}`} onClick={() => markKept(diff.diff_id, i)}>
                      Keep
                    </SmallButton>
                  )}
                  <SmallButton label={`Undo change ${i + 1}`} warn disabled={hs.phase === "pending"} onClick={() => undo(i)}>
                    {hs.phase === "pending" ? "Undoing…" : "Undo"}
                  </SmallButton>
                </>
              ) : (
                !hs.kept && (
                  <SmallButton label={`Keep change ${i + 1}`} onClick={() => markKept(diff.diff_id, i)}>
                    Keep
                  </SmallButton>
                )
              )}
            </div>
            {hs.phase === "refused" && (
              <p role="alert" className="m-0 px-2.5 py-1 text-[11px]" style={{ color: BAD }} data-diff-refusal={i}>
                Not undone: {hs.reason}
              </p>
            )}
            <div className={undone ? "opacity-40 line-through" : ""}>
              <DiffLines lines={h.lines} />
            </div>
          </div>
        )
      })}
    </section>
  )
}

export function DiffReview({ diffs, sendMessage }: { diffs: EditDiff[]; sendMessage?: SendMessageFn | null }) {
  return (
    <div data-diff-review>
      {diffs.map((d, i) => (
        <DiffFile
          key={d.diff_id}
          diff={d}
          sendMessage={sendMessage}
          index={diffs.slice(0, i).filter((x) => x.path === d.path).length}
        />
      ))}
      <p className="text-[11px]" style={{ color: MUTED }}>
        Undo restores the file. IRIS also learns that the change was not wanted.
      </p>
    </div>
  )
}

export default DiffReview
