"""
T0b (Wave 0) — characterization baseline for LocalModelManager._build_server_cmd.

PURPOSE: pins the argv for the compiled llama-server path so T8 (REQ-4),
which added `--mmproj <path>` when the caller supplies a projector, and T4
(REQ-6), which mirrors this function's `--fit off` fix in lfm_vl_provider.py,
have a concrete "before" to diff against.

BASELINE GAP (specs/unified-vision-routing/tasks.md, Wave 0): zero tests
referenced _build_server_cmd before this file.

UPDATED BY T8 (REQ-4, 2026-08-18): `_build_server_cmd` gained a fourth
parameter, `mmproj_path: Optional[str] = None`. When set, `--mmproj <path>`
is emitted; when absent (the default — every call site written before T8
existed), the argv is byte-for-byte what it was before T8 landed. The two
tests below that characterized "no --mmproj concept exists" have been
INVERTED to describe what is actually true now: the concept exists, and the
no-projector case is the deliberate opt-out/back-compat path (REQ-4 AC2,
CT-5), not an absent feature. New tests were ADDED (not substituted) for the
WITH-projector case, and the full-argv snapshot was EXTENDED with a second,
WITH-projector variant rather than modified in place — the original
snapshot's inputs and assertion are unchanged because calling with no
mmproj_path still produces the exact old argv.

No subprocess, no GPU, no real llama-server binary: _select_server_binary is
monkeypatched to return a fixed fake path so the compiled-server branch is
taken deterministically without touching disk or nvidia-smi.
"""

from multiprocessing import cpu_count

from backend.agent.local_model_manager import LocalModelManager, PROFILES

FAKE_LLAMA_SERVER = "C:/fake/llama-server.exe"
MODEL_PATH = "C:/models/test-model.Q4_K_M.gguf"


def _make_manager_with_fake_server() -> LocalModelManager:
    """LocalModelManager with _select_server_binary forced to a fake compiled
    binary path, so _build_server_cmd always takes the ik_llama.cpp branch."""
    mgr = LocalModelManager()
    mgr._select_server_binary = lambda model_path: FAKE_LLAMA_SERVER
    return mgr


def test_fit_off_is_present():
    """`--fit off` landed in commit e9d2fc89 to disable llama.cpp's own
    device-memory auto-fit search (measured as a 12-36 minute hang on
    LFM2.5-8B-A1B). T0b pins that it stays present."""
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])

    cmd = mgr._build_server_cmd(MODEL_PATH, params)

    assert "--fit" in cmd
    assert cmd[cmd.index("--fit") + 1] == "off"


def test_no_mmproj_flag_when_no_projector_given():
    """INVERTED by T8 (REQ-4): this used to characterize "_build_server_cmd
    has no concept of a vision projector at all". It now pins the deliberate
    opt-out / back-compat case instead — mmproj_path defaults to None, so a
    call site written before T8 existed (or one that explicitly opts out,
    REQ-4 AC2) still gets an argv with no --mmproj / -mm token, byte-for-byte
    identical to the pre-T8 behavior (CT-5)."""
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])

    cmd = mgr._build_server_cmd(MODEL_PATH, params)

    assert "--mmproj" not in cmd
    assert "-mm" not in cmd


def test_mmproj_flag_present_when_projector_given():
    """NEW by T8 (REQ-4 AC1): when the caller passes mmproj_path,
    --mmproj <path> is emitted so the base model actually sees."""
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])
    fake_projector = "C:/models/mmproj-test-model-BF16.gguf"

    cmd = mgr._build_server_cmd(MODEL_PATH, params, mmproj_path=fake_projector)

    assert "--mmproj" in cmd
    assert cmd[cmd.index("--mmproj") + 1] == fake_projector


def test_mmproj_flag_absent_when_opted_out_even_if_available():
    """NEW by T8 (REQ-4 AC2): the caller decides whether to attach — passing
    mmproj_path=None (the opt-out signal load_model() uses when
    with_projector=False) never emits --mmproj, regardless of the model."""
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])

    cmd = mgr._build_server_cmd(MODEL_PATH, params, mmproj_path=None)

    assert "--mmproj" not in cmd


def test_build_server_cmd_full_argv_snapshot():
    """Full argv snapshot for a known model + the 'balanced' profile, so a
    future addition (e.g. T8's --mmproj) is visible as a diff against this
    list rather than discovered incidentally by some other test.

    NOTE on determinism: keep_model_in_memory=True in the balanced profile
    would normally add --mlock, but n_gpu_layers=-1 (full GPU offload) means
    _build_server_cmd deliberately skips --mlock (a locked host copy is dead
    weight once weights are fully resident in VRAM) — see the comment at its
    call site. That's why --mlock does not appear below even though the
    profile requests keep_model_in_memory.
    """
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])

    cmd = mgr._build_server_cmd(MODEL_PATH, params)

    expected = [
        FAKE_LLAMA_SERVER,
        "--model",
        MODEL_PATH,
        "--port",
        str(LocalModelManager.PORT),
        "--host",
        "127.0.0.1",
        "--threads",
        str(cpu_count()),
        "--n-gpu-layers",
        "-1",
        "--fit",
        "off",
        "--ctx-size",
        "32768",
        "--batch-size",
        "2048",
        "--flash-attn",
        "on",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--mmap",
        "--kv-offload",
    ]
    assert cmd == expected


def test_build_server_cmd_full_argv_snapshot_with_projector():
    """EXTENSION (not a replacement) of the snapshot above, added by T8
    (REQ-4 AC1). Same model + 'balanced' profile, but with mmproj_path set —
    pins exactly where --mmproj lands in the argv: right after --threads
    (grouped with the other model-identity flags: --model, --mmproj) and
    before the GPU/context flags, so a future reordering shows as a diff
    here instead of being discovered incidentally."""
    mgr = _make_manager_with_fake_server()
    params = dict(PROFILES["balanced"])
    fake_projector = "C:/models/mmproj-test-model-BF16.gguf"

    cmd = mgr._build_server_cmd(MODEL_PATH, params, mmproj_path=fake_projector)

    expected = [
        FAKE_LLAMA_SERVER,
        "--model",
        MODEL_PATH,
        "--port",
        str(LocalModelManager.PORT),
        "--host",
        "127.0.0.1",
        "--threads",
        str(cpu_count()),
        "--mmproj",
        fake_projector,
        "--n-gpu-layers",
        "-1",
        "--fit",
        "off",
        "--ctx-size",
        "32768",
        "--batch-size",
        "2048",
        "--flash-attn",
        "on",
        "--cache-type-k",
        "q8_0",
        "--cache-type-v",
        "q8_0",
        "--mmap",
        "--kv-offload",
    ]
    assert cmd == expected
