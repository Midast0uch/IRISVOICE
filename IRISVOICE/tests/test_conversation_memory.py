"""
Unit tests for ConversationMemory class
"""
import pytest
import json
import time
import tempfile
import shutil
from pathlib import Path
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.agent.memory import ConversationMemory, Message, get_conversation_memory


@pytest.fixture
def temp_session_dir():
    """Create a temporary session directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def conversation_memory(temp_session_dir):
    """Create a ConversationMemory instance for testing"""
    return ConversationMemory(
        session_id="test-session-123",
        max_messages=10,
        session_storage_path=temp_session_dir
    )


class TestConversationMemoryBasics:
    """Test basic ConversationMemory functionality"""
    
    def test_initialization(self, conversation_memory):
        """Test ConversationMemory initialization"""
        assert conversation_memory.session_id == "test-session-123"
        assert conversation_memory.max_messages == 10
        assert len(conversation_memory.messages) == 0
        assert conversation_memory.session_start > 0
    
    def test_add_message(self, conversation_memory):
        """Test adding a message"""
        conversation_memory.add_message(
            role="user",
            content="Hello, IRIS!",
            text_tokens=5
        )
        
        assert len(conversation_memory.messages) == 1
        assert conversation_memory.messages[0].role == "user"
        assert conversation_memory.messages[0].content == "Hello, IRIS!"
        assert conversation_memory.messages[0].text_tokens == 5
    
    def test_add_message_with_tool_results(self, conversation_memory):
        """Test adding a message with tool results"""
        tool_results = [
            {"tool": "web_search", "result": "Found 10 results"}
        ]
        
        conversation_memory.add_message(
            role="assistant",
            content="I found some results for you.",
            text_tokens=10,
            tool_results=tool_results
        )
        
        assert len(conversation_memory.messages) == 1
        assert conversation_memory.messages[0].tool_results == tool_results
    
    def test_get_context(self, conversation_memory):
        """Test getting conversation context"""
        conversation_memory.add_message("user", "Hello", text_tokens=2)
        conversation_memory.add_message("assistant", "Hi there!", text_tokens=3)
        
        context = conversation_memory.get_context()
        
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"
        assert context[1]["role"] == "assistant"
        assert context[1]["content"] == "Hi there!"
    
    def test_get_context_with_limit(self, conversation_memory):
        """Test getting context with message limit"""
        for i in range(5):
            conversation_memory.add_message("user", f"Message {i}", text_tokens=2)
        
        context = conversation_memory.get_context(max_messages=3)
        
        assert len(context) == 3
        assert context[0]["content"] == "Message 2"
        assert context[2]["content"] == "Message 4"
    
    def test_clear(self, conversation_memory):
        """Test clearing conversation history"""
        conversation_memory.add_message("user", "Hello", text_tokens=2)
        conversation_memory.add_message("assistant", "Hi!", text_tokens=2)
        
        assert len(conversation_memory.messages) == 2
        
        conversation_memory.clear()
        
        assert len(conversation_memory.messages) == 0


class TestConversationMemoryLimit:
    """Test message limit functionality"""
    
    def test_rolling_window(self, conversation_memory):
        """Test that messages are limited to max_messages"""
        # Add 15 messages (max is 10)
        for i in range(15):
            conversation_memory.add_message("user", f"Message {i}", text_tokens=2)
        
        # Should only keep the last 10
        assert len(conversation_memory.messages) == 10
        assert conversation_memory.messages[0].content == "Message 5"
        assert conversation_memory.messages[9].content == "Message 14"
    
    def test_custom_max_messages(self, temp_session_dir):
        """Test custom max_messages limit"""
        memory = ConversationMemory(
            session_id="test-custom",
            max_messages=5,
            session_storage_path=temp_session_dir
        )
        
        for i in range(10):
            memory.add_message("user", f"Message {i}", text_tokens=2)
        
        assert len(memory.messages) == 5
        assert memory.messages[0].content == "Message 5"


class TestConversationMemoryPersistence:
    """Test persistence functionality"""
    
    def test_persist_to_session_storage(self, conversation_memory, temp_session_dir):
        """Test persisting conversation to session storage"""
        conversation_memory.add_message("user", "Test message", text_tokens=3)
        
        # Check that conversation.json was created
        conversation_file = Path(temp_session_dir) / "conversation.json"
        assert conversation_file.exists()
        
        # Verify content
        with open(conversation_file, 'r') as f:
            data = json.load(f)
        
        assert data["session_id"] == "test-session-123"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Test message"
    
    def test_load_from_session_storage(self, temp_session_dir):
        """Test loading conversation from session storage"""
        # Create a conversation file
        conversation_file = Path(temp_session_dir) / "conversation.json"
        data = {
            "session_id": "test-session-123",
            "session_start": time.time(),
            "last_updated": time.time(),
            "max_messages": 10,
            "messages": [
                {
                    "role": "user",
                    "content": "Persisted message",
                    "timestamp": time.time(),
                    "audio_tokens": 0,
                    "text_tokens": 3,
                    "tool_results": None
                }
            ]
        }
        
        with open(conversation_file, 'w') as f:
            json.dump(data, f)
        
        # Create new memory instance - should load from storage
        memory = ConversationMemory(
            session_id="test-session-123",
            session_storage_path=temp_session_dir
        )
        
        assert len(memory.messages) == 1
        assert memory.messages[0].content == "Persisted message"
    
    def test_archive_on_session_end(self, conversation_memory, temp_session_dir):
        """Test archiving conversation on session end"""
        conversation_memory.add_message("user", "Message 1", text_tokens=2)
        conversation_memory.add_message("assistant", "Response 1", text_tokens=3)
        
        result = conversation_memory.archive_on_session_end()
        
        assert result is True
        
        # Check that archive file was created
        archive_files = list(Path(temp_session_dir).glob("conversation_archive_*.json"))
        assert len(archive_files) == 1
        
        # Verify archive content
        with open(archive_files[0], 'r') as f:
            data = json.load(f)
        
        assert data["session_id"] == "test-session-123"
        assert data["message_count"] == 2
        assert len(data["messages"]) == 2


class TestConversationMemoryUtilities:
    """Test utility methods"""
    
    def test_get_token_count(self, conversation_memory):
        """Test token counting"""
        conversation_memory.add_message("user", "Hello", audio_tokens=5, text_tokens=2)
        conversation_memory.add_message("assistant", "Hi!", audio_tokens=3, text_tokens=1)
        
        token_info = conversation_memory.get_token_count()
        
        assert token_info["audio_tokens"] == 8
        assert token_info["text_tokens"] == 3
        assert token_info["total_tokens"] == 11
        assert token_info["message_count"] == 2
        assert token_info["max_messages"] == 10
    
    def test_get_context_visualization(self, conversation_memory):
        """Test context visualization"""
        conversation_memory.add_message("user", "Test message", text_tokens=5)
        
        viz = conversation_memory.get_context_visualization()
        
        assert "usage_percent" in viz
        assert "token_breakdown" in viz
        assert "messages" in viz
        assert len(viz["messages"]) == 1
        assert viz["messages"][0]["role"] == "user"
    
    def test_get_summary(self, conversation_memory):
        """Test getting conversation summary"""
        conversation_memory.add_message("user", "Hello", text_tokens=2)
        conversation_memory.add_message("assistant", "Hi!", text_tokens=2)
        
        summary = conversation_memory.get_summary()
        
        assert "test-session-123" in summary
        assert "Messages: 2" in summary
    
    def test_search(self, conversation_memory):
        """Test searching conversation history"""
        conversation_memory.add_message("user", "What is the weather?", text_tokens=5)
        conversation_memory.add_message("assistant", "It's sunny today.", text_tokens=4)
        conversation_memory.add_message("user", "Tell me a joke.", text_tokens=4)
        
        results = conversation_memory.search("weather")
        
        assert len(results) == 1
        assert results[0].content == "What is the weather?"
    
    def test_export_to_file(self, conversation_memory, temp_session_dir):
        """Test exporting conversation to file"""
        conversation_memory.add_message("user", "Export test", text_tokens=3)
        
        export_file = Path(temp_session_dir) / "export.json"
        result = conversation_memory.export_to_file(str(export_file))
        
        assert result is True
        assert export_file.exists()
        
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        assert data["session_id"] == "test-session-123"
        assert len(data["messages"]) == 1
    
    def test_import_from_file(self, conversation_memory, temp_session_dir):
        """Test importing conversation from file"""
        # Create import file
        import_file = Path(temp_session_dir) / "import.json"
        data = {
            "session_id": "test-session-123",
            "messages": [
                {
                    "role": "user",
                    "content": "Imported message",
                    "timestamp": time.time(),
                    "audio_tokens": 0,
                    "text_tokens": 3,
                    "tool_results": None
                }
            ]
        }
        
        with open(import_file, 'w') as f:
            json.dump(data, f)
        
        result = conversation_memory.import_from_file(str(import_file))
        
        assert result is True
        assert len(conversation_memory.messages) == 1
        assert conversation_memory.messages[0].content == "Imported message"


class TestGetConversationMemory:
    """Test the get_conversation_memory factory function"""
    
    def test_get_default_session(self):
        """Test getting default session memory"""
        memory1 = get_conversation_memory()
        memory2 = get_conversation_memory()
        
        # Should return the same instance for default session
        assert memory1 is memory2
    
    def test_get_custom_session(self, temp_session_dir):
        """Test getting custom session memory"""
        memory1 = get_conversation_memory(
            session_id="custom-1",
            max_messages=5
        )
        memory2 = get_conversation_memory(
            session_id="custom-2",
            max_messages=5
        )
        
        # Should return different instances for different sessions
        assert memory1 is not memory2
        assert memory1.session_id == "custom-1"
        assert memory2.session_id == "custom-2"


class TestBackwardCompatibility:
    """Test backward compatibility with legacy code"""
    
    def test_get_context_window(self, conversation_memory):
        """Test legacy get_context_window method"""
        conversation_memory.add_message("user", "Hello", text_tokens=2)
        conversation_memory.add_message("assistant", "Hi!", text_tokens=2)
        
        context = conversation_memory.get_context_window()
        
        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"
    
    def test_prune_if_needed(self, conversation_memory):
        """Test legacy _prune_if_needed method"""
        # Add messages that exceed token limit
        for i in range(5):
            conversation_memory.add_message(
                "user",
                f"Message {i}",
                text_tokens=2000  # Total will exceed 8192
            )
        
        conversation_memory._prune_if_needed()
        
        # Should have pruned some messages
        assert len(conversation_memory.messages) < 5
