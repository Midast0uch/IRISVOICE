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
        """Test that model is loaded lazily on first encode()."""
        service = EmbeddingService()
        
        # Model should be None before
        assert service._model is None
        
        # Trigger lazy loading
        embedding = service.encode("Hello world")
        
        # Model should now be loaded
        assert service._model is not None, "Model should be loaded after encode()"
        assert len(embedding) == 384, "Should return 384-dim vector"


class TestEmbeddingServiceEncoding:
    """Test encoding functionality."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        EmbeddingService.reset_instance()
    
    def teardown_method(self):
        """Reset singleton after each test."""
        EmbeddingService.reset_instance()
    
    def test_encode_returns_384_dimensions(self):
        """Test that encode returns 384-dimensional vector."""
        service = EmbeddingService()
        embedding = service.encode("Hello world")
        
        assert len(embedding) == 384, f"Expected 384 dimensions, got {len(embedding)}"
    
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
        
        assert len(embedding) == 384
        assert all(x == 0.0 for x in embedding), "Empty string should return zero vector"
    
    def test_encode_whitespace_only(self):
        """Test encoding whitespace returns zero vector."""
        service = EmbeddingService()
        
        embedding = service.encode("   \n\t  ")
        
        assert len(embedding) == 384
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
        assert all(len(emb) == 384 for emb in embeddings)
    
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
        """Test that EMBEDDING_DIM is 384."""
        assert EmbeddingService.EMBEDDING_DIM == 384
    
    def test_model_name_constant(self):
        """Test that MODEL_NAME is all-MiniLM-L6-v2."""
        assert EmbeddingService.MODEL_NAME == "all-MiniLM-L6-v2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
