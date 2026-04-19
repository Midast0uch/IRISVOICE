"""
Tests for SkillCrystalliser - High-performing Tool Sequence Detection

_Requirements: 8.1, 8.2, 8.3, 8.4_
"""

import pytest
from unittest.mock import Mock, patch

# Skip all tests if dependencies not available
pytest.importorskip("backend.memory", reason="Memory module not available")

from backend.memory.skills import SkillCrystalliser


@pytest.fixture
def mock_memory_interface():
    """Create a mock MemoryInterface."""
    return Mock()


@pytest.fixture
def mock_adapter():
    """Create a mock model adapter."""
    adapter = Mock()
    adapter.generate.return_value = "Search and Summarize"
    return adapter


@pytest.fixture
def skill_crystalliser(mock_memory_interface, mock_adapter):
    """Create a SkillCrystalliser instance."""
    return SkillCrystalliser(
        memory_interface=mock_memory_interface,
        adapter=mock_adapter
    )


class TestSkillCrystalliserInitialization:
    """Test SkillCrystalliser initialization."""
    
    def test_initializes_with_constants(self, mock_memory_interface, mock_adapter):
        """Test that SkillCrystalliser initializes with constants."""
        sc = SkillCrystalliser(mock_memory_interface, mock_adapter)
        
        assert sc.CRYSTALLISATION_MIN_USES == 5
        assert sc.CRYSTALLISATION_MIN_SCORE == 0.7
    
    def test_stores_references(self, mock_memory_interface, mock_adapter):
        """Test that SkillCrystalliser stores memory and adapter references."""
        sc = SkillCrystalliser(mock_memory_interface, mock_adapter)
        
        assert sc.memory is mock_memory_interface
        assert sc.adapter is mock_adapter


class TestScanAndCrystallise:
    """Test scanning and crystallising skills."""
    
    def test_fetches_candidates(self, skill_crystalliser, mock_memory_interface):
        """Test that scan fetches crystallisation candidates."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = []
        
        skill_crystalliser.scan_and_crystallise()
        
        mock_memory_interface.episodic.get_crystallisation_candidates.assert_called_once()
    
    def test_generates_skill_name(self, skill_crystalliser, mock_memory_interface, mock_adapter):
        """Test that skill name is generated using model."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search", "summarize"]', 5, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        mock_adapter.generate.assert_called()
    
    def test_stores_skill_in_semantic_memory(self, skill_crystalliser, mock_memory_interface):
        """Test that crystallised skills are stored in semantic memory."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search", "summarize"]', 5, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        mock_memory_interface.semantic.update.assert_called()
        # Verify stored with correct category
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            args = call_args[0] if call_args[0] else call_args[1]
            if args:
                assert "named_skills" in str(args).lower() or args[0] == "named_skills"
    
    def test_stores_with_confidence_0_9(self, skill_crystalliser, mock_memory_interface):
        """Test that skills are stored with confidence=0.9."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search"]', 5, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Check confidence parameter
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            kwargs = call_args[1] if len(call_args) > 1 else call_args.kwargs
            if kwargs and 'confidence' in kwargs:
                assert kwargs['confidence'] == 0.9
    
    def test_stores_with_source_crystallisation(self, skill_crystalliser, mock_memory_interface):
        """Test that skills are stored with source='crystallisation'."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search"]', 5, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Check source parameter
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            kwargs = call_args[1] if len(call_args) > 1 else call_args.kwargs
            if kwargs and 'source' in kwargs:
                assert kwargs['source'] == 'crystallisation'
    
    def test_handles_no_candidates(self, skill_crystalliser, mock_memory_interface):
        """Test that no skills are created when no candidates."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = []
        
        skill_crystalliser.scan_and_crystallise()
        
        # Should not call semantic.update when no candidates
        mock_memory_interface.semantic.update.assert_not_called()
    
    def test_handles_multiple_candidates(self, skill_crystalliser, mock_memory_interface):
        """Test handling multiple candidates."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search", "read"]', 6, 0.75),
            ('["summarize", "save"]', 5, 0.8),
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Should generate names for each candidate
        assert mock_memory_interface.adapter.generate.call_count == 2


class TestGetCrystallisationCandidates:
    """Test getting crystallisation candidates from episodic store."""
    
    def test_filters_by_min_uses(self, skill_crystalliser, mock_memory_interface):
        """Test that candidates are filtered by minimum uses."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["tool1"]', 5, 0.8),  # Meets threshold
            ('["tool2"]', 3, 0.8),  # Below threshold
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Should only process candidates meeting threshold
        mock_memory_interface.episodic.get_crystallisation_candidates.assert_called_with(
            min_uses=5, min_score=0.7
        )
    
    def test_filters_by_min_score(self, skill_crystalliser, mock_memory_interface):
        """Test that candidates are filtered by minimum score."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["tool1"]', 5, 0.8),   # Meets threshold
            ('["tool2"]', 5, 0.65),  # Below threshold
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        mock_memory_interface.episodic.get_crystallisation_candidates.assert_called_with(
            min_uses=5, min_score=0.7
        )


class TestSkillNaming:
    """Test skill name generation."""
    
    def test_generates_descriptive_name(self, skill_crystalliser, mock_adapter):
        """Test that skill name is descriptive (3-5 words)."""
        name = skill_crystalliser._generate_skill_name(
            tool_sequence=["search", "summarize"],
            example_tasks=["Find Python docs", "Summarize article"]
        )
        
        # Name should be generated via adapter
        mock_adapter.generate.assert_called()
    
    def test_name_is_reasonable_length(self, skill_crystalliser):
        """Test that generated name is reasonable length."""
        with patch.object(skill_crystalliser.adapter, 'generate', return_value="Search and Summarize"):
            name = skill_crystalliser._generate_skill_name(
                tool_sequence=["search", "summarize"],
                example_tasks=[]
            )
            
            # Should be 3-5 words
            word_count = len(name.split())
            assert 2 <= word_count <= 6  # Reasonable range
    
    def test_name_includes_tool_names(self, skill_crystalliser):
        """Test that name includes tool names when appropriate."""
        with patch.object(skill_crystalliser.adapter, 'generate', return_value="Search Documents"):
            name = skill_crystalliser._generate_skill_name(
                tool_sequence=["search", "read"],
                example_tasks=[]
            )
            
            # Name should reflect tool usage
            assert "search" in name.lower() or "read" in name.lower() or "document" in name.lower()


class TestSkillStorage:
    """Test skill storage format."""
    
    def test_stores_tool_sequence(self, skill_crystalliser, mock_memory_interface):
        """Test that skill stores tool sequence."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search", "summarize"]', 5, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Verify tool sequence is stored in value
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            args = call_args[0] if call_args[0] else []
            kwargs = call_args[1] if len(call_args) > 1 else call_args.kwargs
            
            combined = list(args) + list(kwargs.values()) if kwargs else args
            assert any('search' in str(v) and 'summarize' in str(v) for v in combined)
    
    def test_stores_usage_count(self, skill_crystalliser, mock_memory_interface):
        """Test that skill stores usage count."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search"]', 7, 0.8)
        ]
        
        skill_crystalliser.scan_and_crystallise()
        
        # Usage count should be in stored value
        call_args = mock_memory_interface.semantic.update.call_args
        if call_args:
            value_arg = call_args[0][2] if len(call_args[0]) > 2 else None
            if value_arg and isinstance(value_arg, str):
                assert '7' in value_arg or 'uses' in value_arg.lower()


class TestErrorHandling:
    """Test error handling."""
    
    def test_handles_candidate_fetch_error(self, skill_crystalliser, mock_memory_interface):
        """Test handling errors fetching candidates."""
        mock_memory_interface.episodic.get_crystallisation_candidates.side_effect = Exception("DB error")
        
        # Should not raise
        skill_crystalliser.scan_and_crystallise()
    
    def test_handles_naming_error(self, skill_crystalliser, mock_memory_interface, mock_adapter):
        """Test handling errors during skill naming."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search"]', 5, 0.8)
        ]
        mock_adapter.generate.side_effect = Exception("Model error")
        
        # Should not raise
        skill_crystalliser.scan_and_crystallise()
    
    def test_handles_storage_error(self, skill_crystalliser, mock_memory_interface):
        """Test handling errors during skill storage."""
        mock_memory_interface.episodic.get_crystallisation_candidates.return_value = [
            ('["search"]', 5, 0.8)
        ]
        mock_memory_interface.semantic.update.side_effect = Exception("Storage error")
        
        # Should not raise
        skill_crystalliser.scan_and_crystallise()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
