/**
 * ModelBrowserPanel — T9 (REQ-4 AC5, REQ-5 AC3), extending the T0f baseline.
 *
 * T0f pinned the OLD world: a fixture shaped like the pre-T1 `/api/models`
 * payload, where `mmproj-*.gguf` files rendered as their own independently
 * loadable row and no vision-capability indicator existed anywhere. T1
 * (backend) already changed what `scan_models` emits — projector rows are
 * gone, and each base model with a matching projector now carries
 * `has_vision` / `mmproj_path` / `mmproj_size_gb`, with `plan.mmproj_gb`
 * already folded into `plan.vram_gb` (T8). T9 DID change this file: the
 * fixture now mirrors the CURRENT payload shape, and every assertion that
 * pinned the old bugs is inverted below (called out inline as "INVERTED").
 *
 * The two-row load-plan block (row 1: file facts, row 2: the recommend_profile
 * + derive_config plan) landed in e9d2fc89 and is EXTENDED here, not
 * restructured — the original three plan-row assertions (ctx / VRAM / profile)
 * survive unchanged; T9 only appends a fourth, conditional span for the
 * projector cost disclosure.
 */

import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import { ModelBrowserPanel } from "@/components/dashboard/ModelBrowserPanel";

/* ------------------------------------------------------------------ */
/*  Fixture — mirrors today's real /api/models payload (post T1/T8)   */
/* ------------------------------------------------------------------ */

// Text-only model — no `has_vision` field at all, matching a base model with
// no matching projector on disk. Unchanged from the T0f fixture.
const baseModel = {
  path: "C:/models/gemma-4b-e4b.Q4_K_M.gguf",
  filename: "gemma-4b-e4b.Q4_K_M.gguf",
  display_name: "gemma 4b e4b.Q4 K M",
  size_gb: 2.6,
  architecture: "gemma3",
  params_b: 4.0,
  quantization: "Q4_K_M",
  vram_estimate_gb: 3.4,
  native_ctx: 32768,
  loaded: false,
  // The two-row load plan already rendered by the card (e9d2fc89) — computed
  // by the backend's recommend_profile + derive_config, same as plan_load().
  plan: {
    profile: "balanced",
    n_ctx: 16384,
    native_ctx: 32768,
    kv_cache: "f16",
    vram_gb: 3.4,
    vram_free_gb: 8.0,
    fits: true,
    reason: "",
    mmproj_gb: 0.0,
  },
};

// A vision-capable model — gemma-4-E4B, the exact model Decisions Locked 6
// measured (64.5 -> 42.1 tok/s, +1.2GB VRAM with --mmproj). `has_vision` /
// `mmproj_path` / `mmproj_size_gb` are attached by scan_models (T1) after
// matching a sibling mmproj-*.gguf by stem — the projector itself is NEVER
// its own row in this payload (REQ-5 AC1, already enforced backend-side).
// `plan.vram_gb` already has the projector folded in by plan_load (T8), and
// `plan.mmproj_gb` surfaces that component separately for the card (T9).
const visionModel = {
  path: "C:/models/gemma-4-e4b-it.Q4_K_M.gguf",
  filename: "gemma-4-e4b-it.Q4_K_M.gguf",
  display_name: "gemma 4 e4b it.Q4 K M",
  size_gb: 2.6,
  architecture: "gemma3",
  params_b: 4.0,
  quantization: "Q4_K_M",
  vram_estimate_gb: 4.7,
  native_ctx: 32768,
  loaded: false,
  has_vision: true,
  mmproj_path: "C:/models/mmproj-gemma-4-e4b-it-BF16.gguf",
  mmproj_size_gb: 1.2,
  plan: {
    profile: "balanced",
    n_ctx: 16384,
    native_ctx: 32768,
    kv_cache: "f16",
    vram_gb: 4.7,
    vram_free_gb: 8.0,
    fits: true,
    reason: "",
    mmproj_gb: 1.2,
  },
};

const fixturePayload = {
  models: [baseModel, visionModel],
  models_dir: "C:/models",
};

function mockFetchOnce(payload: unknown) {
  (global as any).fetch = jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => payload,
  });
}

async function renderAndSettle(payload: unknown = fixturePayload, props: Partial<React.ComponentProps<typeof ModelBrowserPanel>> = {}) {
  mockFetchOnce(payload);
  render(<ModelBrowserPanel glowColor="#00d4ff" fontColor="#ffffff" {...props} />);
  await waitFor(() => {
    expect(screen.queryByText(/scanning models/i)).not.toBeInTheDocument();
  });
}

describe("ModelBrowserPanel — T9 (REQ-4 AC5, REQ-5 AC3)", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  // INVERTED from T0f's "renders a mmproj-*.gguf entry as a normal loadable
  // row — BUG pinned for T9". The current /api/models payload never contains
  // a projector row at all (T1, backend) — it is attached data on the base
  // model instead. This asserts that inversion: the projector's own filename
  // never appears as a row, and the footer count reflects only the two real,
  // independently-loadable base models.
  it("never renders the projector as its own row — it is attached data on the base model (REQ-5 AC1/AC2)", async () => {
    await renderAndSettle();

    // SCOPING CALLED OUT (T15b): `screen.getByText(visionModel.display_name)`
    // used to be unique on screen. T15b added a second, legitimate place a
    // has_vision model's name renders — the vision fallback ladder's
    // candidate list (REQ-10 AC1) — so a global query now matches twice.
    // Scoped to the model list container instead; same assertion (the model
    // row exists), same coverage, nothing weakened or dropped.
    const modelList = screen.getByTestId("model-list");
    expect(screen.queryByText(/mmproj/i)).not.toBeInTheDocument();
    expect(within(modelList).getByText(baseModel.display_name)).toBeInTheDocument();
    expect(within(modelList).getByText(visionModel.display_name)).toBeInTheDocument();
    expect(screen.getByText("2 models")).toBeInTheDocument();
  });

  // INVERTED from T0f's "shows no vision-capability indicator anywhere —
  // BUG pinned for T9". Keeps BOTH sides: the indicator now DOES appear for
  // the has_vision model, and still does NOT for the text-only one.
  it("shows a vision-capability indicator only on the has_vision model (REQ-5 AC3)", async () => {
    await renderAndSettle();

    const visionRow = screen.getByTestId(`model-row-${visionModel.path}`);
    const textOnlyRow = screen.getByTestId(`model-row-${baseModel.path}`);

    expect(within(visionRow).getByText("VISION")).toBeInTheDocument();
    expect(within(textOnlyRow).queryByText(/vision/i)).not.toBeInTheDocument();
    expect(within(textOnlyRow).queryByTitle(/vision/i)).not.toBeInTheDocument();
  });

  // SURVIVES from T0f, extended rather than replaced. Row 1 (file facts) and
  // the three original row-2 plan spans (ctx / VRAM / profile) are pinned
  // exactly as before, scoped to the text-only model so the new vision-cost
  // span (asserted separately below) cannot be confused with them.
  //
  // INPUT CHANGE CALLED OUT: T0f's fixture had a second entry (the mmproj
  // row) with no `plan`, so exactly one element matched /ctx$/. That entry no
  // longer exists in the current payload — instead there are now TWO real
  // base models, each with its own plan, so /ctx$/ now legitimately matches
  // twice. This is not a weakened assertion; it is the same structural check
  // (one ctx span per plan row) applied to a payload that has the projector
  // removed as its own row (REQ-5 AC1) rather than lacking a plan.
  it("pins the current two-row load-plan structure the card already renders (e9d2fc89), extended for two real models", async () => {
    await renderAndSettle();

    const textOnlyRow = screen.getByTestId(`model-row-${baseModel.path}`);

    // Row 1 — file facts: quantization, size, native context.
    expect(within(textOnlyRow).getByText("Q4_K_M")).toBeInTheDocument();
    expect(within(textOnlyRow).getByText("2.6GB")).toBeInTheDocument();
    expect(within(textOnlyRow).getByText("32k native")).toBeInTheDocument();

    // Row 2 — the load plan itself: target ctx, VRAM cost, profile name.
    // T9 extends this row (the projector-cost figure, asserted separately);
    // it must not replace these three pieces of information.
    expect(within(textOnlyRow).getByText("→ 16k ctx")).toBeInTheDocument();
    expect(within(textOnlyRow).getByText("3.4GB VRAM")).toBeInTheDocument();
    expect(within(textOnlyRow).getByText("balanced")).toBeInTheDocument();

    // Both base models in the fixture carry a plan now (the projector is no
    // longer a row-without-a-plan) — one ctx span per model, two total.
    expect(screen.getAllByText(/ctx$/)).toHaveLength(2);
  });

  // NEW (REQ-4 AC5 / Decisions Locked 6): the measured cost of attaching the
  // projector — gemma-4-E4B 64.5 -> 42.1 tok/s (-35% generation) and the
  // projector's own +1.2GB — must be visible on the card, never hidden,
  // since it is precisely why a user would knowingly choose a multimodal
  // brain over a faster text-only one. Scoped to the vision row; absent on
  // the text-only row.
  it("surfaces the measured projector cost when attaching (REQ-4 AC5)", async () => {
    await renderAndSettle();

    const visionRow = screen.getByTestId(`model-row-${visionModel.path}`);
    const textOnlyRow = screen.getByTestId(`model-row-${baseModel.path}`);

    expect(within(visionRow).getByText(/\+1\.2GB vision/)).toBeInTheDocument();
    expect(within(visionRow).getByText(/-35% gen/)).toBeInTheDocument();
    expect(within(textOnlyRow).queryByText(/vision/i)).not.toBeInTheDocument();
  });

  // NEW (REQ-4 AC2): a control to load WITHOUT the projector, sending
  // `with_projector: false`. Default Load (unchanged) omits the key entirely
  // — an absent key still means attach (CT-5 back-compat), so this test only
  // asserts the opt-out path adds it.
  it("offers a load-without-projector control that sends with_projector: false (REQ-4 AC2)", async () => {
    const sendMessage = jest.fn().mockReturnValue(true);
    await renderAndSettle(fixturePayload, { sendMessage });

    const visionRow = screen.getByTestId(`model-row-${visionModel.path}`);
    const textOnlyButton = within(visionRow).getByRole("button", { name: /text only/i });

    const { fireEvent } = await import("@testing-library/react");
    fireEvent.click(textOnlyButton);

    expect(sendMessage).toHaveBeenCalledWith("load_local_model", {
      model_path: visionModel.path,
      with_projector: false,
    });

    // The text-only model has nothing to opt out of — no such control on it.
    const textOnlyRow = screen.getByTestId(`model-row-${baseModel.path}`);
    expect(within(textOnlyRow).queryByRole("button", { name: /text only/i })).not.toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/*  T15b (REQ-10 AC2) — vision fallback ladder selection + ordering   */
/* ------------------------------------------------------------------ */

// A second has_vision model — the smaller LFM2.5-VL-450M-shaped candidate —
// so ordering has something real to order. `path` differs from visionModel's;
// both carry has_vision so both must appear as ladder candidates.
const visionModel2 = {
  path: "C:/models/lfm2.5-vl-450m.Q4_K_M.gguf",
  filename: "lfm2.5-vl-450m.Q4_K_M.gguf",
  display_name: "lfm2.5 vl 450m.Q4 K M",
  size_gb: 0.5,
  architecture: "lfm2",
  params_b: 0.45,
  quantization: "Q4_K_M",
  vram_estimate_gb: 0.7,
  native_ctx: 32768,
  loaded: false,
  has_vision: true,
  mmproj_path: "C:/models/mmproj-LFM2.5-VL-450M-F16.gguf",
  mmproj_size_gb: 0.2,
  plan: {
    profile: "eco",
    n_ctx: 8192,
    native_ctx: 32768,
    kv_cache: "f16",
    vram_gb: 0.7,
    vram_free_gb: 8.0,
    fits: true,
    reason: "",
    mmproj_gb: 0.2,
  },
};

const ladderFixturePayload = {
  models: [baseModel, visionModel, visionModel2],
  models_dir: "C:/models",
  vision_fallback_ladder: [] as string[],
};

describe("ModelBrowserPanel — T15b (REQ-10 AC2)", () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it("offers only has_vision models as ladder candidates (REQ-10 AC1)", async () => {
    await renderAndSettle(ladderFixturePayload);

    const ladderSection = screen.getByTestId("vision-ladder-section");
    expect(within(ladderSection).getByTestId(`vision-candidate-${visionModel.path}`)).toBeInTheDocument();
    expect(within(ladderSection).getByTestId(`vision-candidate-${visionModel2.path}`)).toBeInTheDocument();
    // The text-only base model is never offered as a candidate.
    expect(within(ladderSection).queryByTestId(`vision-candidate-${baseModel.path}`)).not.toBeInTheDocument();

    // Each candidate's own size and its projector size are both shown, so
    // the choice is informed (fallback footprint = weights + projector).
    const model2Row = within(ladderSection).getByTestId(`vision-candidate-${visionModel2.path}`);
    expect(within(model2Row).getByText(/0\.5GB/)).toBeInTheDocument();
    expect(within(model2Row).getByText(/\+0\.2GB proj/)).toBeInTheDocument();
  });

  it("shows AUTO when the user has selected nothing (REQ-10 AC5)", async () => {
    await renderAndSettle(ladderFixturePayload);

    const ladderSection = screen.getByTestId("vision-ladder-section");
    expect(within(ladderSection).getByText(/AUTO/)).toBeInTheDocument();
  });

  it("persists the chosen ORDER over confirm_card as the user selects and reorders (REQ-10 AC2/AC3)", async () => {
    const sendMessage = jest.fn().mockReturnValue(true);
    await renderAndSettle(ladderFixturePayload, { sendMessage });

    const { fireEvent } = await import("@testing-library/react");
    const ladderSection = screen.getByTestId("vision-ladder-section");
    const row1 = within(ladderSection).getByTestId(`vision-candidate-${visionModel.path}`);
    const row2 = within(ladderSection).getByTestId(`vision-candidate-${visionModel2.path}`);

    // Select the 3B first, then the 450M — order of SELECTION becomes order
    // of PRIORITY: [visionModel, visionModel2].
    fireEvent.click(within(row1).getByTitle(/add to the vision fallback ladder/i));
    fireEvent.click(within(row2).getByTitle(/add to the vision fallback ladder/i));

    expect(sendMessage).toHaveBeenLastCalledWith("confirm_card", {
      section_id: "vision_fallback_ladder",
      values: { vision_fallback_ladder: [visionModel.path, visionModel2.path] },
    });

    // AUTO no longer shown once something is selected.
    expect(within(ladderSection).queryByText(/AUTO/)).not.toBeInTheDocument();

    // Promote the 450M above the 3B — the persisted order flips.
    const promoteButton = within(row2).getByTitle(/higher priority/i);
    fireEvent.click(promoteButton);

    expect(sendMessage).toHaveBeenLastCalledWith("confirm_card", {
      section_id: "vision_fallback_ladder",
      values: { vision_fallback_ladder: [visionModel2.path, visionModel.path] },
    });
  });
});
