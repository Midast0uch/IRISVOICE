#!/usr/bin/env python3
"""
Verification script for wake word discovery UI integration.

This script demonstrates the wake word discovery integration with IRISGateway
by simulating WebSocket message exchanges.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.iris_gateway import IRISGateway
from backend.ws_manager import WebSocketManager
from backend.state_manager import StateManager
from unittest.mock import Mock, AsyncMock


async def verify_integration():
    """Verify wake word discovery integration."""
    print("=" * 70)
    print("Wake Word Discovery UI Integration Verification")
    print("=" * 70)
    print()
    
    # Create mock managers
    mock_ws_manager = Mock()
    mock_ws_manager.send_to_client = AsyncMock()
    mock_ws_manager.broadcast_to_session = AsyncMock()
    mock_ws_manager.get_session_id_for_client = Mock(return_value="test_session")
    
    mock_state_manager = Mock()
    
    # Initialize gateway
    print("1. Initializing IRISGateway...")
    try:
        gateway = IRISGateway(
            ws_manager=mock_ws_manager,
            state_manager=mock_state_manager
        )
        print("   ✓ Gateway initialized successfully")
        
        # Check wake word discovery
        discovered_files = gateway._wake_word_discovery.get_discovered_files()
        print(f"   ✓ Found {len(discovered_files)} wake word file(s)")
        
        if discovered_files:
            print("\n   Discovered wake words:")
            for wf in discovered_files:
                print(f"     - {wf.display_name} ({wf.filename})")
                print(f"       Platform: {wf.platform}, Version: {wf.version}")
        else:
            print("\n   ⚠ No wake word files found in models/wake_words directory")
            print("     This is expected if wake word files haven't been added yet")
        
    except Exception as e:
        print(f"   ✗ Error initializing gateway: {e}")
        return False
    
    print()
    
    # Test get_wake_words message
    print("2. Testing get_wake_words message handler...")
    try:
        await gateway.handle_message("client1", {
            "type": "get_wake_words",
            "payload": {}
        })
        
        # Check if response was sent
        if mock_ws_manager.send_to_client.called:
            call_args = mock_ws_manager.send_to_client.call_args
            response = call_args[0][1]
            
            if response["type"] == "wake_words_list":
                count = response["payload"]["count"]
                wake_words = response["payload"]["wake_words"]
                
                print(f"   ✓ Handler responded with wake_words_list")
                print(f"   ✓ Count: {count}")
                
                if wake_words:
                    print(f"   ✓ Wake words in response:")
                    for ww in wake_words:
                        print(f"     - {ww['display_name']} ({ww['filename']})")
                else:
                    print(f"   ✓ Empty wake words list (expected if no files)")
            else:
                print(f"   ✗ Unexpected response type: {response['type']}")
                return False
        else:
            print("   ✗ No response sent")
            return False
            
    except Exception as e:
        print(f"   ✗ Error handling get_wake_words: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    
    # Test select_wake_word message (if files exist)
    if discovered_files:
        print("3. Testing select_wake_word message handler...")
        try:
            test_file = discovered_files[0]
            
            await gateway.handle_message("client1", {
                "type": "select_wake_word",
                "payload": {
                    "filename": test_file.filename
                }
            })
            
            # Check if broadcast was sent
            if mock_ws_manager.broadcast_to_session.called:
                call_args = mock_ws_manager.broadcast_to_session.call_args
                response = call_args[0][1]
                
                if response["type"] == "wake_word_selected":
                    payload = response["payload"]
                    print(f"   ✓ Handler broadcasted wake_word_selected")
                    print(f"   ✓ Selected: {payload['display_name']}")
                    print(f"   ✓ Filename: {payload['filename']}")
                    print(f"   ✓ Platform: {payload['platform']}")
                    print(f"   ✓ Version: {payload['version']}")
                else:
                    print(f"   ✗ Unexpected response type: {response['type']}")
                    return False
            else:
                print("   ✗ No broadcast sent")
                return False
                
        except Exception as e:
            print(f"   ✗ Error handling select_wake_word: {e}")
            import traceback
            traceback.print_exc()
            return False
    else:
        print("3. Skipping select_wake_word test (no wake word files)")
    
    print()
    
    # Test error handling
    print("4. Testing error handling...")
    try:
        # Test with missing filename
        mock_ws_manager.send_to_client.reset_mock()
        
        await gateway.handle_message("client1", {
            "type": "select_wake_word",
            "payload": {}
        })
        
        if mock_ws_manager.send_to_client.called:
            call_args = mock_ws_manager.send_to_client.call_args
            response = call_args[0][1]
            
            if response["type"] == "error":
                print(f"   ✓ Error handling works (missing filename)")
                print(f"   ✓ Error message: {response['payload']['message']}")
            else:
                print(f"   ✗ Expected error response, got: {response['type']}")
                return False
        else:
            print("   ✗ No error response sent")
            return False
            
    except Exception as e:
        print(f"   ✗ Error in error handling test: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 70)
    print("✓ All verification tests passed!")
    print("=" * 70)
    print()
    print("Next Steps:")
    print("1. Frontend: Implement wake word dropdown in WheelView")
    print("2. Frontend: Implement wake word dropdown in DarkGlassDashboard")
    print("3. Backend: Integrate selected wake word with PorcupineDetector")
    print()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(verify_integration())
    sys.exit(0 if success else 1)
