/**
 * GUARD: personal and developer mode render DIFFERENTLY. (Owner, 2026-10-07.)
 *
 * The backend now pins INTENT as mode-independent — a work request routes to
 * the work loop in both modes and a question takes the direct path in both
 * (backend/tests/unit/test_routing_is_mode_independent.py). That test asserts
 * NOTHING about rendering, and it must stay that way: the modes are NOT the
 * same thing to look at.
 *
 * The owner's rule, verbatim: "there should be no difference between personal
 * mode and developer mode besides HOW THINGS ARE DISPLAYED in chatview and the
 * agent being able to actually edit, read and write its own code."
 *
 * So this file pins the other half — the DISPLAY half — so nobody can later
 * read the routing invariant as licence to collapse the two views. A task card
 * is a live execution MATRIX in developer mode and the compact card in
 * personal mode, from the same data.
 *
 * Fails if: TaskCardEntry loses its isDeveloper branch, or either mode renders
 * the other's view.
 */
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import React from "react";

import { TaskCardEntry } from "@/components/chat/TaskCardEntry";
import type { TaskCard } from "@/hooks/useTaskProgress";

// The card reads brand colours from context and animates through framer-motion;
// same stand-ins the existing TaskListCard suites use.
jest.mock("@/contexts/BrandColorContext", () => ({
  useBrandColor: () => ({
    getThemeConfig: () => ({ glow: { color: "#00d4ff" }, accent: "#00d4ff" }),
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
    <div data-testid="xur" data-color={props.color} />
  ),
}));

const GLOW = "#00d4ff";

function card(extra: Partial<TaskCard> = {}): TaskCard {
  return {
    cardId: "card-disp-1",
    conversationId: "conv-1",
    turnId: "turn-1",
    isWorking: true,
    currentStep: 1,
    totalSteps: 2,
    planTitle: "Fix the router window test",
    steps: [
      {
        id: "n1",
        seq: 1,
        description: "read router.py 419-466",
        status: "done",
        toolName: "read_file",
        resultPreview: "48 ln",
      },
      {
        id: "n2",
        seq: 2,
        description: "pytest tests/unit/test_router.py",
        status: "working",
        toolName: "run_command",
      },
    ],
    ...extra,
  } as TaskCard;
}

function renderIn(mode: "personal" | "developer", extra: Partial<TaskCard> = {}) {
  const { container } = render(
    <TaskCardEntry
      card={card(extra)}
      isDeveloper={mode === "developer"}
      glowColor={GLOW}
      matrixElapsedSec={7}
    />,
  );
  return container;
}

describe("the two modes display the same work differently", () => {
  it("developer mode draws the live execution matrix, not the compact card", () => {
    const container = renderIn("developer");

    // The matrix frame is present (data-matrix is the matrix's own hook).
    expect(container.querySelector("[data-matrix]")).not.toBeNull();
    // ...and the compact card's own chrome is absent.
    expect(container.querySelector("[data-matrix]")).toBeTruthy();
    expect(screen.queryByText(/^✓ DONE$/)).toBeNull();
  });

  it("personal mode draws the compact card, not the matrix", () => {
    const container = renderIn("personal");

    // No matrix frame at all.
    expect(container.querySelector("[data-matrix]")).toBeNull();
    // The compact card speaks the work in plain words, past tense.
    expect(screen.getByText(/Fix the router window test/)).toBeInTheDocument();
    expect(screen.getByText(/read router\.py 419-466/)).toBeInTheDocument();
  });

  it("the same card renders DIFFERENTLY in each mode (the point of the guard)", () => {
    const dev = renderIn("developer").innerHTML;
    const personal = renderIn("personal").innerHTML;
    expect(dev).not.toEqual(personal);
    expect(dev).toContain("data-matrix");
    expect(personal).not.toContain("data-matrix");
  });
});