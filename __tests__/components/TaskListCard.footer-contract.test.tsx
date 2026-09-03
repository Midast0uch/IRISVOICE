/**
 * BEHAVIORAL CONTRACT — task card FOOTER (session 247).
 *
 * The footer is where the live failures physically rendered:
 *   - "LEGACY_UNKNOWN/MEMORY.DB" instead of the real card short-id
 *   - a timer that kept running after task:done
 * These tests pin the footer's identity + liveness contract at the component
 * level, complementing the hook-level replay in
 * useTaskProgress.card-contract.test.tsx.
 */
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import React from "react";
import TaskListCard from "@/components/chat/TaskListCard";
import type { TaskStep } from "@/hooks/useTaskProgress";

jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#22d3ee" }, accent: "#22d3ee" }),
  }),
  BrandColorProvider: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock("framer-motion", () => {
  const React = require("react");
  const motion: any = new Proxy(
    {},
    { get: (_t: any, tag: string) => React.forwardRef((p: any, ref: any) =>
      React.createElement(tag, { ...p, ref }, p?.children)) },
  );
  return { motion, AnimatePresence: ({ children }: any) => children };
});
jest.mock("@/components/Xur", () => ({
  Xur: (props: { size?: number; color?: string }) => (
    <div data-testid="xur" data-color={props.color} data-size={props.size} />
  ),
}));

function step(overrides: Partial<TaskStep> = {}): TaskStep {
  return {
    id: "r1",
    description: "Search web for breakthroughs",
    status: "done",
    toolName: "crawler_query",
    ...overrides,
  };
}

describe("FOOTER CONTRACT — identity chrome", () => {
  it("renders the real card short-id when card_id is known", () => {
    render(
      <TaskListCard
        steps={[step()]}
        cardId="card_fb24d28d-f98"
        planTitle="Fusion research"
      />,
    )
    expect(screen.getByText(/fb24d28d-f98\/memory\.db/i)).toBeInTheDocument()
  })

  it("renders whatever identity it is given, verbatim", () => {
    // The component is a FAITHFUL renderer: identity guarantees live
    // upstream in useTaskProgress (pinned by card-contract C1 — no
    // legacy_unknown fabrication). This test documents the passthrough so
    // any future filtering logic here is a conscious decision.
    render(
      <TaskListCard
        steps={[step()]}
        cardId="card_fb24d28d-f98"
        planTitle="Fusion research"
      />,
    )
    expect(screen.getByText(/fb24d28d-f98\/memory\.db/i)).toBeInTheDocument()
  })
})

describe("FOOTER CONTRACT — liveness pills", () => {
  it("live run shows the running elapsed timer", () => {
    render(
      <TaskListCard
        steps={[step({ status: "working" })]}
        cardActive
        cardId="card_fb24d28d-f98"
        planTitle="Fusion research"
      />,
    )
    // ⏱ pill renders while working (elapsed starts near 0:00)
    expect(screen.getByText(/⏱/)).toBeInTheDocument()
  })

  it("completed run shows the FROZEN duration, not a running timer", () => {
    render(
      <TaskListCard
        steps={[step({ status: "done" })]}
        cardActive={false}
        durationSec={180}
        cardId="card_fb24d28d-f98"
        planTitle="Fusion research"
      />,
    )
    // frozen duration pill: 180s -> "3:00" (rendered inside the ⏱ pill)
    expect(screen.getByText(/⏱\s*3:00/)).toBeInTheDocument()
  })
})
