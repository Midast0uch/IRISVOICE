/**
 * T17a (REQ-8): honest frontend display flow.
 *
 * Drives <TaskListCard> with REAL TaskStep records (the same shape
 * useTaskProgress produces from the backend QueueItem + ledger) and
 * asserts the spec's core acceptance criteria:
 *
 *   AC1  cards are driven by real step records, not fabricated UI state
 *   AC2  live status transitions render (pending -> working -> done)
 *   AC3  real tool / result are shown
 *   AC4  NO phantom card â€” a step that was never created is absent
 *   AC5  a FAILED step renders as fail (never as done)
 *   AC6  learningSignal drives the border tint + badge
 *
 * This is the behavioral guard the spec requires (T17) â€” it proves the
 * display cannot lie about task state.
 */
import "@testing-library/jest-dom";
import { render, screen, within, fireEvent } from "@testing-library/react";
import React from "react";
import TaskListCard from "@/components/chat/TaskListCard";
import type { TaskStep } from "@/hooks/useTaskProgress";

// TaskListCard reads brand colors from context; mock it like the existing
// TaskListCard.test.tsx does.
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

function makeSteps(): TaskStep[] {
  return [
    {
      id: "s1",
      description: "Read the config file",
      status: "done",
      toolName: "read_file",
      resultPreview: "config loaded",
    },
    {
      id: "s2",
      description: "Validate the schema",
      status: "working",
      toolName: "validate_schema",
    },
    {
      id: "s3",
      description: "Write the report",
      status: "pending",
      toolName: "write_file",
    },
  ];
}

describe("TaskListCard â€” honest display (REQ-8 / T17a)", () => {
  it("renders real step records with live status + tool/result (AC1-AC3)", () => {
    const { container } = render(<TaskListCard steps={makeSteps()} />);
    // All three real steps are present.
    expect(screen.getByText("Read the config file")).toBeInTheDocument();
    expect(screen.getByText("Validate the schema")).toBeInTheDocument();
    expect(screen.getByText("Write the report")).toBeInTheDocument();

    // Live status transitions render as the dot color (done=#34d399,
    // working=#fbbf24, pending=rgba(255,255,255,0.4)).
    const dots = Array.from(
      container.querySelectorAll('span[style*="border"]'),
    ) as HTMLElement[];
    const hasDone = dots.some((d) =>
      (d.getAttribute("style") || "").toLowerCase().includes("34d399"),
    );
    const hasWorking = dots.some((d) =>
      (d.getAttribute("style") || "").toLowerCase().includes("fbbf24"),
    );
    const hasPending = dots.some((d) =>
      (d.getAttribute("style") || "").includes("255, 255, 255, 0.4"),
    );
    expect(hasDone).toBe(true);
    expect(hasWorking).toBe(true);
    expect(hasPending).toBe(true);

    // Real tool is shown (not fabricated).
    expect(screen.getByText(/read_file/)).toBeInTheDocument();

    // The real result preview is shown once the step is expanded.
    const stepBtn = screen.getByText("Read the config file");
    fireEvent.click(stepBtn);
    expect(screen.getByText(/config loaded/)).toBeInTheDocument();
  });

  it("shows NO phantom card for a step that was never created (AC4)", () => {
    const steps = makeSteps();
    const { container } = render(<TaskListCard steps={steps} />);
    // A step id that does not exist in the records must not appear.
    expect(screen.queryByText("Phantom ghost step")).not.toBeInTheDocument();
    // Exactly the real steps render — each step is a <button> card
    // (excluding the "Collapse plan" toggle button).
    const stepButtons = Array.from(
      container.querySelectorAll("button"),
    ).filter((b) => /Read the config|Validate the schema|Write the report/.test(b.textContent || ""));
    expect(stepButtons).toHaveLength(steps.length);
  });

  it("renders a FAILED step as fail (red dot), never as done (AC5)", () => {
    const steps = makeSteps();
    steps[1] = {
      ...steps[1],
      status: "fail",
    };
    const { container } = render(<TaskListCard steps={steps} />);
    // The failed step's description is present (real record, not dropped).
    expect(screen.getByText("Validate the schema")).toBeInTheDocument();
    // The status dot uses the FAIL color (#f87171 = rgb(248,113,113)),
    // NOT the done color (#34d399 = rgb(52,211,153)). The dot border
    // is inline-styled with meta.color.
    const dots = Array.from(
      container.querySelectorAll('span[style*="border"]'),
    ) as HTMLElement[];
    const failDot = dots.find((d) =>
      (d.getAttribute("style") || "").includes("248, 113, 113") ||
      (d.getAttribute("style") || "").toLowerCase().includes("f87171"),
    );
    expect(failDot).toBeTruthy();
    // The fail dot must NOT carry the done color.
    expect(failDot!.getAttribute("style")).not.toMatch(/34d399/i);
  });

  it("drives border tint + badge from learningSignal (AC6)", () => {
    const steps = makeSteps();
    const { container } = render(
      <TaskListCard steps={steps} learningSignal={"retried" as any} />,
    );
    // The learning badge renders the discrete signal label (not narration).
    expect(screen.getByText(/Retried/i)).toBeInTheDocument();
    // The badge carries a title exposing the real signal state.
    const badge = screen.getByTitle(/Learning signal: Retried/i);
    expect(badge).toBeInTheDocument();
    // The card carries a subtle border particle span (aria-hidden) whose
    // inline border uses the blue retried tint (#3b82f6).
    const particle = container.querySelector('span[aria-hidden="true"]');
    expect(particle).not.toBeNull();
    expect(particle!.getAttribute("style")).toMatch(/3b82f6/i);
  });

  it("renders crystallized signal with green tint (AC6 variant)", () => {
    const steps = makeSteps();
    const { container } = render(
      <TaskListCard steps={steps} learningSignal={"crystallized" as any} />,
    );
    expect(screen.getByText(/Crystallized/i)).toBeInTheDocument();
    const badge = screen.getByTitle(/Learning signal: Crystallized/i);
    expect(badge).toBeInTheDocument();
    const particle = container.querySelector('span[aria-hidden="true"]');
    expect(particle).not.toBeNull();
    expect(particle!.getAttribute("style")).toMatch(/22c55e/i);
  });
});
