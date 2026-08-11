"""
Embedding Service for IRIS Memory Foundation.

Phase 4 (LFM2.5 Encoder Integration) — backend-swappable, chunking, provenance.

Backends (provenance values stored with every persisted vector):
  - "qwen3"           Qwen/Qwen3-Embedding-0.6B via sentence-transformers
                       (1024-dim, ~639MB, 32K context). Default (2026-08).
  - "bge-m3"          BAAI/bge-m3 via sentence-transformers (1024-dim, ~2.3GB).
                       Selectable at any time; kept as the pre-switch default.
  - "lfm25-emb-350m"  LFM2.5-Embedding-350M via llama_cpp GGUF on CPU (1024-dim).
  - "hash"            Dependency-free hash-projection fallback. Always available.

The swap is INTERNAL: ``get_embedding_service()`` and the ``EmbeddingService``
method signatures (``encode``, ``encode_batch``) are unchanged (CT-E1). Call
sites that need provenance use ``encode_with_meta()`` which returns an
``Embedding`` carrying the backend that produced it (REQ-1 AC5).

Chunking (REQ-2): text longer than the active backend's token window is split
into overlapping chunks, each embedded, then combined by element-wise MAX-POOL
and L2-normalised AFTER pooling. Text that fits is embedded whole — the
single-chunk path is byte-identical to the unchunked result (REQ-2 AC5).

Cross-space refusal (REQ-3 AC2, CT-E6): ``compare_embeddings`` is the ONLY place
two vectors are compared. If their provenance differs it RAISES rather than
returning a (plausible, wrong) number. Both neural backends are 1024-dim, so a
cross-space comparison would otherwise look fine and silently degrade recall.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock, Thread
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Provenance backend identifiers ────────────────────────────────────────────
BACKEND_BGE = "bge-m3"
BACKEND_LFM = "lfm25-emb-350m"
BACKEND_HASH = "hash"
BACKEND_QWEN = "qwen3"
BACKEND_NEURAL = (BACKEND_BGE, BACKEND_LFM, BACKEND_QWEN)

# Chunking defaults (OQ-1: start 480 / 64; tune against REQ-8 AC1).
DEFAULT_CHUNK_TOKENS = 480
DEFAULT_OVERLAP_TOKENS = 64
# AC3: hard bound on chunks per document. Beyond this the tail is dropped WITH a
# log line — silent tail loss is the failure a user finds a year later.
MAX_CHUNKS_PER_DOC = 32

# ── Bounded backend loading (Defect 1) ────────────────────────────────────────
# The neural backends import heavy native libraries (sentence-transformers ->
# torch/torchvision/torchaudio/torchcodec, or llama_cpp). On a machine where a
# native dependency can't fully resolve (e.g. torchcodec probing an
# incompatible local FFmpeg build), the import can block the calling thread
# for tens of minutes with no exception raised and no way to interrupt it from
# pure Python. Any such load MUST therefore be (a) off the construction path
# and (b) bounded by a timeout, never awaited unboundedly.
DEFAULT_LOAD_TIMEOUT_S = 300.0


def _load_timeout_s() -> float:
    """Bound for a backend load attempt (default 300s for neural backends;
    60s was too tight for Qwen3-Embedding-0.6B which cold-loads in ~106s).
    Overridable via IRIS_EMBEDDING_LOAD_TIMEOUT_S."""
    raw = os.environ.get("IRIS_EMBEDDING_LOAD_TIMEOUT_S")
    if not raw:
        return DEFAULT_LOAD_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "[EmbeddingService] invalid IRIS_EMBEDDING_LOAD_TIMEOUT_S=%r; "
            "using default %.0fs", raw, DEFAULT_LOAD_TIMEOUT_S,
        )
        return DEFAULT_LOAD_TIMEOUT_S


def _run_bounded(fn, timeout_s: float, label: str):
    """Run ``fn()`` on a daemon thread, bounded by ``timeout_s``.

    A stuck native import can block its thread forever with no way to
    interrupt it from Python. Using a DAEMON thread (rather than e.g. a bare
    ``ThreadPoolExecutor``, whose worker threads are joined at interpreter
    shutdown) means the process can still exit even if the load never
    returns — we simply stop waiting after ``timeout_s`` and abandon the
    thread rather than joining it.

    Returns ``(result, timed_out)``. ``result`` is ``None`` on timeout or if
    ``fn`` raised — exceptions are swallowed here because every current
    caller (``_load_bge``, ``_load_gguf``, the ``is_available`` probe)
    already treats "could not load" and "raised while loading" identically.
    """
    box: dict = {}

    def _target():
        try:
            box["value"] = fn()
        except Exception as exc:  # ImportError or any load-time failure
            box["error"] = exc

    t = Thread(target=_target, name=f"embedding-load-{label}", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None, True
    return box.get("value"), False


class CrossSpaceComparisonError(ValueError):
    """Raised when two vectors of differing provenance are compared (REQ-3 AC2).

    Both neural backends are 1024-dim, so a cross-space comparison returns a
    plausible number and quietly degrades recall. Refusing at the single
    comparison point is the only mechanism that catches it; review will not.
    """


@dataclass(frozen=True)
class Embedding:
    """A persisted embedding with its provenance (REQ-1 AC5, design data model)."""

    vector: List[float]
    backend: str          # BACKEND_* — STORED, never inferred
    chunk_count: int      # 1 = unchunked (REQ-2 AC5)
    truncated: bool       # AC3 bound dropped a tail


def _hash_embed(text: str, dim: int = 384) -> List[float]:
    """
    Lightweight hash-projection embedding — no external dependencies.

    Maps each whitespace-split token to a bucket in [0, dim) via SHA-256 and
    accumulates a count vector.  The result is L2-normalised to unit length so
    cosine similarity comparisons work correctly.

    Properties:
    - Deterministic (same text → same vector every time)
    - Collision-robust (two different words land in the same bucket ~1/dim of
      the time — negligible for short phrases)
    - Bag-of-words: word order is ignored; bigrams are added to partially
      preserve local context
    """
    vec = [0.0] * dim
    tokens = text.lower().split()
    if not tokens:
        return vec

    # Unigrams
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0

    # Bigrams — add partial positional context
    for a, b in zip(tokens, tokens[1:]):
        bigram = f"{a}_{b}"
        h = int(hashlib.sha256(bigram.encode()).hexdigest(), 16) % dim
        vec[h] += 0.5

    # L2 normalise
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        vec = [x / norm for x in vec]
    return vec


# ── Chunking + pooling (REQ-2) ────────────────────────────────────────────────

def _word_tokenize(text: str) -> List[str]:
    """Default tokeniser: whitespace split. A word ≈ one token for English; the
    chunker is tokeniser-agnostic and accepts an injected one for tests."""
    return text.split()


def max_pool(vectors: List[List[float]]) -> List[float]:
    """Element-wise MAX across a list of equal-length vectors (REQ-2, D-2).

    Max-pool (not mean-pool): a document matching strongly in one section should
    score on that section, not have it averaged away. Constructed so mean-pool
    fails the distinguishing case (see test_pooling_is_max_not_mean).
    """
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            if v[i] > out[i]:
                out[i] = v[i]
    return out


def l2_normalize(vec: List[float]) -> List[float]:
    """L2-normalise a vector IN-PLACE-safe (returns a new list)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        return [x / norm for x in vec]
    return list(vec)


class Chunker:
    """Splits text into token-bounded overlapping chunks (REQ-2).

    ``window`` is the backend's max-token context. Text within the window is
    returned as a single chunk (whole-text embed → byte-identical to today,
    REQ-2 AC5). Text beyond the window is split into ``chunk_tokens`` windows
    with ``overlap_tokens`` overlap. If the resulting chunk count exceeds
    ``max_chunks``, the tail is dropped and ``truncated=True`` is reported.
    """

    def __init__(
        self,
        window: int = 512,
        chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        max_chunks: int = MAX_CHUNKS_PER_DOC,
        tokenize=_word_tokenize,
    ) -> None:
        self.window = window
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.max_chunks = max_chunks
        self.tokenize = tokenize

    def chunk(self, text: str) -> tuple[List[str], bool]:
        """Return (chunks, truncated). Single chunk when text fits the window."""
        if not text or not text.strip():
            return [text or ""], False
        tokens = self.tokenize(text)
        if len(tokens) <= self.window:
            return [text], False
        chunks: List[str] = []
        start = 0
        n = len(tokens)
        while start < n:
            end = min(start + self.chunk_tokens, n)
            chunks.append(" ".join(tokens[start:end]))
            if end >= n:
                break
            start += self.chunk_tokens - self.overlap_tokens
        truncated = False
        if len(chunks) > self.max_chunks:
            logger.warning(
                "[Chunker] document produced %d chunks (> max %d); "
                "dropping tail beyond %d chunks",
                len(chunks), self.max_chunks, self.max_chunks,
            )
            chunks = chunks[: self.max_chunks]
            truncated = True
        return chunks, truncated


def compare_embeddings(
    a: List[float],
    backend_a: str,
    b: List[float],
    backend_b: str,
) -> float:
    """The SINGLE point where two vectors are compared (REQ-3 AC2, CT-E6).

    Refuses a cross-space comparison: if the two vectors were produced by
    different backends, raise rather than return a number. A dimension change
    would have crashed safely; sharing a dimension makes the bug silent.
    """
    if backend_a and backend_b and backend_a != backend_b:
        raise CrossSpaceComparisonError(
            f"refused similarity between vectors of provenance "
            f"{backend_a!r} and {backend_b!r}"
        )
    return _cosine(a, b)


def _cosine(a: List[float], b: List[float]) -> float:
    """Plain cosine similarity. Callers that care about provenance use
    ``compare_embeddings`` instead."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingService:
    """
    Singleton, backend-swappable embedding service (Phase 4).

    Model: Qwen/Qwen3-Embedding-0.6B (default, 2026-08), BAAI/bge-m3, or
    LFM2.5-Embedding-350M (GGUF, CPU). Falls back to the hash-projection
    embedder if no neural backend is available. All memory components share
    this single instance.
    """

    _instance: Optional["EmbeddingService"] = None
    _model = None
    _lock = Lock()
    _model_lock = Lock()

    # Model configuration
    MODEL_NAME = "BAAI/bge-m3"
    MODEL_NAME_QWEN = "Qwen/Qwen3-Embedding-0.6B"
    EMBEDDING_DIM = 1024

    # Sentinel: True when sentence-transformers is confirmed unavailable.
    _neural_unavailable: bool = False

    # Cache for is_available() — an import probe bounded by the same Defect 1
    # timeout as backend loading; cached so a broken install only pays it once.
    _is_available_cache: Optional[bool] = None

    def __new__(cls) -> "EmbeddingService":
        """Ensure singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    logger.info("[EmbeddingService] Created singleton instance")
        return cls._instance

    def __init__(self) -> None:
        """Initialize the embedding service with LRU cache + backend selection."""
        if getattr(self, "_initialised", False):
            return
        self._initialised = True
        self._enc_cache: "OrderedDict[str, Embedding]" = OrderedDict()
        self._enc_cache_max = 256

        # Per-backend loaded models. "hash" is always available (no model object).
        self._models: dict = {BACKEND_HASH: "hash"}
        self._gguf_path: Optional[str] = None
        self._backend_loaded = False
        # Backends whose load has already been attempted (success, failure, or
        # timeout) — a load is attempted AT MOST ONCE per backend per instance
        # so a broken/slow backend cannot stall every subsequent call.
        self._load_attempted: set = set()

        self._selected = self._resolve_selected_backend()
        self._backend = BACKEND_HASH
        # Defect 1: do NOT load anything here. Construction must be cheap and
        # synchronous even if the selected backend's native import is broken
        # on this machine — loading happens lazily on first actual
        # encode/embed use, via ``_load_active_backend`` (bounded, latched).

    # ── Backend selection (REQ-1 AC4) ────────────────────────────────────────
    def _resolve_selected_backend(self) -> str:
        """Select backend from config; default QWEN3 (2026-08 switch)."""
        try:
            from backend.memory.config import get_config
            cfg = get_config()
            vec = getattr(cfg, "embedding", None)
            b = getattr(vec, "backend", None) if vec else None
            if b in (BACKEND_BGE, BACKEND_LFM, BACKEND_HASH, BACKEND_QWEN):
                return b
        except Exception as exc:  # pragma: no cover - config optional at import
            logger.debug("[EmbeddingService] backend config read failed: %s", exc)
        return BACKEND_QWEN

    @staticmethod
    def _window_for(backend: str) -> int:
        if backend == BACKEND_LFM:
            return 512
        if backend == BACKEND_BGE:
            return 8192
        if backend == BACKEND_QWEN:
            return 32768
        return 10 ** 9  # hash: effectively unbounded

    def _chunker_for(self, backend: str) -> Chunker:
        return Chunker(window=self._window_for(backend))

    def _load_active_backend(self) -> None:
        """Resolve + load the selected backend. LAZY: called on first actual
        encode/embed use (see ``_encode_uncached`` / ``encode`` /
        ``encode_with_meta``), never from ``__init__`` (Defect 1). Latched by
        ``_backend_loaded`` — idempotent, thread-safe via ``_model_lock``."""
        if self._backend_loaded:
            return
        with self._model_lock:
            if self._backend_loaded:
                return
            self._backend_loaded = True
            if self._ensure_backend(self._selected):
                self._backend = self._selected
                logger.info("[EmbeddingService] active backend = %s", self._backend)
            else:
                self._backend = BACKEND_HASH
                logger.warning(
                    "[EmbeddingService] selected backend %r unavailable; "
                    "active backend = hash (dependency-free fallback)",
                    self._selected,
                )

    def _ensure_backend(self, backend: str) -> bool:
        """Ensure ``backend`` is loaded. Returns True if usable (model or hash).

        A load is attempted AT MOST ONCE per backend per instance — a failed
        OR timed-out load is latched in ``_load_attempted`` so a broken
        backend does not re-attempt (and re-stall) on every call (Defect 1).
        The attempt itself is bounded by ``_load_timeout_s()`` via
        ``_run_bounded`` so a stuck native import cannot block the caller.
        """
        if backend in self._models and self._models[backend] is not None:
            return True
        if backend == BACKEND_HASH:
            self._models[BACKEND_HASH] = "hash"
            return True
        if backend not in BACKEND_NEURAL:
            return False
        if backend in self._load_attempted:
            return False
        self._load_attempted.add(backend)
        timeout_s = _load_timeout_s()
        load_fn = {
            BACKEND_BGE: self._load_bge,
            BACKEND_QWEN: self._load_qwen,
            BACKEND_LFM: self._load_gguf,
        }[backend]
        model, timed_out = _run_bounded(load_fn, timeout_s, backend)
        if timed_out:
            logger.warning(
                "[EmbeddingService] loading backend %r did not complete "
                "within %.0fs (IRIS_EMBEDDING_LOAD_TIMEOUT_S); falling back "
                "to hash",
                backend, timeout_s,
            )
            model = None
        self._models[backend] = model
        return model is not None

    def _load_bge(self):
        """Load BGE-M3 ONLY from the local HF cache (2026-08-09: the cache was
        removed; bge-m3 is no longer the default backend, so this backend now
        resolves to None unless the weights are re-downloaded intentionally).
        Guarded against silent network re-download: a model that is not already
        cached locally is reported unavailable rather than fetched."""
        import os
        if not self._hf_cached(self.MODEL_NAME):
            logger.info(
                "[EmbeddingService] %s not in local HF cache; "
                "BGE-M3 backend unavailable (no download attempted)",
                self.MODEL_NAME,
            )
            return None
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("[EmbeddingService] Loading %s model...", self.MODEL_NAME)
            return SentenceTransformer(self.MODEL_NAME, device="cpu")
        except Exception as exc:  # ImportError or load failure
            logger.info("[EmbeddingService] BGE-M3 not available: %s", exc)
            return None

    def _load_qwen(self):
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("[EmbeddingService] Loading %s model (CPU)...", self.MODEL_NAME_QWEN)
            # Pinned to CPU (2026-08-09): the embedding models run on system
            # RAM, keeping the GPU free for audio/STT workloads.
            return SentenceTransformer(self.MODEL_NAME_QWEN, device="cpu")
        except Exception as exc:  # ImportError or load failure
            logger.info("[EmbeddingService] Qwen3 not available: %s", exc)
            return None

    @staticmethod
    def _hf_cached(model_name: str) -> bool:
        """True if ``model_name`` has a populated snapshot in the HF hub cache."""
        import os
        hf_home = os.environ.get("HF_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface"
        )
        hub_dir = os.path.join(hf_home, "hub", "models--" + model_name.replace("/", "--"))
        snap = os.path.join(hub_dir, "snapshots")
        if not os.path.isdir(snap) or not os.listdir(snap):
            return False
        return any(
            os.path.isdir(os.path.join(snap, s))
            for s in os.listdir(snap)
        )

    def _load_gguf(self):
        path = self._resolve_gguf_path()
        if not path:
            return None
        try:
            from llama_cpp import Llama
            model = Llama(
                model_path=path,
                embedding=True,
                n_ctx=512,
                n_gpu_layers=0,          # CPU only (REQ-1 AC6 / Phase 3)
                verbose=False,
            )
            # Validate dimension before committing to this backend.
            probe = model.embed("dimension probe")
            if len(probe) != self.EMBEDDING_DIM:
                logger.warning(
                    "[EmbeddingService] GGUF embedding dim %d != %d; rejecting",
                    len(probe), self.EMBEDDING_DIM,
                )
                return None
            self._gguf_path = path
            return model
        except Exception as exc:
            logger.warning("[EmbeddingService] LFM2.5 GGUF load failed: %s", exc)
            return None

    def _resolve_gguf_path(self) -> Optional[str]:
        """Resolve the Embedding-350M GGUF from config or the user's folder
        BEFORE any network fetch (REQ-7 AC1/AC2). Returns None if absent and
        logs what is expected (never silently downloads)."""
        # 1. Explicit config path.
        try:
            from backend.memory.config import get_config
            cfg = get_config()
            vec = getattr(cfg, "embedding", None)
            explicit = getattr(vec, "model_path", None) if vec else None
            if explicit and os.path.isfile(explicit):
                return explicit
        except Exception:
            pass
        # 2. Scan the user's local model folder (symlink-aware via rglob).
        candidates = self._discover_gguf()
        if candidates:
            return candidates[0]
        logger.warning(
            "[EmbeddingService] LFM2.5-Embedding-350M GGUF not found in "
            "config.embedding.model_path or the local model folder. "
            "Expected a file matching '*embedding*350m*.gguf'. "
            "No network download will be attempted."
        )
        return None

    @staticmethod
    def _discover_gguf() -> List[str]:
        """Find a plausible Embedding-350M GGUF under common local model roots."""
        roots = [
            os.environ.get("IRIS_MODEL_DIR", ""),
            os.path.expanduser("~/.lmstudio/models"),
            os.path.expanduser("~/Library/Application Support/LM Studio/models"),
            "C:/Users/midas/.lmstudio/models",
        ]
        found: List[str] = []
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            try:
                for p in os.listdir(root):
                    low = p.lower()
                    if "embedding" in low and "350m" in low and low.endswith(".gguf"):
                        found.append(os.path.join(root, p))
            except Exception:
                continue
        return found

    # ── Public API (signatures unchanged — CT-E1) ────────────────────────────
    @property
    def backend(self) -> str:
        """Provenance of vectors this service currently produces (REQ-1 AC5)."""
        return self._backend

    def available_backends(self) -> List[str]:
        """Backends that are currently usable (loaded model or hash fallback)."""
        return [b for b, m in self._models.items() if m is not None]

    def _encode_chunk_with(self, text: str, backend: str) -> List[float]:
        """Embed a single chunk with the given backend, else hash fallback."""
        model = self._models.get(backend)
        if backend in (BACKEND_BGE, BACKEND_QWEN) and model is not None:
            emb = model.encode(text, convert_to_numpy=True)
            return emb.tolist()
        if backend == BACKEND_LFM and model is not None:
            return list(model.embed(text))
        return _hash_embed(text, self.EMBEDDING_DIM)

    def _encode_uncached_with(self, text: str, backend: str) -> Embedding:
        """Embed text with chunking + max-pool + post-pool L2 (REQ-2)."""
        chunker = self._chunker_for(backend)
        chunks, truncated = chunker.chunk(text)
        if len(chunks) == 1:
            vec = self._encode_chunk_with(chunks[0], backend)
            return Embedding(
                vector=vec, backend=backend, chunk_count=1, truncated=False
            )
        vecs = [self._encode_chunk_with(c, backend) for c in chunks]
        pooled = l2_normalize(max_pool(vecs))
        return Embedding(
            vector=pooled,
            backend=backend,
            chunk_count=len(vecs),
            truncated=truncated,
        )

    def _encode_uncached(self, text: str) -> Embedding:
        self._load_active_backend()
        return self._encode_uncached_with(text, self._backend)

    def encode(self, text: str) -> List[float]:
        """Encode a single text into an embedding_dim-dimensional vector.

        Unchanged signature. Returns the vector only; use ``encode_with_meta``
        for provenance. Never raises — empty input → zero vector.

        Backend loading is lazy (Defect 1): the FIRST call to this method (or
        ``encode_with_meta``) on a fresh instance triggers ``_load_active_backend``,
        bounded by IRIS_EMBEDDING_LOAD_TIMEOUT_S. Construction itself never loads.
        """
        if not text or not text.strip():
            return [0.0] * self.EMBEDDING_DIM
        key = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
        cached = self._enc_cache.get(key)
        if cached is not None:
            self._enc_cache.move_to_end(key)
            return cached.vector
        emb = self._encode_uncached(text)
        self._enc_cache[key] = emb
        if len(self._enc_cache) > self._enc_cache_max:
            self._enc_cache.popitem(last=False)
        return emb.vector

    def encode_with_meta(self, text: str) -> Embedding:
        """Encode and return the full ``Embedding`` (vector + provenance)."""
        if not text or not text.strip():
            self._load_active_backend()
            return Embedding(
                vector=[0.0] * self.EMBEDDING_DIM,
                backend=self._backend,
                chunk_count=1,
                truncated=False,
            )
        key = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
        cached = self._enc_cache.get(key)
        if cached is not None:
            self._enc_cache.move_to_end(key)
            return cached
        emb = self._encode_uncached(text)
        self._enc_cache[key] = emb
        if len(self._enc_cache) > self._enc_cache_max:
            self._enc_cache.popitem(last=False)
        return emb

    def encode_with_backend(self, text: str, backend: str) -> Optional[List[float]]:
        """Embed ``text`` with a SPECIFIC backend (dual-read during migration,
        REQ-3 AC3). Returns None if that backend cannot be loaded — the caller
        skips that space rather than comparing across spaces."""
        if not self._ensure_backend(backend):
            logger.warning(
                "[EmbeddingService] cannot encode with backend %r; skipping space",
                backend,
            )
            return None
        emb = self._encode_uncached_with(text, backend)
        return emb.vector

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Encode multiple texts. Returns one vector per input (unchanged sig)."""
        if not texts:
            return []
        out: List[List[float]] = []
        for t in texts:
            out.append(self.encode(t))
        return out

    @classmethod
    def is_available(cls) -> bool:
        """True if sentence-transformers can be imported (legacy helper).

        Shares the Defect 1 hazard: importing sentence-transformers can block
        the calling thread indefinitely on a machine with a broken native
        dependency (e.g. torchcodec vs. local FFmpeg). Bounded the same way
        as backend loading — an import that doesn't resolve within
        IRIS_EMBEDDING_LOAD_TIMEOUT_S is reported unavailable rather than
        blocking the caller. Cached at the class level so a broken install
        only pays the timeout once per process.
        """
        if cls._is_available_cache is not None:
            return cls._is_available_cache

        def _try_import() -> bool:
            try:
                import sentence_transformers  # noqa: F401
                return True
            except ImportError:
                return False

        timeout_s = _load_timeout_s()
        result, timed_out = _run_bounded(_try_import, timeout_s, "is_available")
        if timed_out:
            logger.warning(
                "[EmbeddingService] is_available() import probe did not "
                "complete within %.0fs; reporting unavailable", timeout_s,
            )
            result = False
        cls._is_available_cache = bool(result)
        return cls._is_available_cache

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None
            cls._model = None
            cls._neural_unavailable = False


# Convenience function for quick access (CT-E1 — sole accessor, unchanged).
def get_embedding_service() -> EmbeddingService:
    """Get the singleton embedding service instance."""
    return EmbeddingService.get_instance()
