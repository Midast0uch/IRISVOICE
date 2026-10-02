# CONFLICT-FLAG (stash pop 2026-09-06, resolved session-299): this file had a
# whole-file conflict — upstream side (2268 lines, port 18181, leases,
# borrowed servers) kept; stashed side (662 lines, port 8081, ancestral)
# dropped. Upstream == HEAD modulo em-dash encoding fixes. Stash entries
# (git stash list) remain for archaeology.
"""
LFM2.5-VL Vision Provider — vision client with NO spawn (specs/vision-single-server).

Synchronous OpenAI-compatible HTTP client for the SHARED multimodal server.
Tier 3 never starts a process: vision resolves by discovering an already-
running multimodal endpoint (the shared local model server hosting a
projector-backed model, or any configured API/LOCAL_OPENAI provider that
verifies multimodal). When none exists, every entry point fails LOUDLY with
VisionModelUnavailable — there is no standalone llama-server to spawn; the
old port-18181 spawn machinery was deleted 2026-09-18.
"""
import base64
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy default endpoint (kept as the fallback URL for LFMVLConfig only; NO
# server is spawned there — specs/vision-single-server). Points at the shared
# local model server (LocalModelManager, default port 8082) so the LFMVLConfig
# default is "the shared server" rather than a dead port.
# ---------------------------------------------------------------------------
_VISION_PORT: int = int(os.environ.get("IRIS_VISION_PORT", "8082"))



# ── The ONLY vision source: a shared multimodal server ───────────────────────
# specs/vision-single-server (2026-09-18): the standalone 18181 llama-server
# spawn path is DELETED (~6-minute, wildly variable cold starts). Vision
# traffic is routed to an ALREADY-RUNNING multimodal OpenAI-compatible server:
# the shared local model server when it hosts a projector-backed model (the
# intended path), or another configured provider. We never start, stop, or
# restart that server from here.
#
# CRITICAL: a text-only server answers `/models` happily and then fails every
# vision call. So reuse is gated on a real multimodal round trip, NOT an id
# match — an id match is a GUESS about capability; a successful 1x1-PNG
# completion is PROOF. Verdicts are cached per endpoint so the probe is paid
# once per process, not per call.
#
# Opt-out: set IRIS_VISION_REUSE_ENABLED=0 to refuse borrowed servers (vision
# then serves ONLY from a tier-1/2 vision-capable brain, or is unavailable).
# (endpoint, cred_ref, vision_model) — vision_model is the user's pinned VLM id
# ("" => auto-pick first multimodal). Registered borrowed candidates (tests/advanced).
_EXTRA_VISION_ENDPOINTS: list[tuple[str, Optional[str], str]] = []
# (endpoint, preferred_model) -> (model_id if capable else None, monotonic stamp).
# Positive AND negative verdicts expire after _CAPABILITY_TTL_S: a server that
# loads (or drops) a projector later is re-proved, and a dead or text-only
# endpoint is not re-probed on every resolution inside the window (V4).
_VISION_CAPABILITY_CACHE: dict[tuple[str, str], tuple[Optional[str], float]] = {}
_CAPABILITY_TTL_S = 300.0
# A local server lists only what it serves (llama-server: the loaded model;
# router mode: a few), but an Ollama-style catalog lists every pulled model and
# answers each probe by LOADING it. Bound the image round trips per endpoint.
_LOCAL_PROBE_CAP = 4

# Reuse state: set when discovery selects a borrowed server. _call()/health_check()
# consult these so vision traffic is actually routed to the borrowed server.
_reused_vision_base_url: Optional[str] = None
_reused_vision_auth: Optional[str] = None
_reused_vision_model: Optional[str] = None

# The capability probe image: 32x16 PNG, left half solid red, right half solid
# blue. "HTTP 200 with choices" is NOT proof of sight — a text-only server
# (live: NVIDIA openai/gpt-oss-20b) drops the image and answers anyway (V3).
# Proof is the model NAMING both colours; a blind guess names both rarely.
_PROBE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAQCAIAAAD4YuoOAAAAIElEQVR42mP4z8BAEiJR+X+GUQtGLRi1YNSCUQuGggUAUKb+ELySDi8AAAAASUVORK5CYII="
)
_PROBE_PROMPT = (
    "The image has a left half and a right half, each one solid colour. "
    "Name the two colours, left first, in at most four words."
)
_PROBE_EXPECT = ("red", "blue")


def set_vision_candidate_endpoints(endpoints) -> None:
    """Replace the list of registered borrowed vision-server candidates.

    Each item is a URL string, or a (url, vision_model) / (url, cred_ref,
    vision_model) tuple. Used by tests and advanced callers. Replaces (does not
    append) so re-configuring cannot accumulate stale entries. The primary
    candidate source is the user's iris_config providers (see
    _load_candidate_endpoints_from_config)."""
    global _EXTRA_VISION_ENDPOINTS
    _norm: list[tuple[str, Optional[str], str]] = []
    for _e in (endpoints or []):
        if isinstance(_e, str):
            if _e:
                _norm.append((_e, None, ""))
        elif isinstance(_e, (tuple, list)):
            _url = _e[0] if len(_e) > 0 else ""
            _cred = _e[1] if len(_e) > 1 else None
            _vm = _e[2] if len(_e) > 2 else ""
            if _url:
                _norm.append((_url, _cred, _vm))
    _EXTRA_VISION_ENDPOINTS = _norm


def register_vision_candidate_endpoint(url: str) -> None:
    """Append a single borrowed vision-server candidate (idempotent)."""
    global _EXTRA_VISION_ENDPOINTS
    if url and url not in [e[0] for e in _EXTRA_VISION_ENDPOINTS]:
        _EXTRA_VISION_ENDPOINTS = list(_EXTRA_VISION_ENDPOINTS) + [(url, None, "")]


def clear_vision_capability_cache() -> None:
    """Drop cached capability verdicts AND any active reuse selection.

    Used by tests between cases and to force re-discovery."""
    _VISION_CAPABILITY_CACHE.clear()
    _reset_reused_vision_server()


def _reset_reused_vision_server() -> None:
    global _reused_vision_base_url, _reused_vision_auth, _reused_vision_model
    _reused_vision_base_url = None
    _reused_vision_auth = None
    _reused_vision_model = None


def _normalise_vision_base_url(url: str) -> str:
    """OpenAI-compatible servers expose their API under `/v1`. The IRIS-owned
    `base_url` already ends in `/v1`; user-configured endpoints (e.g.
    `http://localhost:1234`) usually do NOT. Normalise so the probe hits
    `/v1/models` and `/v1/chat/completions` rather than the bare root (which
    404s and would make every borrowed server look dead)."""
    url = (url or "").rstrip("/")
    if not url:
        return url
    if url.endswith("/v1"):
        return url
    return url + "/v1"


def _read_global_vision_model_pin() -> str:
    """The user's preferred VLM, set via the vision-card dropdown (persisted to
    ``field_values['vision']['vision_model']``). Empty => auto-pick the first
    multimodal model during probe / the widest-first ladder during local spawn.
    Never raises — a broken config must not crash vision."""
    try:
        from backend.iris_config import load_config

        _cfg = load_config()
        _fv = getattr(_cfg, "field_values", None) or {}
        _vision = _fv.get("vision", {}) if isinstance(_fv, dict) else {}
        return str(_vision.get("vision_model", "") or "")
    except Exception:
        return ""


def _load_candidate_endpoints_from_config() -> list[tuple[str, Optional[str], str]]:
    """Return (endpoint, cred_ref, vision_model_pin) for configured providers that
    are OpenAI-compatible AND have both an endpoint and a credential.

    The third field is the model to try FIRST on that endpoint. LOCAL_OPENAI
    providers and the shared server get the user's vision pin (a scanned GGUF
    path from the vision card dropdown - meaningful only to a local server).
    An API provider gets ITS OWN configured model: a paid catalog is never
    scanned with image requests (V4 - NVIDIA lists 81 models), and a local
    file path means nothing to it. Excludes LM_STUDIO (own routing path)
    and OLLAMA (different API shape). Safe to call anytime: reads only the local
    config JSON; the credential itself is never read here (only its keyring key,
    ``cred_ref``, resolved lazily at probe time)."""
    _pin = _read_global_vision_model_pin()
    try:
        from backend.iris_config import load_config

        _cfg = load_config()
        _inference = getattr(_cfg, "inference", None)
        _providers = getattr(_inference, "providers", {}) or {}
    except Exception:
        return []
    _out: list[tuple[str, Optional[str], str]] = []
    for _p in _providers.values():
        if getattr(_p, "kind", "") not in ("API", "LOCAL_OPENAI"):
            continue
        _ep = getattr(_p, "endpoint", "") or ""
        if not _ep:
            continue
        _cred = getattr(_p, "cred_ref", "") or ""
        _first = _pin if getattr(_p, "kind", "") == "LOCAL_OPENAI" else (
            getattr(_p, "model", "") or ""
        )
        _out.append((_ep, _cred or None, _first))
    # The SHARED local model server enters the candidate set when it is
    # running AND its active model was loaded with a projector (the
    # truthful signal is vision_loaded, set only when --mmproj actually made
    # it onto the running server's argv — REQ-4 AC4). This is the primary
    # tier-3 source after specs/vision-single-server: one process, already
    # loaded, vision OFF the spawn path entirely. Best-effort: any failure
    # here just means no local candidate.
    try:
        from backend.agent.local_model_manager import get_local_model_manager

        _mgr = get_local_model_manager()
        _st = _mgr.get_status()
        if _st.get("loaded") and _st.get("vision_loaded") and _st.get("endpoint"):
            _out.append((_st["endpoint"], None, _pin))
    except Exception:
        pass
    return _out


def _fetch_provider_secret(cred_ref: Optional[str]) -> Optional[str]:
    """Best-effort keyring lookup for a provider credential. Returns None if no
    cred_ref, or on any failure (the server may not need a key). Never raises."""
    if not cred_ref:
        return None
    try:
        from backend.agent.inference.keyring import get_secret

        return get_secret(cred_ref)
    except Exception:
        return None


def _is_local_endpoint(url: str) -> bool:
    """True for a server on this machine (no money, no catalog of strangers)."""
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001 — an unparsable URL is not local
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def _candidate_vision_specs(base_url: str) -> list[tuple[str, Optional[str], str]]:
    """All borrowed candidates to probe, as (normalised_endpoint, cred_ref,
    first_model), LOCAL servers first.

    No endpoint is excluded: the old rule dropped `base_url` (default
    127.0.0.1:8082) as "IRIS-owned" - a leftover from the deleted 18181 spawn
    server. 8082 IS the shared local model server, so the rule made the local
    VLM unreachable for tier 3 (V2). `base_url` is kept for the call shape."""
    del base_url
    _out: list[tuple[str, Optional[str], str]] = []
    _seen: set[str] = set()
    # 1. Configured providers + the shared server (primary source).
    # 2. Explicitly registered endpoints (tests / advanced callers).
    _raw = list(_load_candidate_endpoints_from_config()) + [
        (_e[0], _e[1], _e[2]) for _e in _EXTRA_VISION_ENDPOINTS if _e
    ]
    for _ep, _cred, _vm in _raw:
        _norm = _normalise_vision_base_url(_ep)
        if not _norm or _norm in _seen:
            continue
        _seen.add(_norm)
        _out.append((_norm, _cred, _vm))
    # Local first (V4): a local VLM costs nothing and is the owner's fallback;
    # paid API endpoints are probed only when no local server can see.
    _out.sort(key=lambda c: not _is_local_endpoint(c[0]))
    return _out


def _probe_vision_capability(
    base_url: str, auth: Optional[str] = None, preferred_model: Optional[str] = None
) -> Optional[str]:
    """Return the served VLM model id iff the server at `base_url` is a MULTIMODAL
    OpenAI-compatible server we can safely reuse; otherwise None. Never raises.

    If `preferred_model` is set, that exact model id is tested FIRST; if it is
    multimodal we use it (the user's pinned choice, e.g. lfm2.5-vl-3b).

    A LOCAL endpoint then falls back to the models it lists (router-mode
    servers hosting an LLM + VLM on one process, routed by the `model` field),
    at most _LOCAL_PROBE_CAP image round trips. A REMOTE endpoint is tried on
    `preferred_model` ONLY - never a scan of a paid catalog (V4).

    Published metadata decides before any image is sent: an entry that states
    its input modalities (OpenRouter `architecture.input_modalities`, a
    `capabilities` list) is trusted - image -> capable, no image -> skipped."""
    _headers = {"Authorization": f"Bearer {auth}"} if auth else None
    try:
        import httpx

        _r = httpx.get(f"{base_url}/models", headers=_headers, timeout=2.0)
        if _r.status_code != 200:
            return None
        try:
            _data = _r.json()
        except Exception:
            return None
        _models = _data.get("data", []) if isinstance(_data, dict) else []
        if not _models:
            return None
        _meta = {
            str((_m or {}).get("id")): _published_vision(_m)
            for _m in _models if isinstance(_m, dict) and _m.get("id")
        }
        _probe_timeout = float(os.environ.get("IRIS_VISION_PROBE_TIMEOUT_S", "15"))
        # The pin may be a local model PATH (from the vision-card dropdown, which
        # lists scanned GGUF paths) while a borrowed router-mode server serves
        # models by FILENAME — so also try the basename to bridge the two.
        # The bridge is for FILE pins only: a remote id like "org/model" is a
        # different model once cut ("cline-pass/kimi-k3" -> "kimi-k3").
        _local = _is_local_endpoint(base_url)
        _order: list = []
        if preferred_model:
            _order.append(preferred_model)
            _base = os.path.basename(preferred_model)
            _file_pin = "\\" in preferred_model or preferred_model.lower().endswith(".gguf")
            if _base and _base != preferred_model and (_local or _file_pin):
                _order.append(_base)
        if _local:
            # Ollama lists "<name>:<tag>-cloud" models: remote models behind
            # the local port - never probed as a local fallback.
            _order += [m for m in _meta if not m.lower().endswith("cloud")]
        _probes = 0
        _tried: set = set()
        for _model_id in _order:
            if not _model_id or _model_id in _tried:
                continue
            _tried.add(_model_id)
            _published = _meta.get(_model_id)
            if _published is True:
                return _model_id
            if _published is False:
                continue
            if _local:
                if _probes >= _LOCAL_PROBE_CAP:
                    break
                _probes += 1
            if _model_is_multimodal(base_url, _model_id, _headers, _probe_timeout):
                return _model_id
        return None
    except Exception:
        return None


def _published_vision(entry: dict) -> Optional[bool]:
    """What a /models entry PUBLISHES about image input: True, False, or None
    when it says nothing (then only the probe can tell). Never raises."""
    try:
        _arch = entry.get("architecture")
        if isinstance(_arch, dict) and isinstance(_arch.get("input_modalities"), list):
            return "image" in [str(m).lower() for m in _arch["input_modalities"]]
        for _key in ("input_modalities", "modalities"):
            if isinstance(entry.get(_key), list):
                return "image" in [str(m).lower() for m in entry[_key]]
        _caps = entry.get("capabilities")
        if isinstance(_caps, list) and _caps:
            _caps_l = [str(c).lower() for c in _caps]
            return "vision" in _caps_l or "multimodal" in _caps_l
    except Exception:  # noqa: BLE001 — unreadable metadata says nothing
        return None
    return None


def _model_is_multimodal(
    base_url: str, model_id: str, headers: Optional[dict], timeout: float
) -> bool:
    """Proof that `model_id` on this server SEES an image: it must name both
    colours of the red|blue probe image. A 200 with choices is not enough - a
    text-only model drops the image and still answers (V3). Never raises."""
    try:
        import httpx

        _resp = httpx.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{_PROBE_PNG_B64}"
                                },
                            },
                            {"type": "text", "text": _PROBE_PROMPT},
                        ],
                    }
                ],
                # Headroom for a short answer; a model that hides reasoning
                # first may still run out - that reads as "cannot see".
                "max_tokens": 64,
                "temperature": 0,
            },
            timeout=timeout,
        )
        if _resp.status_code != 200:
            return False
        try:
            _j = _resp.json()
        except Exception:
            return False
        if not isinstance(_j, dict) or "error" in _j:
            return False
        _choices = _j.get("choices") or [{}]
        _msg = (_choices[0] or {}).get("message") or {}
        _text = str(_msg.get("content") or "").lower()
        _ok = all(_c in _text for _c in _PROBE_EXPECT)
        if not _ok:
            logger.info(
                "[LFMVLProvider] probe model=%s at %s did not name the probe "
                "colours (answer=%r): not vision-capable",
                model_id, base_url, _text[:80],
            )
        return _ok
    except Exception:
        return False


def _is_verified_vision_capable(
    url: str, auth: Optional[str] = None, preferred_model: Optional[str] = None
) -> Optional[str]:
    """Cached wrapper around `_probe_vision_capability`. Returns the model id if
    capable, else None. Cache keyed by (endpoint, preferred_model) so a pinned
    choice and an auto-scan don't collide."""
    _key = (url, preferred_model or "")
    _hit = _VISION_CAPABILITY_CACHE.get(_key)
    if _hit is not None and time.monotonic() - _hit[1] < _CAPABILITY_TTL_S:
        return _hit[0]
    _model_id = _probe_vision_capability(url, auth=auth, preferred_model=preferred_model)
    _VISION_CAPABILITY_CACHE[_key] = (_model_id, time.monotonic())
    return _model_id


def _discover_reusable_vision_server(base_url: str) -> Optional[str]:
    """Probe borrowed candidates for a verified multimodal server.

    Returns the first reusable endpoint, or None if none verify. On success,
    records the reuse selection (endpoint + credential + model id) so _call()
    routes vision traffic to the borrowed server. Runs OUTSIDE the spawn lock;
    never spawns, never raises.
    """
    if os.environ.get("IRIS_VISION_REUSE_ENABLED", "1").lower() in ("0", "false", "no"):
        return None
    for _cand, _cred, _vm in _candidate_vision_specs(base_url):
        try:
            _secret = _fetch_provider_secret(_cred)
            _model_id = _is_verified_vision_capable(_cand, auth=_secret, preferred_model=_vm or None)
            if _model_id:
                global _reused_vision_base_url, _reused_vision_auth, _reused_vision_model
                _reused_vision_base_url = _cand
                _reused_vision_auth = _secret
                _reused_vision_model = _model_id
                logger.info(
                    "[LFMVLProvider] discovered reusable multimodal vision "
                    "server at %s (model=%s); routing vision calls there, no spawn",
                    _cand, _model_id,
                )
                return _cand
            logger.info(
                "[LFMVLProvider] candidate %s not multimodal-capable; skipping",
                _cand,
            )
        except Exception as _exc:  # noqa: BLE001 — discovery must never break spawn
            logger.debug(
                "[LFMVLProvider] capability probe error for %s: %s", _cand, _exc
            )
    return None


def _active_vision_base_url(base_url: str = "") -> str:
    """The endpoint vision calls should target: the borrowed server if one was
    discovered, else the IRIS-owned `base_url` passed by the caller."""
    return _reused_vision_base_url or (base_url or f"http://127.0.0.1:{_VISION_PORT}/v1")


def _active_vision_auth() -> Optional[str]:
    return _reused_vision_auth


def _active_vision_model() -> str:
    return _reused_vision_model or "vision-model"


# ── P3 auto-provision (session-342, owner decision) ──────────────────────────
# The owner asked for auto-load with "minimal risk and zero disruption to the
# agent". The architecture answers that: LocalModelManager is SINGLE-SLOT —
# loading a model evicts whatever is loaded. So the ONLY lawful auto-load is
# the empty-slot case: nothing resident, nothing to disrupt. A resident
# non-multimodal model is NEVER touched from here (evicting the user's loaded
# model mid-turn is the disruption we are forbidden from); the fix for that
# user is to load a projector-backed model ONCE, after which vision is free.
# Two consent anchors keep it safe: the model auto-loaded is the user's OWN
# pinned vision model (vision-card dropdown / IRIS_VISION_AUTOLOAD_MODEL) —
# autoload never CHOOSES a model, it only loads the one already chosen — and
# the load runs through LocalModelManager.load_model(), the same code the UI's
# Apply button runs, pre-flight VRAM check included.
_VISION_AUTOLOAD_ENABLED = os.environ.get("IRIS_VISION_AUTOLOAD", "1").lower() not in (
    "0", "false", "no",
)
_VISION_AUTOLOAD_TIMEOUT_S = float(os.environ.get("IRIS_VISION_AUTOLOAD_TIMEOUT_S", "150"))
_VISION_AUTOLOAD_HINT = os.environ.get("IRIS_VISION_AUTOLOAD_MODEL", "").strip()
_autoload_lock = threading.Lock()


def _read_vision_fallback_ladder() -> list:
    """The user's ordered vision models (model browser, REQ-10): a list of
    scanned GGUF paths, first = most wanted. Never raises."""
    try:
        from backend.iris_config import load_config

        return [str(p) for p in (load_config().inference.vision_fallback_ladder or []) if p]
    except Exception:  # noqa: BLE001 — a broken config means no ladder
        return []


def _autoload_hints() -> list:
    """The models autoload may load, in order - ONE mechanism (V7, owner
    decision 2026-10-02): an explicit IRIS_VISION_AUTOLOAD_MODEL hint, else
    the vision fallback ladder, else (empty ladder) the vision card pin."""
    if _VISION_AUTOLOAD_HINT:
        return [_VISION_AUTOLOAD_HINT]
    ladder = _read_vision_fallback_ladder()
    if ladder:
        return ladder
    try:
        pin = _read_global_vision_model_pin()
    except Exception:  # noqa: BLE001 — a broken config means no autoload
        pin = ""
    return [pin] if pin else []


def _hint_matches(hint: str, entry: dict) -> bool:
    """Does a hint name this scan entry?

    A PATH hint matches by file name or by resolved path: the pin says
    D:\\lmstudio\\models\\..., the scan walks C:\\Users\\...\\.lmstudio\\models
    (a junction to the same folder), so a substring of the full path never
    matched (V6). A NAME hint ("LFM2.5-VL-3B") stays a substring match."""
    h = hint.strip()
    if not h:
        return False
    if any(sep in h for sep in ("/", "\\")) or h.lower().endswith(".gguf"):
        if os.path.basename(h).lower() == str(entry.get("filename", "")).lower():
            return True
        try:
            return os.path.normcase(os.path.realpath(h)) == os.path.normcase(
                os.path.realpath(str(entry.get("path", "")))
            )
        except Exception:  # noqa: BLE001 — an unresolvable path does not match
            return False
    hl = h.lower()
    return (
        hl in str(entry.get("path", "")).lower()
        or hl in str(entry.get("filename", "")).lower()
        or hl in str(entry.get("display_name", "")).lower()
    )


def _find_autoload_vision_models() -> list:
    """The projector-backed GGUF paths autoload may load, in hint order.

    Consent anchor: the ONLY candidates considered are the user's recorded
    choices (``_autoload_hints``). With none, this returns [] — autoload
    NEVER picks a model on its own, so a fresh install (or a test machine)
    cannot have gigabytes loaded without a recorded choice. Candidates are
    projector-backed scan entries — the SAME pairing the model browser shows
    (has_vision/mmproj_path). Never raises.
    """
    hints = _autoload_hints()
    if not hints:
        return []
    try:
        from backend.agent.local_model_manager import get_local_model_manager

        entries = get_local_model_manager().scan_models()
    except Exception as exc:  # noqa: BLE001
        logger.info("[LFMVLProvider] autoload: model scan failed: %s", exc)
        return []
    candidates = sorted(
        (e for e in (entries or []) if e.get("mmproj_path") and e.get("path")),
        key=lambda e: e.get("filename", ""),
    )
    out: list = []
    for hint in hints:
        for e in candidates:
            if _hint_matches(hint, e) and e["path"] not in out:
                out.append(e["path"])
                break
        else:
            logger.info(
                "[LFMVLProvider] autoload: chosen model %r matched no "
                "projector-backed model on disk",
                hint,
            )
    return out


def _find_autoload_vision_model() -> Optional[str]:
    """The first model autoload would load, or None."""
    found = _find_autoload_vision_models()
    return found[0] if found else None


def vision_autoload_possible() -> bool:
    """Cheap answer for the router's tier 3 (V5): could autoload give us a
    vision server right now? Enabled, a recorded choice exists, and the
    shared slot is empty. No disk scan here - the load itself checks the
    file and the projector, and its failure reaches the caller loudly."""
    if not _VISION_AUTOLOAD_ENABLED:
        return False
    hints = _autoload_hints()
    if not hints:
        return False
    paths = [h for h in hints if any(s in h for s in ("/", "\\"))]
    if paths and len(paths) == len(hints) and not any(os.path.exists(p) for p in paths):
        return False
    return not _shared_slot_is_resident()


def _shared_slot_is_resident() -> bool:
    """True when the shared local-model slot holds ANY model — ours or an
    externally started server's. Evicting a resident model is the disruption
    P3 forbids, so both evidence sources block autoload. Never raises."""
    try:
        from backend.agent.local_model_manager import get_local_model_manager

        mgr = get_local_model_manager()
        if mgr.is_loaded():
            return True
        endpoint = mgr.ENDPOINT
    except Exception:  # noqa: BLE001 — cannot prove residency: stay safe
        return True
    try:
        import httpx

        r = httpx.get(f"{endpoint}/models", timeout=1.0)
        if r.status_code == 200:
            data = r.json() if isinstance(r.json(), dict) else {}
            return bool(data.get("data"))
        # A non-200 means no healthy server is up: slot is empty.
        return False
    except Exception:  # noqa: BLE001 — unreachable server: slot is empty
        return False


def _maybe_autoprovision_vision_server() -> bool:
    """Load the projector-backed vision model onto the shared server — ONLY
    when the slot is empty. Returns True when a load succeeded and discovery
    should be retried. Never raises; every failure degrades to the loud
    vision-unavailable path the caller already has.

    Boundaries: single-flight (a second caller returns False immediately —
    its own next call borrows the now-warm server), bounded by
    IRIS_VISION_AUTOLOAD_TIMEOUT_S, and never run on a live event-loop
    thread (a sync-in-async call cannot block for minutes; the threaded
    callers — fetch_vision / search_discovery via asyncio.to_thread — are
    the intended hosts).
    """
    if not _VISION_AUTOLOAD_ENABLED:
        return False
    if not _autoload_lock.acquire(blocking=False):
        logger.info("[LFMVLProvider] autoload already in flight — skip")
        return False
    try:
        try:
            import asyncio

            asyncio.get_running_loop()
            logger.info(
                "[LFMVLProvider] autoload skipped: called on a live event-loop "
                "thread (must not block the loop for a model load)"
            )
            return False
        except RuntimeError:
            pass  # no running loop on this thread — safe to block here
        except Exception:  # noqa: BLE001 — fail safe, never autoload blind
            return False

        if _shared_slot_is_resident():
            logger.info(
                "[LFMVLProvider] autoload skipped: a model is already resident "
                "on the shared slot (eviction is never automatic)"
            )
            return False
        model_paths = _find_autoload_vision_models()
        if not model_paths:
            logger.info(
                "[LFMVLProvider] autoload: no projector-backed model on disk; "
                "vision stays unavailable (load one via the model browser)"
            )
            return False

        import asyncio

        from backend.agent.local_model_manager import get_local_model_manager

        async def _load(path: str):
            return await asyncio.wait_for(
                get_local_model_manager().load_model(
                    path, with_projector=True,
                ),
                timeout=_VISION_AUTOLOAD_TIMEOUT_S,
            )

        # Down the ladder: the next choice loads only when the one before it
        # failed (VRAM pre-flight, a broken file, the bound).
        for model_path in model_paths:
            logger.info(
                "[LFMVLProvider] autoload: empty shared slot — loading %s "
                "(with_projector, bounded %.0fs)",
                model_path, _VISION_AUTOLOAD_TIMEOUT_S,
            )
            try:
                ok = bool(asyncio.run(_load(model_path)))
            except Exception as exc:  # noqa: BLE001 — bounded carry, loud degrade
                logger.warning("[LFMVLProvider] autoload failed for %s: %s", model_path, exc)
                continue
            if not ok:
                logger.warning("[LFMVLProvider] autoload: load reported failure for %s", model_path)
                continue
            # The capability cache may hold a stale NEGATIVE probe for this
            # endpoint from the pre-load world — drop it so discovery re-proves
            # the fresh server instead of reusing "not multimodal: measured".
            _VISION_CAPABILITY_CACHE.clear()
            logger.info("[LFMVLProvider] autoload complete: %s", model_path)
            return True
        return False
    finally:
        _autoload_lock.release()


# ── Vision lifecycle broadcast (REQ-5) ──────────────────────────────────────
# cold -> spawning -> warm | error. Emitted off every inference path via a
# registered callback. Duplicate
# transitions inside the debounce window are dropped so a flapping state
# cannot spam the WS channel.
_lifecycle_callback = None
_lifecycle_lock = threading.Lock()
_last_lifecycle: tuple = ("", 0.0)  # (state, monotonic)
_LIFECYCLE_DEBOUNCE_S = 1.0


def set_vision_lifecycle_callback(cb) -> None:
    """Register the callback invoked on vision lifecycle transitions."""
    global _lifecycle_callback
    _lifecycle_callback = cb


def _notify_lifecycle(state: str, reason: str = "", trigger: str = "") -> None:
    """Best-effort lifecycle emit — never raises, never blocks inference."""
    global _last_lifecycle
    now = time.monotonic()
    with _lifecycle_lock:
        last_state, last_t = _last_lifecycle
        if state == last_state and (now - last_t) < _LIFECYCLE_DEBOUNCE_S:
            return
        _last_lifecycle = (state, now)
    cb = _lifecycle_callback
    if cb is None:
        return
    try:
        cb(state=state, reason=reason, trigger=trigger)
    except Exception as exc:  # noqa: BLE001 — broadcast must never fail a call
        logger.debug("[LFMVLProvider] lifecycle notify failed: %s", exc)


_lfm_vl_provider_singleton = None


def get_lfm_vl_provider():
    """Module-level singleton used by both the gateway and VisionMCPServer."""
    global _lfm_vl_provider_singleton
    if _lfm_vl_provider_singleton is None:
        _lfm_vl_provider_singleton = LFMVLProvider()
    return _lfm_vl_provider_singleton


@dataclass
class LFMVLConfig:
    """Configuration for LFM2.5-VL vision provider."""
    base_url: str = f"http://127.0.0.1:{_VISION_PORT}/v1"
    temperature: float = 0.1
    min_p: float = 0.15
    repetition_penalty: float = 1.05
    image_max_tokens: int = 128  # 64 for speed, 256 for detail
    timeout: float = 30.0


class VisionModelUnavailable(RuntimeError):
    """Raised when no vision-language model can be found on disk, or none of
    the discovered candidates fit current free VRAM (REQ-3 AC4).

    Carries the facts AC4's error message and AC6's VISION_UNAVAILABLE chat
    system message both need, computed exactly once (``_fail_vision_
    unavailable`` populates both from this object) so the log, the raise and
    the event can never disagree.
    """

    def __init__(
        self,
        message: str,
        *,
        free_gb: float = 0.0,
        smallest_requirement_gb: float = 0.0,
        ladder: Optional[list] = None,
    ) -> None:
        super().__init__(message)
        self.free_gb = free_gb
        self.smallest_requirement_gb = smallest_requirement_gb
        self.ladder = ladder or []


def _fail_vision_unavailable(
    message: str,
    *,
    free_gb: float,
    smallest_requirement_gb: float,
    ladder: list,
) -> None:
    """Log, escalate (REQ-3 AC6) and raise (REQ-3 AC4) — the single exit for
    every "no usable VL model" path, so AC4's error and AC6's chat system
    message always carry the same facts.

    Emitting VISION_UNAVAILABLE is best-effort: the EventBus is optional
    infrastructure (mirrors the existing BUDGET_EXHAUSTED/VALIDATION_FAILED
    emit sites in agent_kernel.py) — a broken bus must never suppress the
    raise, which is the part that actually stops a doomed spawn.
    """
    logger.error("[LFMVLProvider] %s", message)
    try:
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

        get_event_bus().emit(
            IRISStreamEvent.VISION_UNAVAILABLE,
            data={
                "message": message,
                "free_vram_gb": round(free_gb, 2),
                "smallest_requirement_gb": round(smallest_requirement_gb, 2),
                "ladder": ladder,
            },
        )
    except Exception as exc:  # noqa: BLE001 — EventBus is optional, never blocks the raise
        logger.warning("[LFMVLProvider] failed to emit VISION_UNAVAILABLE: %s", exc)
    raise VisionModelUnavailable(
        message,
        free_gb=free_gb,
        smallest_requirement_gb=smallest_requirement_gb,
        ladder=ladder,
    )


def _find_llama_server_binary() -> Optional[str]:
    """
    Find llama-server binary for the vision model.

    Priority: upstream ggml-org/llama.cpp (supports LFM2/LFM2-VL)
             → LocalModelManager discovery (ik_llama.cpp, PATH, etc.)
             → basic PATH search

    We prefer upstream llama.cpp for vision because ik_llama.cpp
    (Kimi-K2 fork) does not support the LFM2 model architecture.
    Brain models on port 8082 continue to use whatever binary
    LocalModelManager resolves (ik_llama.cpp for Kimi-K2).
    """
    # 1. Prefer upstream llama.cpp which supports LFM2/LFM2-VL
    upstream = Path.home() / "llama.cpp-upstream" / "llama-server"
    if upstream.exists():
        return str(upstream)

    # 2. Reuse LocalModelManager discovery
    try:
        from backend.agent.local_model_manager import LocalModelManager
        return LocalModelManager._find_llama_server_binary()
    except Exception:
        pass

    # 3. Fallback: basic PATH search
    import shutil
    found = shutil.which("llama-server")
    if found:
        return found
    return None


def _ensure_vision_server_running(base_url: str = "") -> bool:
    """Ensure a multimodal vision endpoint is reachable — BORROW-ONLY.

    specs/vision-single-server REQ-1: tier 3 NEVER spawns a process. This
    function has exactly three branches:

      1. Fast path: the currently-active endpoint answers /models → True.
      2. Discovery: `_discover_reusable_vision_server()` finds and verifies a
         borrowed multimodal server (config providers, the shared local model
         server when it hosts a projector-backed model, registered endpoints).
         On success it announces lifecycle "warm" and returns True.
      3. Neither: lifecycle "error" is announced and False is returned. The
         caller turns that into a clean VisionModelUnavailable user-facing
         decline — never a spawn, never a silent degrade.
    """
    # ── 1. fast path, no lock: the VERIFIED selection is still up ──
    # Only a server discovery proved multimodal counts. The old fast path
    # pinged the default 8082 and returned True for ANY model there - a
    # text-only tool model read as "vision ready" (V3).
    # base_url ALREADY ENDS IN /v1 (LFMVLConfig.base_url), so the endpoint is
    # "/models" — NOT "/v1/models". Appending /v1 again produced .../v1/v1/models,
    # which 404s forever (live proof 2026-08-10). Keep hitting /models.
    _active = _reused_vision_base_url
    if _active:
        try:
            import httpx
            _auth = _active_vision_auth()
            _headers = {"Authorization": f"Bearer {_auth}"} if _auth else None
            r = httpx.get(f"{_active}/models", headers=_headers, timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        # It went away: forget its verdict too, then re-discover below.
        for _k in [k for k in _VISION_CAPABILITY_CACHE if k[0] == _active]:
            _VISION_CAPABILITY_CACHE.pop(_k, None)
        _reset_reused_vision_server()

    # ── 2. discover a borrowed multimodal server ──
    try:
        _reused = _discover_reusable_vision_server(base_url)
        if _reused is not None:
            _notify_lifecycle("warm", reason="borrowed-server", trigger="ensure")
            return True
    except Exception:
        pass

    # ── 2.5 P3 auto-provision: the ONLY lawful auto-load ──
    # (session-342 owner decision) The slot is EMPTY or nothing qualifies.
    # A load here pays its cost ONCE for a server that then stays warm for
    # every later vision need, and it can never evict a resident model
    # (`_shared_slot_is_resident` gates it). On success, re-run discovery so
    # the borrow probe proves the fresh server multimodal (cache cleared by
    # the load) and routes this call to it.
    if _maybe_autoprovision_vision_server():
        try:
            _reused = _discover_reusable_vision_server(base_url)
            if _reused is not None:
                _notify_lifecycle("warm", reason="autoloaded-shared-model", trigger="ensure")
                return True
        except Exception:
            pass

    # ── 3. nothing to serve vision — fail loudly, never spawn ──
    _notify_lifecycle(
        "error",
        reason="no-shared-multimodal-server-available",
        trigger="ensure",
    )
    logger.warning(
        "[LFMVLProvider] no reusable multimodal server available; vision is "
        "unavailable for this call (spec: vision-single-server)"
    )
    return False


def screenshot_to_bytes(region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """
    Capture screen and return as PNG bytes.
    Uses mss for cross-platform support. Latency: <5ms.

    Args:
        region: Optional (left, top, width, height) bounding box.

    Returns:
        PNG bytes of the screenshot.
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        if region:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[1]  # Primary monitor

        sct_img = sct.grab(monitor)
        return mss.tools.to_png(sct_img.rgb, sct_img.size)


def _img_to_base64(img_bytes: bytes) -> str:
    """Convert PNG bytes to base64 string."""
    return base64.b64encode(img_bytes).decode("utf-8")


class LFMVLProvider:
    """
    Synchronous HTTP client for LFM2.5-VL vision model via llama-server.

    Design principles:
    - No state held between calls
    - Every call is independent (screenshot, query, response)
    - All methods return strings/dicts — never raise on failure
    - Uses httpx for sync HTTP requests

    Sampling (Liquid AI official recommendations):
    - temperature: 0.1   (deterministic outputs)
    - min_p: 0.15        (nucleus sampling threshold)
    - repetition_penalty: 1.05 (prevent repetition)
    """

    def __init__(self, config: Optional[LFMVLConfig] = None):
        self.config = config or LFMVLConfig()

    def _call(self, img_bytes: bytes, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Send image + prompt to the vision endpoint /v1/chat/completions.
        Vision is BORROW-ONLY (specs/vision-single-server): no process is
        ever spawned from here. If no multimodal endpoint is available the
        call fails into the loud Vision-unavailable string below.
        Returns model response text, or error string on any failure.
        """
        _ensure_vision_server_running(self.config.base_url)

        try:
            import httpx

            img_b64 = _img_to_base64(img_bytes)
            tokens = max_tokens or self.config.image_max_tokens

            # Route to the server discovery selected; it is a shared/borrowed
            # server, never one we own or may restart.
            _base = _active_vision_base_url(self.config.base_url)
            _auth = _active_vision_auth()
            _req_headers = {"Authorization": f"Bearer {_auth}"} if _auth else None

            payload = {
                # For the borrowed server the model id MUST be the real one —
                # use the id the capability probe discovered.
                "model": _active_vision_model(),
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": self.config.temperature,
                "min_p": self.config.min_p,
                "repetition_penalty": self.config.repetition_penalty,
                "max_tokens": tokens,
            }

            # A dead borrowed server is surfaced, never respawned
            # (specs/vision-single-server REQ-2 AC3).
            response = httpx.post(
                f"{_base}/chat/completions",
                headers=_req_headers,
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.warning(f"[LFMVLProvider] Call failed: {e}")
            return f"Vision unavailable: {e}"

    def health_check(self) -> bool:
        """
        Check if the active vision endpoint (borrowed server if discovered, else
        the IRIS-owned llama-server) is reachable and has a vision model loaded.
        Returns True if server responds, False otherwise.
        """
        # Only a server discovery PROVED multimodal is healthy for vision: the
        # default 8082 answers /models for a text-only model too (V3).
        _base = _reused_vision_base_url
        if not _base:
            return False
        try:
            import httpx

            _auth = _active_vision_auth()
            _headers = {"Authorization": f"Bearer {_auth}"} if _auth else None
            response = httpx.get(
                f"{_base}/models",
                headers=_headers,
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False

    def start(self) -> bool:
        """Resolve the shared vision server — the explicit 'enable vision' gate.

        specs/vision-single-server: no process is spawned here. "Enabled"
        means: a borrowed/verified multimodal endpoint exists. Returns True if
        one is available after this call, False otherwise.
        """
        return _ensure_vision_server_running(self.config.base_url)

    def disable(self) -> None:
        """Drop the borrowed-server selection. Never touches a process —
        the shared server belongs to its owner (or the model manager), and
        the spawn path is gone (specs/vision-single-server REQ-2 AC2). The
        next vision call simply re-discovers from scratch."""
        _reset_reused_vision_server()

    def analyze_screen(self, img_bytes: bytes, question: str = "") -> str:
        """
        Analyze screen content and answer a question about it.

        Args:
            img_bytes: PNG screenshot bytes
            question: Optional specific question about the screen

        Returns:
            Text description of screen content.
        """
        prompt = question if question else "Describe what is visible on this screen in detail."
        return self._call(img_bytes, prompt, max_tokens=256)

    def find_ui_element(self, img_bytes: bytes, description: str) -> dict:
        """
        Locate a UI element on screen by description.

        Args:
            img_bytes: PNG screenshot bytes
            description: Natural language description of the element

        Returns:
            {"found": bool, "location_hint": str}
        """
        prompt = (
            f'Find the UI element described as: "{description}". '
            "Describe where it is located on screen (top-left, center, bottom-right, etc.) "
            "and whether it is visible. Keep response brief."
        )
        response = self._call(img_bytes, prompt, max_tokens=64)

        if response.startswith("Vision unavailable"):
            return {"found": False, "location_hint": response}

        found = not any(
            word in response.lower()
            for word in ["not found", "not visible", "cannot find", "don't see", "no such"]
        )
        return {"found": found, "location_hint": response}

    def read_text(self, img_bytes: bytes, region: Optional[Tuple] = None) -> str:
        """
        Extract text from screen or a specific region.

        Args:
            img_bytes: PNG screenshot bytes
            region: Optional region description hint

        Returns:
            Extracted text string.
        """
        hint = f" Focus on: {region}." if region else ""
        prompt = f"Extract all readable text from this screenshot.{hint} Return only the text content, no commentary."
        return self._call(img_bytes, prompt, max_tokens=256)

    def suggest_action(self, img_bytes: bytes, goal: str) -> dict:
        """
        Suggest the next UI action to achieve a goal.

        REQ-2 (this spec's T2): the prompt requests a RESOLVABLE target the
        executor can satisfy rather than open-ended prose, and asks for a
        `type` action's input in its OWN field (`VALUE:`) so the text never
        gets embedded in `target`. `_map_action` (fetch_vision) parses the
        four fields into `VisionAction(kind, target, value, reason)`, so
        `type` populates `value` separately. The role+name vocabulary matches
        `backend/vision/action_allowlist.py`, which the executor resolves.

        Args:
            img_bytes: PNG screenshot bytes
            goal: What the user wants to accomplish

        Returns:
            {"action": str, "target": str, "value": str, "reasoning": str}
        """
        prompt = (
            f'Goal: "{goal}". '
            "Looking at the current screen, what is the single best next action? "
            "Reply with exactly these fields, one per line: "
            "ACTION: [click/type/scroll/wait/navigate], "
            "TARGET: [a stable handle the executor can resolve -- a CSS selector "
            "OR a role and accessible name, e.g. 'button \"Sign in\"' or "
            "'#submit'], "
            "VALUE: [for a type action ONLY, the exact text to enter; leave empty "
            "for every other action], "
            "REASON: [brief reason]."
        )
        response = self._call(img_bytes, prompt, max_tokens=160)

        if response.startswith("Vision unavailable"):
            return {"action": "error", "target": "", "value": "", "reasoning": response}

        # Parse structured response
        result = {"action": "unknown", "target": "", "value": "", "reasoning": response}
        for line in response.splitlines():
            line_lower = line.lower()
            if line_lower.startswith("action:"):
                result["action"] = line.split(":", 1)[1].strip().lower()
            elif line_lower.startswith("target:"):
                result["target"] = line.split(":", 1)[1].strip()
            elif line_lower.startswith("value:"):
                result["value"] = line.split(":", 1)[1].strip()
            elif line_lower.startswith("reason:"):
                result["reasoning"] = line.split(":", 1)[1].strip()

        return result

    def describe_live_frame(self, img_bytes: bytes) -> str:
        """
        Fast single-sentence description for streaming/monitoring.
        Uses minimum tokens for speed.

        Args:
            img_bytes: PNG screenshot bytes

        Returns:
            Single sentence describing the screen.
        """
        prompt = "In one sentence, what is happening on this screen right now?"
        return self._call(img_bytes, prompt, max_tokens=64)
