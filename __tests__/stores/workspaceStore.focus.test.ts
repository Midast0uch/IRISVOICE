/**
 * cli-workspace-unification T12 — focus-mode filter + multi-agent Kanban flow.
 *
 * Unit (REQ-6): Focus presets cycle FULL -> ACTIVE -> PROJECT -> COMPACT and
 * drive board density (kanbanCompact).
 *
 * Behavioral (REQ-5): `iris:task_update` window events flow through
 * upsertFromTaskUpdate into the store — backend-emitted tags are kept
 * verbatim, missing tags fall back to conversationId-only keying, and the
 * board caps at 50 cards (bounded memory).
 */

import { useWorkspaceStore } from "@/stores/workspaceStore";
import { upsertFromTaskUpdate } from "@/hooks/useAgentTaskEvents";

beforeEach(() => {
  useWorkspaceStore.setState({
    focusPreset: "full",
    isFocusMode: false,
    kanbanCompact: false,
    agentTasks: [],
  });
});

describe("Focus Mode presets (T8, REQ-6)", () => {
  test("cycles full -> active -> project -> compact -> full", () => {
    const s = useWorkspaceStore.getState();
    s.toggleFocusMode();
    expect(useWorkspaceStore.getState().focusPreset).toBe("active");
    s.toggleFocusMode();
    expect(useWorkspaceStore.getState().focusPreset).toBe("project");
    s.toggleFocusMode();
    expect(useWorkspaceStore.getState().focusPreset).toBe("compact");
    s.toggleFocusMode();
    expect(useWorkspaceStore.getState().focusPreset).toBe("full");
  });

  test("COMPACT drives kanbanCompact density; FULL clears it", () => {
    const s = useWorkspaceStore.getState();
    s.setFocusPreset("compact");
    expect(useWorkspaceStore.getState().kanbanCompact).toBe(true);
    expect(useWorkspaceStore.getState().isFocusMode).toBe(true);
    s.setFocusPreset("full");
    expect(useWorkspaceStore.getState().kanbanCompact).toBe(false);
    expect(useWorkspaceStore.getState().isFocusMode).toBe(false);
  });

  test("legacy terminal-collapse configs are gone (presets no longer touch showTerminal/showArchive)", () => {
    const before = {
      showTerminal: useWorkspaceStore.getState().showTerminal,
      showArchive: useWorkspaceStore.getState().showArchive,
    };
    useWorkspaceStore.getState().setFocusPreset("zen" as never);
    // 'zen' is not a valid preset anymore — the store must not crash and must
    // not touch section visibility either way.
    const after = useWorkspaceStore.getState();
    expect(after.showTerminal).toBe(before.showTerminal);
    expect(after.showArchive).toBe(before.showArchive);
  });
});

describe("Multi-agent Kanban task flow (T9, REQ-5)", () => {
  function dispatchTaskUpdate(detail: Record<string, unknown>) {
    window.dispatchEvent(new CustomEvent("iris:task_update", { detail }));
  }

  test("task:start with backend tags keys by card_id and keeps tags verbatim", () => {
    upsertFromTaskUpdate({
      type: "task:start",
      task_id: "t1",
      card_id: "card_t1",
      plan_title: "Build the thing",
      total_steps: 4,
      agent_id: "sess_1",
      project_id: "proj_iris",
      conversation_id: "conv_9",
    });
    const tasks = useWorkspaceStore.getState().agentTasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0]).toMatchObject({
      key: "card_t1",
      status: "in_progress",
      agentId: "sess_1",
      projectId: "proj_iris",
      conversationId: "conv_9",
    });
  });

  test("missing tags fall back to conversationId-only keying without dropping the card", () => {
    upsertFromTaskUpdate({ type: "task:start", task_id: "t2", conversation_id: "conv_only" });
    const tasks = useWorkspaceStore.getState().agentTasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0].key).toBe("t2");
    expect(tasks[0].agentId).toBeNull();
    expect(tasks[0].projectId).toBeNull();
    expect(tasks[0].conversationId).toBe("conv_only");
  });

  test("task:done crystallizes; task:fail lands in REVIEW with failed flag", () => {
    upsertFromTaskUpdate({ type: "task:start", task_id: "t3", card_id: "c3", conversation_id: "cv" });
    upsertFromTaskUpdate({ type: "task:done", task_id: "t3", card_id: "c3", outcome: "success" });
    upsertFromTaskUpdate({ type: "task:start", task_id: "t4", card_id: "c4", conversation_id: "cv" });
    upsertFromTaskUpdate({ type: "task:fail", task_id: "t4", card_id: "c4", error: "verify_failed" });

    const byKey = Object.fromEntries(
      useWorkspaceStore.getState().agentTasks.map((t) => [t.key, t])
    );
    expect(byKey["c3"].status).toBe("crystallized");
    expect(byKey["c4"].status).toBe("review");
    expect(byKey["c4"].failed).toBe(true);
  });

  test("window event path wires through (the same channel useIRISWebSocket feeds)", () => {
    // Wire the SAME listener the hook mounts on dashboard surfaces.
    const handler = (e: Event) =>
      upsertFromTaskUpdate((e as CustomEvent<Record<string, unknown>>).detail);
    window.addEventListener("iris:task_update", handler);
    try {
      dispatchTaskUpdate({
        type: "task:start",
        task_id: "t5",
        card_id: "c5",
        agent_id: "a5",
        conversation_id: "cv5",
      });
      expect(useWorkspaceStore.getState().agentTasks[0]?.key).toBe("c5");
    } finally {
      window.removeEventListener("iris:task_update", handler);
    }
  });

  test("board is bounded at 50 cards (quality check: bounded memory)", () => {
    for (let i = 0; i < 60; i++) {
      upsertFromTaskUpdate({
        type: i % 2 === 0 ? "task:start" : "task:done",
        task_id: `bulk_${i}`,
        card_id: `bulk_${i}`,
        conversation_id: "cv_bulk",
      });
    }
    expect(useWorkspaceStore.getState().agentTasks.length).toBeLessThanOrEqual(50);
  });
});
