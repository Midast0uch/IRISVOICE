"""
Tests for EpisodicStore - Persistent Task Storage

_Requirements: 2.1, 2.2, 2.3, 2.4_
"""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.episodic import EpisodicStore, Episode


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_episodes.db")


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"


@pytest.fixture
def sample_episode():
    """Create a sample episode for testing."""
    return Episode(
        session_id="test_session_123",
        task_summary="Search for Python documentation",
        full_content="User asked about Python list comprehensions",
        tool_sequence=[
            {"tool": "search", "action": "query", "params": {"q": "python list comprehension"}, "result": "found"}
        ],
        outcome_type="success",
        outcome_score=0.8,
        failure_reason=None,
        user_corrected=False,
        user_confirmed=True,
        duration_ms=2500,
        tokens_used=150,
        model_id="test-model-v1",
        source_channel="websocket",
        node_id="local",
        origin="local"
    )


class TestEpisodeDataclass:
    """Test Episode dataclass."""
    
    def test_episode_creation(self):
        """Test creating an Episode instance."""
        episode = Episode(
            session_id="s1",
            task_summary="test task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success"
        )
        
        assert episode.session_id == "s1"
        assert episode.task_summary == "test task"
        assert episode.node_id == "local"  # Default Torus field
        assert episode.origin == "local"  # Default Torus field
    
    def test_episode_with_all_fields(self):
        """Test creating an Episode with all fields."""
        episode = Episode(
            session_id="s1",
            task_summary="test",
            full_content="content",
            tool_sequence=[{"tool": "search"}],
            outcome_type="success",
            outcome_score=0.9,
            failure_reason=None,
            user_corrected=False,
            user_confirmed=True,
            duration_ms=1000,
            tokens_used=100,
            model_id="model-v1",
            source_channel="websocket",
            node_id="local",
            origin="local"
        )
        
        assert episode.outcome_score == 0.9
        assert episode.duration_ms == 1000


class TestEpisodicStoreInitialization:
    """Test EpisodicStore initialization."""
    
    def test_store_initialization(self, temp_db_path, biometric_key):
        """Test that EpisodicStore initializes."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        assert store is not None
        assert store.db_path == temp_db_path


class TestStoreEpisode:
    """Test storing episodes."""
    
    def test_store_episode(self, temp_db_path, biometric_key, sample_episode):
        """Test storing an episode."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock the database operations
        store.conn = Mock()
        store.conn.execute = Mock()
        store.conn.commit = Mock()
        
        episode_id = store.store(sample_episode)
        
        assert episode_id is not None
        store.conn.execute.assert_called()
        store.conn.commit.assert_called()
    
    def test_store_computes_embedding(self, temp_db_path, biometric_key, sample_episode):
        """Test that store computes embedding for episode."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        with patch.object(store, '_get_embedding') as mock_embed:
            mock_embed.return_value = [0.1] * 384
            store.conn = Mock()
            store.conn.execute = Mock()
            store.conn.commit = Mock()
            
            store.store(sample_episode)
            
            mock_embed.assert_called_once_with(sample_episode.task_summary)


class TestRetrieveSimilar:
    """Test retrieving similar episodes."""
    
    def test_retrieve_similar_returns_list(self, temp_db_path, biometric_key):
        """Test that retrieve_similar returns a list."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock the database
        store.conn = Mock()
        store.conn.execute.return_value.fetchall.return_value = []
        
        results = store.retrieve_similar("test query", top_k=3)
        
        assert isinstance(results, list)
    
    def test_retrieve_similar_filters_by_score(self, temp_db_path, biometric_key):
        """Test that retrieve_similar filters by minimum score."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock results with different scores
        mock_results = [
            ("id1", 0.9, "task1"),
            ("id2", 0.7, "task2"),
            ("id3", 0.5, "task3"),  # Below threshold
        ]
        
        with patch.object(store, '_vector_search', return_value=mock_results):
            results = store.retrieve_similar("query", top_k=3, min_score=0.6)
            
            # Should filter out results below min_score
            scores = [r[1] for r in results]
            assert all(s >= 0.6 for s in scores)
    
    def test_retrieve_similar_limits_top_k(self, temp_db_path, biometric_key):
        """Test that retrieve_similar respects top_k limit."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        # Mock many results
        mock_results = [(f"id{i}", 0.9 - i*0.01, f"task{i}") for i in range(10)]
        
        with patch.object(store, '_vector_search', return_value=mock_results):
            results = store.retrieve_similar("query", top_k=3)
            
            assert len(results) <= 3


class TestRetrieveFailures:
    """Test retrieving failure episodes."""
    
    def test_retrieve_failures_returns_failures_only(self, temp_db_path, biometric_key):
        """Test that retrieve_failures only returns failure episodes."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        store.conn = Mock()
        store.conn.execute.return_value.fetchall.return_value = [
            ("id1", 0.8, "failed task")
        ]
        
        results = store.retrieve_failures("query", top_k=2)
        
        # Verify query includes failure filter
        call_args = store.conn.execute.call_args
        assert "failure" in str(call_args).lower()


class TestAssembleEpisodicContext:
    """Test assembling episodic context for prompts."""
    
    def test_assemble_includes_successes(self, temp_db_path, biometric_key):
        """Test that assemble includes successful episodes."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        mock_episodes = [
            {"task_summary": "Successful task 1", "outcome_type": "success"},
            {"task_summary": "Successful task 2", "outcome_type": "success"},
        ]
        
        with patch.object(store, 'retrieve_similar', return_value=mock_episodes):
            context = store.assemble_episodic_context("current task")
            
            assert "Successful task 1" in context
            assert "Successful task 2" in context
    
    def test_assemble_includes_failure_warnings(self, temp_db_path, biometric_key):
        """Test that assemble includes failure warnings."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        mock_failures = [
            {"task_summary": "Failed task", "outcome_type": "failure"}
        ]
        
        with patch.object(store, 'retrieve_similar', return_value=[]):
            with patch.object(store, 'retrieve_failures', return_value=mock_failures):
                context = store.assemble_episodic_context("current task")
                
                assert "WARNING" in context or "failed" in context.lower()


class TestGetStats:
    """Test getting episode statistics."""
    
    def test_get_stats_returns_dict(self, temp_db_path, biometric_key):
        """Test that get_stats returns a dictionary."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        store.conn = Mock()
        store.conn.execute.return_value.fetchone.return_value = (10,)
        store.conn.execute.return_value.fetchall.return_value = [
            (5,),  # successes
            (3,),  # failures
        ]
        
        stats = store.get_stats()
        
        assert isinstance(stats, dict)
    
    def test_get_stats_includes_total(self, temp_db_path, biometric_key):
        """Test that get_stats includes total episode count."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        store.conn = Mock()
        store.conn.execute.return_value.fetchone.return_value = (10,)
        
        stats = store.get_stats()
        
        assert "total_episodes" in stats or "count" in str(stats).lower()


class TestGetRecentForDistillation:
    """Test getting recent episodes for distillation."""
    
    def test_get_recent_filters_by_hours(self, temp_db_path, biometric_key):
        """Test that get_recent_for_distillation filters by time window."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        store.conn = Mock()
        store.conn.execute.return_value.fetchall.return_value = []
        
        store.get_recent_for_distillation(hours=8, min_episodes=5)
        
        # Verify query includes time filter
        call_args = store.conn.execute.call_args
        assert "hour" in str(call_args).lower() or "timestamp" in str(call_args).lower()


class TestGetCrystallisationCandidates:
    """Test getting skill crystallisation candidates."""
    
    def test_get_candidates_filters_by_count_and_score(self, temp_db_path, biometric_key):
        """Test that candidates are filtered by min uses and score."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        store.conn = Mock()
        store.conn.execute.return_value.fetchall.return_value = [
            ("tool_sequence_json", 5, 0.75)  # count=5, avg_score=0.75
        ]
        
        candidates = store.get_crystallisation_candidates(min_uses=5, min_score=0.7)
        
        assert len(candidates) > 0
        assert candidates[0][1] >= 5  # count >= min_uses
        assert candidates[0][2] >= 0.7  # avg_score >= min_score


class TestOutcomeScoring:
    """Test outcome score computation."""
    
    def test_outcome_score_range(self, temp_db_path, biometric_key):
        """Test that outcome scores are in valid range."""
        store = EpisodicStore(temp_db_path, biometric_key)
        
        episode = Episode(
            session_id="s1",
            task_summary="task",
            full_content="content",
            tool_sequence=[],
            outcome_type="success",
            user_confirmed=True,
            user_corrected=False,
            duration_ms=3000
        )
        
        # Score should be 0.50 + 0.30 + 0.10 + 0.10 = 1.0
        assert 0.0 <= episode.outcome_score <= 1.0


class TestTorusFields:
    """Test Torus-ready fields."""
    
    def test_episode_has_node_id(self, sample_episode):
        """Test that episode has node_id field."""
        assert hasattr(sample_episode, 'node_id')
        assert sample_episode.node_id == "local"
    
    def test_episode_has_origin(self, sample_episode):
        """Test that episode has origin field."""
        assert hasattr(sample_episode, 'origin')
        assert sample_episode.origin == "local"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
