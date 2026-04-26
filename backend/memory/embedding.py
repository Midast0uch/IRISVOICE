"""
Embedding Service for IRIS Memory Foundation.

Primary: sentence-transformers all-MiniLM-L6-v2 (384-dim, ~80MB, CPU-capable)
Fallback: hash-projection embedding — always available, no dependencies.

The fallback uses a bag-of-words hash trick to produce a 384-dim sparse vector.
It is consistent (same text → same vector) and similarity-aware (shared tokens →
closer vectors). Accuracy is lower than the neural model but fully functional —
the episodic store writes and retrieves correctly with either backend.

Install sentence-transformers to upgrade to neural embeddings:
  pip install sentence-transformers

All memory components share this single instance.
Never instantiate SentenceTransformer directly anywhere else.
"""

import hashlib
import logging
import math
from collections import OrderedDict
from threading import Lock
from typing import List, Optional

logger = logging.getLogger(__name__)


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


class EmbeddingService:
    """
    Singleton sentence-transformer embedding service.
    
    Model: all-MiniLM-L6-v2 (384-dim, ~80MB, CPU-capable)
    
    All memory components share this single instance.
    Never instantiate SentenceTransformer directly anywhere else.
    """
    
    _instance: Optional["EmbeddingService"] = None
    _model = None
    _lock = Lock()
    _model_lock = Lock()
    
    # Model configuration
    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384
    
    def __new__(cls) -> "EmbeddingService":
        """Ensure singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    logger.info("[EmbeddingService] Created singleton instance")
        return cls._instance
    
    # Sentinel: True when sentence-transformers is confirmed unavailable so we
    # don't re-attempt the import on every encode() call.
    _neural_unavailable: bool = False

    def __init__(self) -> None:
        """Initialize the embedding service with LRU cache."""
        self._enc_cache: OrderedDict[str, List[float]] = OrderedDict()
        self._enc_cache_max = 256

    def _load(self) -> None:
        """
        Lazily load the neural embedding model.

        Falls back silently to _hash_embed() if sentence-transformers is not
        installed — sets _neural_unavailable so future calls skip the import
        attempt.  The episodic store works correctly with either backend.
        """
        if self._model is not None or self._neural_unavailable:
            return
        with self._model_lock:
            if self._model is not None or self._neural_unavailable:
                return
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(
                    f"[EmbeddingService] Loading {self.MODEL_NAME} model..."
                )
                self._model = SentenceTransformer(self.MODEL_NAME)
                logger.info(
                    f"[EmbeddingService] Model loaded successfully "
                    f"({self.EMBEDDING_DIM} dimensions)"
                )
            except ImportError:
                logger.info(
                    "[EmbeddingService] sentence-transformers not installed — "
                    "using hash-projection fallback. "
                    "Run: pip install sentence-transformers for neural embeddings."
                )
                EmbeddingService._neural_unavailable = True
            except Exception as e:
                logger.warning(
                    f"[EmbeddingService] Failed to load neural model ({e}) — "
                    "using hash-projection fallback."
                )
                EmbeddingService._neural_unavailable = True
    
    def _encode_uncached(self, text: str) -> List[float]:
        """
        Internal implementation of encode without caching.

        Args:
            text: The text to encode (assumed non-empty)

        Returns:
            List of 384 float values representing the embedding
        """
        self._load()

        # Neural path
        if self._model is not None:
            try:
                embedding = self._model.encode(text, convert_to_numpy=True)
                return embedding.tolist()
            except Exception as e:
                logger.warning(f"[EmbeddingService] Neural encode failed ({e}), using fallback")

        # Hash-projection fallback (always available)
        return _hash_embed(text, self.EMBEDDING_DIM)

    def encode(self, text: str) -> List[float]:
        """
        Encode a single text into a 384-dimensional embedding vector.

        Uses an LRU cache (max 256 entries) keyed on SHA1 hash of input text.
        Uses the neural model when available, otherwise falls back to
        hash-projection (_hash_embed).  Never raises — returns zero vector
        on empty input.

        Args:
            text: The text to encode

        Returns:
            List of 384 float values representing the embedding
        """
        # Handle empty text before any model interaction
        if not text or not text.strip():
            return [0.0] * self.EMBEDDING_DIM

        # LRU cache lookup
        key = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()
        cached = self._enc_cache.get(key)
        if cached is not None:
            self._enc_cache.move_to_end(key)
            return cached

        # Encode and cache
        vec = self._encode_uncached(text)
        self._enc_cache[key] = vec
        if len(self._enc_cache) > self._enc_cache_max:
            self._enc_cache.popitem(last=False)
        return vec
    
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Encode multiple texts into embedding vectors.

        Uses LRU cache for hits; batches misses through neural model when available.
        Falls back to per-item hash-projection when unavailable.

        Args:
            texts: List of texts to encode

        Returns:
            List of embedding vectors, one per input text
        """
        if not texts:
            return []

        # Check cache for hits; batch the misses
        results: List[List[float]] = []
        miss_indices: List[int] = []
        miss_texts: List[str] = []

        for i, t in enumerate(texts):
            if not t or not t.strip():
                results.append([0.0] * self.EMBEDDING_DIM)
            else:
                key = hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()
                cached = self._enc_cache.get(key)
                if cached is not None:
                    self._enc_cache.move_to_end(key)
                    results.append(cached)
                else:
                    results.append(None)  # placeholder
                    miss_indices.append(i)
                    miss_texts.append(t)

        # If all cache hits, return early
        if not miss_indices:
            return results

        self._load()

        # Neural batch path for misses
        if self._model is not None:
            try:
                embeddings = self._model.encode(
                    miss_texts,
                    convert_to_numpy=True,
                    batch_size=min(len(miss_texts), 32),
                )
                miss_vecs = [emb.tolist() for emb in embeddings]
                # Fill in misses and cache them
                for idx, (miss_i, vec) in enumerate(zip(miss_indices, miss_vecs)):
                    key = hashlib.sha1(miss_texts[idx].encode("utf-8", "ignore")).hexdigest()
                    self._enc_cache[key] = vec
                    if len(self._enc_cache) > self._enc_cache_max:
                        self._enc_cache.popitem(last=False)
                    results[miss_i] = vec
                return results
            except Exception as e:
                logger.warning(f"[EmbeddingService] Neural batch encode failed ({e}), using fallback")

        # Hash-projection fallback for misses
        miss_vecs = [_hash_embed(t, self.EMBEDDING_DIM) for t in miss_texts]
        for miss_i, vec in zip(miss_indices, miss_vecs):
            key = hashlib.sha1(miss_texts[miss_indices.index(miss_i)].encode("utf-8", "ignore")).hexdigest()
            self._enc_cache[key] = vec
            if len(self._enc_cache) > self._enc_cache_max:
                self._enc_cache.popitem(last=False)
            results[miss_i] = vec
        return results
    
    @classmethod
    def is_available(cls) -> bool:
        """
        Check if sentence-transformers is available without loading the model.
        
        Returns:
            True if sentence-transformers can be imported, False otherwise
        """
        try:
            import sentence_transformers
            return True
        except ImportError:
            return False
    
    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        """
        Get the singleton instance.
        
        This is an alternative to direct instantiation.
        
        Returns:
            The singleton EmbeddingService instance
        """
        return cls()
    
    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (mainly for testing).
        
        WARNING: This should rarely be used in production code.
        """
        with cls._lock:
            cls._instance = None
            cls._model = None
            logger.info("[EmbeddingService] Singleton instance reset")


# Convenience function for quick access
def get_embedding_service() -> EmbeddingService:
    """
    Get the singleton embedding service instance.
    
    This is a convenience function that avoids direct class instantiation.
    
    Returns:
        The singleton EmbeddingService instance
    """
    return EmbeddingService.get_instance()
