"""
Embedding Service for IRIS Memory Foundation.

Singleton sentence-transformer embedding service.
Model: all-MiniLM-L6-v2 (384-dim, ~80MB, CPU-capable)

All memory components share this single instance.
Never instantiate SentenceTransformer directly anywhere else.
"""

import logging
from threading import Lock
from typing import List, Optional

logger = logging.getLogger(__name__)


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
    
    def _load(self) -> None:
        """
        Lazily load the embedding model.
        
        This is called automatically on first encode() call.
        Uses double-checked locking for thread safety.
        """
        if self._model is None:
            with self._model_lock:
                if self._model is None:
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
                    except ImportError as e:
                        logger.error(
                            "[EmbeddingService] sentence-transformers not installed. "
                            "Run: pip install sentence-transformers"
                        )
                        raise ImportError(
                            "sentence-transformers is required for embeddings"
                        ) from e
                    except Exception as e:
                        logger.error(f"[EmbeddingService] Failed to load model: {e}")
                        raise RuntimeError(f"Failed to load embedding model: {e}") from e
    
    def encode(self, text: str) -> List[float]:
        """
        Encode a single text into a 384-dimensional embedding vector.
        
        Args:
            text: The text to encode
        
        Returns:
            List of 384 float values representing the embedding
        
        Example:
            >>> service = EmbeddingService()
            >>> embedding = service.encode("Hello world")
            >>> len(embedding)
            384
        """
        self._load()
        
        # Handle empty text
        if not text or not text.strip():
            logger.warning("[EmbeddingService] Encoding empty text, returning zero vector")
            return [0.0] * self.EMBEDDING_DIM
        
        try:
            # Encode and convert to list
            embedding = self._model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"[EmbeddingService] Failed to encode text: {e}")
            raise RuntimeError(f"Failed to encode text: {e}") from e
    
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Encode multiple texts into embedding vectors.
        
        This is more efficient than calling encode() multiple times
        because it batches the computation.
        
        Args:
            texts: List of texts to encode
        
        Returns:
            List of embedding vectors, one per input text
        
        Example:
            >>> service = EmbeddingService()
            >>> embeddings = service.encode_batch(["Hello", "World"])
            >>> len(embeddings)
            2
            >>> len(embeddings[0])
            384
        """
        self._load()
        
        # Handle empty list
        if not texts:
            return []
        
        # Replace empty strings with placeholder to avoid errors
        # Track which indices were empty
        processed_texts = []
        empty_indices = set()
        
        for i, text in enumerate(texts):
            if not text or not text.strip():
                processed_texts.append("[empty]")  # Placeholder
                empty_indices.add(i)
                logger.warning(f"[EmbeddingService] Batch item {i} is empty")
            else:
                processed_texts.append(text)
        
        try:
            # Encode batch
            embeddings = self._model.encode(
                processed_texts,
                convert_to_numpy=True,
                batch_size=min(len(processed_texts), 32)  # Optimal batch size
            )
            
            # Convert to list of lists
            result = [emb.tolist() for emb in embeddings]
            
            # Zero out embeddings for empty texts
            for i in empty_indices:
                result[i] = [0.0] * self.EMBEDDING_DIM
            
            return result
            
        except Exception as e:
            logger.error(f"[EmbeddingService] Failed to encode batch: {e}")
            raise RuntimeError(f"Failed to encode batch: {e}") from e
    
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
