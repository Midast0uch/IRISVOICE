"use client"

/**
 * IRIS asks while it works: a permission or a question, drawn INSIDE the running turn.
 *   variant "row"  (developer): an ASK row in the matrix that waits, keys under it.
 *   variant "card" (personal):  a small card inside the task card.
 * Keys, when the ask has focus: y / Enter allow, n / Esc deny (a permission that needs a
 * second look asks for y again). The countdown shows ONLY when the backend sent a timeout.
 * After the answer the ask becomes a receipt line: "✓ Allowed · run command · <command>".
 * Look: iris-strands.html (`.perm`, `.pcard`, `.receipt`).
 *
 * The answers go through the existing responses (the caller's `actions` send
 * `notification_response` / `question_response`): no new protocol here.
 */
import React from "react"
import { actionLabel } from "@/components/chat/PermissionCard"
import { permissionTarget, resolveAskLocally, type AskItem } from "@/lib/turns/asks"

const RUN = "#f2c14e"
const OK = "#5fcf98"
const BAD = "#ff7a6e"

export interface AskActions {
  permission: (requestId: string, action: "grant" | "deny" | "confirm") => void
  question: (questionId: string, answer: string | string[], source?: string) => void
}

const TIER_NOTE: Record<string, string> = {
  read_only: "just looking, changes nothing",
  side_effect: "this can change things on your computer",
  destructive: "this can delete or overwrite things, check twice",
}

function clock(sec: number): string {
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`
}

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

/** The one-line receipt text of a settled ask (also its accessible name). */
export function receiptOf(a: AskItem): { mark: string; word: string; rest: string; color: string } {
  if (a.kind === "permission") {
    const rest = [actionLabel(a.tool || "").toLowerCase(), permissionTarget(a)].filter(Boolean).join(" · ")
    if (a.state === "allowed") return { mark: "✓", word: "Allowed", rest, color: OK }
    if (a.state === "expired") return { mark: "✕", word: "Not answered in time", rest, color: BAD }
    return { mark: "✕", word: "Denied", rest, color: BAD }
  }
  const rest = [clip(a.text || "", 60), a.answer].filter(Boolean).join(" · ")
  if (a.state === "expired") return { mark: "✕", word: "Not answered in time", rest: clip(a.text || "", 60), color: BAD }
  return { mark: "✓", word: "Answered", rest, color: OK }
}

export function AskPrompt({
  ask,
  variant,
  glowColor,
  actions,
}: {
  ask: AskItem
  variant: "row" | "card"
  glowColor: string
  actions: AskActions
}) {
  const waiting = ask.state === "waiting"
  const rootRef = React.useRef<HTMLDivElement>(null)
  const [confirming, setConfirming] = React.useState(false)
  const [left, setLeft] = React.useState(ask.timeoutSeconds ?? 0)
  const [picked, setPicked] = React.useState<string[]>([])
  const [typed, setTyped] = React.useState("")

  // The countdown is the backend's: no `timeout_seconds` in the ask, no clock.
  React.useEffect(() => {
    if (!waiting || !ask.timeoutSeconds) return
    const t = setInterval(() => setLeft((l) => Math.max(0, l - 1)), 1000)
    return () => clearInterval(t)
  }, [waiting, ask.timeoutSeconds])

  // Take focus so y / n work at once, but never from the composer or any field in use.
  React.useEffect(() => {
    if (!waiting || ask.kind !== "permission") return
    const el = document.activeElement
    if (!el || el === document.body) rootRef.current?.focus({ preventScroll: true })
  }, [waiting, ask.kind, ask.id])

  const approve = () => {
    if (!waiting) return
    if (ask.requiresConfirmation && !confirming) {
      setConfirming(true)
      return
    }
    resolveAskLocally(ask.id, "allowed")
    actions.permission(ask.id, ask.requiresConfirmation ? "confirm" : "grant")
  }
  const deny = () => {
    if (!waiting) return
    resolveAskLocally(ask.id, "denied")
    actions.permission(ask.id, "deny")
  }
  const answer = (value: string | string[], source: string) => {
    const text = Array.isArray(value) ? value.join(", ") : value
    if (!text.trim() || !waiting) return
    resolveAskLocally(ask.id, "answered", text)
    actions.question(ask.id, value, source)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!waiting || ask.kind !== "permission" || e.ctrlKey || e.metaKey || e.altKey) return
    const t = e.target as HTMLElement
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable) return
    const k = e.key
    if (k === "y" || k === "Y" || (k === "Enter" && e.target === e.currentTarget)) {
      e.preventDefault()
      approve()
    } else if (k === "n" || k === "N" || k === "Escape") {
      e.preventDefault()
      e.stopPropagation()
      deny()
    }
  }

  const mono = variant === "row" ? "font-mono" : ""

  // ── settled: the receipt ───────────────────────────────────────────────
  if (!waiting) {
    const r = receiptOf(ask)
    return (
      <div
        className={`flex min-w-0 items-center gap-2 ${mono}`}
        style={{ minHeight: 22, fontSize: variant === "row" ? 12 : 11.5, color: "rgba(230,233,242,.55)" }}
        data-ask={ask.id}
        data-ask-state={ask.state}
      >
        {variant === "row" && <span className="flex-none text-center" style={{ width: 12, color: r.color }}>{ask.state === "allowed" || ask.state === "answered" ? "●" : "✕"}</span>}
        {variant === "row" && <span className="flex-none font-bold" style={{ width: "7ch", color: r.color }}>ASK</span>}
        <span role="status" data-ask-receipt className="min-w-0 flex-1 truncate" title={`${r.word} · ${r.rest}`}>
          <b style={{ color: r.color, fontWeight: 500 }}>{r.mark} {r.word}</b>
          {r.rest ? ` · ${r.rest}` : ""}
        </span>
      </div>
    )
  }

  const countdown =
    ask.timeoutSeconds ? (
      <span className="tabular-nums" data-ask-countdown style={{ color: left <= 10 ? BAD : "rgba(230,233,242,.55)" }}>
        {clock(left)}
      </span>
    ) : null

  // ── waiting: permission ────────────────────────────────────────────────
  if (ask.kind === "permission") {
    const label = actionLabel(ask.tool || "")
    const target = permissionTarget(ask)
    const keys = (
      <>
        {ask.requiresConfirmation && confirming && (
          <span style={{ color: "#dfe6f2" }}>Are you sure? This one can delete or overwrite things.</span>
        )}
        <button type="button" onClick={approve} data-ask-allow style={variant === "card" ? { background: RUN, color: "#1a1203", borderColor: RUN, borderRadius: 6, padding: "6px 8px", font: "500 11.5px/1 system-ui", border: `1px solid ${RUN}` } : { background: "none", border: 0, color: "#dfe6f2", font: "inherit", padding: 0 }}>
          <span style={{ color: variant === "card" ? "#1a1203" : glowColor }}>{variant === "card" ? "" : "[y] "}</span>
          {confirming ? "yes, allow" : variant === "card" ? "Allow ↵" : "allow"}
        </button>
        <button type="button" onClick={deny} data-ask-deny style={variant === "card" ? { background: "#0e1122", color: "#e6e9f2", borderRadius: 6, padding: "6px 8px", font: "500 11.5px/1 system-ui", border: "1px solid rgba(160,190,255,.09)" } : { background: "none", border: 0, color: "#dfe6f2", font: "inherit", padding: 0 }}>
          <span style={{ color: glowColor }}>{variant === "card" ? "" : "[n] "}</span>
          {variant === "card" ? "Deny · Esc" : "deny"}
        </button>
      </>
    )
    if (variant === "row") {
      return (
        <div
          ref={rootRef}
          tabIndex={0}
          role="group"
          aria-label={`IRIS needs your OK: ${label}`}
          onKeyDown={onKeyDown}
          className={`iris-ask min-w-0 ${mono}`}
          style={{ outline: "none" }}
          data-ask={ask.id}
          data-ask-state="waiting"
          data-ask-kind="permission"
        >
          <div className="flex min-w-0 items-center gap-2 rounded px-1" style={{ minHeight: 22 }}>
            <span className="iris-mx-breathe flex-none text-center" style={{ width: 12, color: RUN }}>◎</span>
            <span className="flex-none font-bold" style={{ width: "7ch", color: RUN }}>ASK</span>
            <span className="min-w-0 flex-1 truncate text-white/80" title={`${label} · ${target}`}>{label.toLowerCase()}{target ? ` · ${target}` : ""}</span>
            <span className="flex-none" style={{ fontSize: 11, color: "rgba(230,233,242,.55)" }}>needs you {countdown}</span>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1" style={{ margin: "2px 0 4px 24px", fontSize: 11.5, color: "#dfe6f2" }}>
            <span style={{ color: "rgba(230,233,242,.55)" }}>{TIER_NOTE[ask.tier || "side_effect"]}</span>
            {keys}
          </div>
        </div>
      )
    }
    return (
      <div
        ref={rootRef}
        tabIndex={0}
        role="group"
        aria-label={`IRIS needs your OK: ${label}`}
        onKeyDown={onKeyDown}
        className="iris-ask px-2.5 py-2"
        style={{ borderRadius: 10, border: `1px solid ${RUN}73`, background: "#080a16", fontSize: 12.5, outline: "none" }}
        data-ask={ask.id}
        data-ask-state="waiting"
        data-ask-kind="permission"
      >
        <div className="flex items-baseline gap-2">
          <b style={{ color: "#e6e9f2" }}>{label}?</b>
          <span className="flex-1" style={{ color: "rgba(230,233,242,.55)" }}>IRIS needs your OK · {TIER_NOTE[ask.tier || "side_effect"]}</span>
          {countdown}
        </div>
        {target && (
          <div className="my-1.5 rounded-md px-2 py-1 font-mono break-words" style={{ background: "rgba(0,0,0,.35)", fontSize: 11.5, lineHeight: 1.5 }}>{target}</div>
        )}
        <div className="flex flex-wrap items-center justify-end gap-1.5">{keys}</div>
      </div>
    )
  }

  // ── waiting: question ──────────────────────────────────────────────────
  const options = ask.options || []
  const body = (
    <>
      {options.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {options.map((o) => {
            const on = picked.includes(o)
            return (
              <button
                key={o}
                type="button"
                data-ask-option={o}
                aria-pressed={ask.multiSelect ? on : undefined}
                onClick={() => (ask.multiSelect ? setPicked((p) => (p.includes(o) ? p.filter((x) => x !== o) : [...p, o])) : answer(o, "click"))}
                className="rounded-md px-2.5 py-1 text-[11px]"
                style={{ color: on ? "#05060c" : "rgba(255,255,255,.85)", border: `1px solid ${glowColor}4d`, background: on ? glowColor : "rgba(255,255,255,.04)", cursor: "pointer" }}
              >
                {o}
              </button>
            )
          })}
          {ask.multiSelect && (
            <button type="button" disabled={picked.length === 0} onClick={() => answer(picked, "click")} className="rounded-md px-2.5 py-1 text-[11px] disabled:opacity-40" style={{ color: "#05060c", background: glowColor }}>
              Send ({picked.length})
            </button>
          )}
        </div>
      )}
      {ask.allowOther && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={typed}
            aria-label="Your answer"
            placeholder="Type your answer…"
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") answer(typed, "text")
            }}
            className="min-w-0 flex-1 rounded px-2 py-1 text-[11px]"
            style={{ color: "rgba(255,255,255,.9)", background: "rgba(0,0,0,.3)", border: `1px solid ${glowColor}4d`, outline: "none" }}
          />
          <button type="button" onClick={() => answer(typed, "text")} className="rounded px-2 py-1 text-[11px]" style={{ color: "#05060c", background: glowColor }}>
            Send
          </button>
        </div>
      )}
    </>
  )
  if (variant === "row") {
    return (
      <div role="group" aria-label={`IRIS asks: ${ask.text}`} className={`iris-ask min-w-0 ${mono}`} data-ask={ask.id} data-ask-state="waiting" data-ask-kind="question">
        <div className="flex min-w-0 items-center gap-2 rounded px-1" style={{ minHeight: 22 }}>
          <span className="iris-mx-breathe flex-none text-center" style={{ width: 12, color: RUN }}>◎</span>
          <span className="flex-none font-bold" style={{ width: "7ch", color: RUN }}>ASK</span>
          <span className="min-w-0 flex-1 truncate text-white/80" title={ask.text}>{ask.header ? `${ask.header} · ` : ""}{ask.text}</span>
          <span className="flex-none" style={{ fontSize: 11, color: "rgba(230,233,242,.55)" }}>needs you {countdown}</span>
        </div>
        <div className="flex flex-col gap-1.5" style={{ margin: "2px 0 4px 24px" }}>{body}</div>
      </div>
    )
  }
  return (
    <div role="group" aria-label={`IRIS asks: ${ask.text}`} className="iris-ask flex flex-col gap-1.5 px-2.5 py-2" style={{ borderRadius: 10, border: `1px solid ${RUN}73`, background: "#080a16", fontSize: 12.5 }} data-ask={ask.id} data-ask-state="waiting" data-ask-kind="question">
      <div className="flex items-baseline gap-2">
        <b className="flex-1" style={{ color: "#e6e9f2", fontWeight: 600 }}>{ask.text}</b>
        {countdown}
      </div>
      {body}
    </div>
  )
}

export default AskPrompt
