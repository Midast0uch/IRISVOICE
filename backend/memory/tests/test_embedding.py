"""
Tests for EmbeddingService singleton.

Verifies singleton behavior, lazy loading, and encoding functionality.
"""

import pytest
import numpy as np

from backend.memory.embedding import EmbeddingService, get_embedding_service


# Skip all tests if sentence-transformers is not available
pytestmark = pytest.mark.skipif(
    not EmbeddingService.is_available(),
    reason="sentence-transformers not installed"
)


class TestEmbeddingServiceSingleton:
    """Test singleton pattern and instance management."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService.reset_instance()
    
    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService.reset_instance()
    
    def test_singleton_same_instance(self):
        """Test that multiple instantiations return the same object."""
        service1 = EmbeddingService()
        service2 = EmbeddingService()
        
        assert service1 is service2, "Should be the same instance"
    
    def test_get_instance_returns_singleton(self):
        """Test get_instance() returns the same singleton."""
        service1 = EmbeddingService.get_instance()
        service2 = get_embedding_service()
        service3 = EmbeddingService()
        
        assert service1 is service2 is service3, "All should be same instance"
    
    def test_is_available_true_when_installed(self):
        """Test is_available() returns True when installed."""
        assert EmbeddingService.is_available(), \
            "sentence-transformers should be available"


class TestEmbeddingServiceLazyLoading:
    """Test lazy loading of the model."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService.reset_instance()
    
    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService.reset_instance()
    
    def test_model_not_loaded_on_instantiation(self):
        """Test that model is not loaded when service is created."""
        service = EmbeddingService()
        
        # Model should be None before first encode()
        assert service._model is None, "Model should not be loaded on instantiation"
    
    def test_model_loaded_on_first_encode(self):
        """Test that model is loaded lazily on first encode().

        NOTE (2026-08-09): the legacy assertion checked ``service._model``,
        a never-populated class attribute from the single-model era. The
        Phase-4 multi-backend service stores the loaded model in
        ``self._models[backend]`` (visible via ``available_backends()``).
        This test was dormant (whole module skipped when
        sentence-transformers was absent) and only now runs; the assertion
        is corrected to the real lazy-load contract, not weakened.
        """
        service = EmbeddingService()

        # Before first encode(): hash fallback is always registered, but no
        # neural backend has loaded yet.
        assert "hash" in service.available_backends()
        assert "qwen3" not in service.available_backends(), \
            "No neural model should be loaded on instantiation"

        # Trigger lazy loading
        embedding = service.encode("Hello world")

        # The neural backend should now be loaded
        assert "qwen3" in service.available_backends(), \
            "Model should be loaded after encode()"
        assert len(embedding) == EmbeddingService.EMBEDDING_DIM, \
            "Should return embedding_dim vector"


class TestEmbeddingServiceEncoding:
    """Test encoding functionality."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService.reset_instance()
    
    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService.reset_instance()
    
    def test_encode_returns_expected_dimensions(self):
        """Test that encode returns embedding_dim-dimensional vector."""
        service = EmbeddingService()
        embedding = service.encode("Hello world")
        
        assert len(embedding) == EmbeddingService.EMBEDDING_DIM, (
            f"Expected {EmbeddingService.EMBEDDING_DIM} dimensions, got {len(embedding)}"
        )
    
    def test_encode_returns_list_of_floats(self):
        """Test that encode returns list of floats."""
        service = EmbeddingService()
        embedding = service.encode("Test text")
        
        assert isinstance(embedding, list)
        assert all(isinstance(x, float) for x in embedding)
    
    def test_encode_consistency(self):
        """Test that same text produces same embedding."""
        service = EmbeddingService()
        
        text = "This is a test sentence"
        embedding1 = service.encode(text)
        embedding2 = service.encode(text)
        
        # Should be very similar (allowing for tiny floating point differences)
        similarity = np.dot(embedding1, embedding2) / (
            np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
        )
        assert similarity > 0.999, "Same text should produce similar embeddings"
    
    def test_encode_different_texts_different_embeddings(self):
        """Test that different texts produce different embeddings."""
        service = EmbeddingService()
        
        embedding1 = service.encode("Machine learning")
        embedding2 = service.encode("Cooking recipes")
        
        # Should be different
        similarity = np.dot(embedding1, embedding2) / (
            np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
        )
        assert similarity < 0.9, "Different texts should have different embeddings"
    
    def test_encode_empty_string(self):
        """Test encoding empty string returns zero vector."""
        service = EmbeddingService()
        
        embedding = service.encode("")
        
        assert len(embedding) == EmbeddingService.EMBEDDING_DIM
        assert all(x == 0.0 for x in embedding), "Empty string should return zero vector"
    
    def test_encode_whitespace_only(self):
        """Test encoding whitespace returns zero vector."""
        service = EmbeddingService()
        
        embedding = service.encode("   \n\t  ")
        
        assert len(embedding) == EmbeddingService.EMBEDDING_DIM
        assert all(x == 0.0 for x in embedding), "Whitespace-only should return zero vector"


class TestEmbeddingServiceBatchEncoding:
    """Test batch encoding functionality."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService.reset_instance()
    
    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService.reset_instance()
    
    def test_encode_batch_returns_list_of_embeddings(self):
        """Test batch encoding returns correct structure."""
        service = EmbeddingService()
        
        texts = ["Hello", "World", "Test"]
        embeddings = service.encode_batch(texts)
        
        assert len(embeddings) == 3
        assert all(len(emb) == EmbeddingService.EMBEDDING_DIM for emb in embeddings)
    
    def test_encode_batch_empty_list(self):
        """Test batch encoding empty list returns empty list."""
        service = EmbeddingService()
        
        embeddings = service.encode_batch([])
        
        assert embeddings == []
    
    def test_encode_batch_matches_individual(self):
        """Test batch encoding produces same results as individual encoding."""
        service = EmbeddingService()
        
        texts = ["First text", "Second text", "Third text"]
        
        # Batch encode
        batch_embeddings = service.encode_batch(texts)
        
        # Individual encode
        individual_embeddings = [service.encode(text) for text in texts]
        
        # Should be the same
        for batch_emb, individual_emb in zip(batch_embeddings, individual_embeddings):
            similarity = np.dot(batch_emb, individual_emb) / (
                np.linalg.norm(batch_emb) * np.linalg.norm(individual_emb)
            )
            assert similarity > 0.999, "Batch and individual should match"
    
    def test_encode_batch_with_empty_strings(self):
        """Test batch encoding handles empty strings."""
        service = EmbeddingService()
        
        texts = ["Valid text", "", "Another valid"]
        embeddings = service.encode_batch(texts)
        
        assert len(embeddings) == 3
        # Middle one (empty) should be zero vector
        assert all(x == 0.0 for x in embeddings[1])
        # Others should be non-zero
        assert any(x != 0.0 for x in embeddings[0])
        assert any(x != 0.0 for x in embeddings[2])


class TestEmbeddingServiceDimensions:
    """Test embedding dimensions constant."""
    
    def test_embedding_dim_constant(self):
        """Test that EMBEDDING_DIM matches the configured model."""
        assert EmbeddingService.EMBEDDING_DIM == 1024
    
    def test_model_name_constant(self):
        """Test that MODEL_NAME is BAAI/bge-m3."""
        assert EmbeddingService.MODEL_NAME == "BAAI/bge-m3"


class TestQwen3Backend:
    """Test the Qwen3-Embedding-0.6B backend (2026-08 switch)."""

    def test_backend_qwen_constant(self):
        """Qwen3 backend id is 'qwen3' and is a registered neural backend."""
        from backend.memory.embedding import BACKEND_QWEN, BACKEND_NEURAL
        assert BACKEND_QWEN == "qwen3"
        assert BACKEND_QWEN in BACKEND_NEURAL

    def test_model_name_qwen_constant(self):
        """Qwen3 model name resolves to the 0.6B sentence-transformers model."""
        assert EmbeddingService.MODEL_NAME_QWEN == "Qwen/Qwen3-Embedding-0.6B"

    def test_window_for_qwen(self):
        """Qwen3 uses its 32K context window for chunking."""
        assert EmbeddingService._window_for("qwen3") == 32768

    def test_default_backend_is_qwen(self):
        """Config default backend is qwen3 after the 2026-08 switch."""
        from backend.memory.config import VectorSearchConfig
        assert VectorSearchConfig().backend == "qwen3"

    def test_resolve_selected_backend_defaults_qwen(self):
        """Service resolves qwen3 when config is untouched (default)."""
        service = EmbeddingService()
        assert service._resolve_selected_backend() == "qwen3"
        EmbeddingService.reset_instance()

    def test_encode_qwen_dim(self):
        """Encoding through the qwen3 backend returns 1024-dim vectors."""
        service = EmbeddingService()
        emb = service.encode_with_backend("test query about waterfalls", "qwen3")
        assert emb is not None, "qwen3 backend should load (model is pre-warmed)"
        assert len(emb) == EmbeddingService.EMBEDDING_DIM
        EmbeddingService.reset_instance()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
