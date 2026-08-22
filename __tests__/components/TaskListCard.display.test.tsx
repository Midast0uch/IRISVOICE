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
// Test INFRA (session 245, added with the ChassisStepNode re-inversion):
// the real Xur is a canvas animation that cannot expose attributes under
// jsdom. Same mock as TaskListCard.test.tsx — lets AC2 observe the working
// step's amber core via data-color WITHOUT weakening any assertion.
jest.mock("@/components/Xur", () => ({
  Xur: (props: { size?: number; color?: string; speed?: number }) => (
    <div data-testid="xur" data-color={props.color} data-size={props.size} />
  ),
}));

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

    // Live status transitions render. RE-INVERTED 2026-08-21, session 245,
    // CALLED OUT DELIBERATELY: the T9 ChassisStepNode swap moved step-node
    // markup into the shared chassis — nodes are DIVs whose done-state colour
    // is an inline BACKGROUND (+boxShadow), not a bordered SPAN, so the old
    // span[style*="border"] query could never match again and this suite sat
    // red against committed code (stash control run identical). WHAT THIS
    // ASSERTION STILL PINS, at unchanged strength: all three live states
    // render with their REAL colours — done #34d399 as the node dot's inline
    // background, working #fbbf24 via the Xur core, pending as its own
    // distinct chassis node (pending is Tailwind-classed now, so its
    // observability moved from inline style to the node testid).
    const doneDot = container.querySelector(
      '[data-testid="chassis-node-done"] [style]',
    );
    expect(doneDot).not.toBeNull();
    expect((doneDot!.getAttribute("style") || "").toLowerCase()).toContain("34d399");
    const workingCore = container.querySelector('[data-testid="xur"]');
    expect(workingCore).toHaveAttribute("data-color", "#fbbf24");
    expect(
      container.querySelector('[data-testid="chassis-node-pending"]'),
    ).not.toBeNull();

    // RE-INVERTED 2026-08-21, session 244 (task-card-v2 completion), CALLED
    // OUT DELIBERATELY: the verb column is now the SINGLE tool representation
    // (design.md token table: w-12 vein-coloured registry verb). The old
    // human-label pill ("Reading File") was removed because it duplicated the
    // verb — a row read "SEARCH … WebSearch", saying the same thing twice.
    // WHAT THIS ASSERTION STILL PINS: the real tool drives the display (not
    // fabricated, not the raw id) — read_file resolves through the SHARED
    // verbRegistry to READ, exactly what the CLI renderer shows.
    expect(screen.getByText("READ")).toBeInTheDocument();

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
    // The status dot uses the FAIL color (#f87171), NOT the done color
    // (#34d399). RE-INVERTED 2026-08-21, session 245, CALLED OUT
    // DELIBERATELY: same ChassisStepNode drift as AC2 above — the failed
    // step renders through a chassis done-node whose colour is an inline
    // BACKGROUND on the node's child div, so the query moved from
    // span[style*="border"] to the chassis-node-done subtree. WHAT THIS
    // ASSERTION STILL PINS, at unchanged strength: the fail colour is
    // present on a real node, and that same node does NOT carry the done
    // colour (a failure must never render as done).
    const nodeDots = Array.from(
      container.querySelectorAll('[data-testid="chassis-node-done"] [style]'),
    ) as HTMLElement[];
    const failDot = nodeDots.find((d) => {
      const s = (d.getAttribute("style") || "").toLowerCase();
      return s.includes("248, 113, 113") || s.includes("f87171");
    });
    expect(failDot).toBeTruthy();
    // The fail dot must NOT carry the done color.
    expect(failDot!.getAttribute("style")).not.toMatch(/34d399/i);
  });

  it("drives border tint + badge from learningSignal (AC6)", () => {
    const steps = makeSteps();
    const { container } = render(
      <TaskListCard steps={steps} learningSignal={"retried" as any} />,
    );
    // The learning signal renders TWICE by design (session 245): the header
    // badge AND the live memory footer's special-effect entry. Assert both.
    expect(screen.getAllByText(/Retried/i)).toHaveLength(2);
    // The badge carries a title exposing the real signal state.
    const badges = screen.getAllByTitle(/Learning signal: Retried/i);
    expect(badges.length).toBeGreaterThanOrEqual(2); // header badge + footer entry
    const badge = badges[0];
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
    // Same dual-render contract as the Retried variant (header badge +
    // footer special-effect entry).
    expect(screen.getAllByText(/Crystallized/i)).toHaveLength(2);
    const badges = screen.getAllByTitle(/Learning signal: Crystallized/i);
    expect(badges.length).toBeGreaterThanOrEqual(2); // header badge + footer entry
    const badge = badges[0];
    expect(badge).toBeInTheDocument();
    const particle = container.querySelector('span[aria-hidden="true"]');
    expect(particle).not.toBeNull();
    expect(particle!.getAttribute("style")).toMatch(/22c55e/i);
  });
});
