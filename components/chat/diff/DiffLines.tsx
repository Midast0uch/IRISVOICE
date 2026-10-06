"use client"

import React from "react"
import { OK, BAD } from "@/components/chat/diff/DiffMark"

/** The rows of one hunk: " " context, "-" removed, "+" added. */
export function DiffLines({ lines, fontSize = 11.5 }: { lines: string[]; fontSize?: number }) {
  return (
    <pre
      className="m-0 px-2.5 py-1.5 font-mono overflow-x-auto"
      style={{ fontSize, lineHeight: 1.55, whiteSpace: "pre" }}
      data-diff-lines
    >
      {lines.map((l, i) =>
        l[0] === "+" ? (
          <span key={i} style={{ display: "block", color: OK, background: "rgba(95,207,152,.07)" }}>{l}</span>
        ) : l[0] === "-" ? (
          <span key={i} style={{ display: "block", color: BAD, background: "rgba(255,122,110,.07)" }}>{l}</span>
        ) : (
          <span key={i} style={{ display: "block" }}>{l}</span>
        ),
      )}
    </pre>
  )
}

export default DiffLines
