"""
Test Backward Compatibility - Verifying NO subnode_id support exists

Per user instruction: "we dont need the need websocket messages to accept any subnode id anymore"
These tests should FAIL if backward compatibility was properly removed.
If any test passes, it indicates leftover backward compatibility code that needs cleanup.
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.models import (
    SelectSectionMessage, 
    FieldUpdateMessage, 
    ConfirmCardMessage,
    FieldUpdatedMessage,
    CardConfirmedMessage
)
from backend.core_models import IRISState


class TestNoBackwardCompatibility:
    """
    Verify that old 'subnode_id' terminology is NOT supported.
    These tests expect failures - if they pass, backward compatibility still exists.
    """
    
    def test_select_section_rejects_subnode_id(self):
        """
        SelectSectionMessage should NOT accept 'subnode_id' field.
        If this test passes (no exception), backward compatibility exists and needs removal.
        """
        with pytest.raises((ValueError, TypeError)):
            # Old format using subnode_id - should fail
            msg = SelectSectionMessage(
                type="select_section",
                subnode_id="input"  # Old field name - should be rejected
            )
        # If we reach here without exception, backward compatibility exists (BAD)
    
    def test_field_update_rejects_subnode_id(self):
        """
        FieldUpdateMessage should NOT accept 'subnode_id' field.
        """
        with pytest.raises((ValueError, TypeError)):
            msg = FieldUpdateMessage(
                type="update_field",
                subnode_id="input",  # Old field name
                field_id="volume",
                value=50
            )
    
    def test_confirm_card_rejects_subnode_id(self):
        """
        ConfirmCardMessage should NOT accept 'subnode_id' field.
        """
        with pytest.raises((ValueError, TypeError)):
            msg = ConfirmCardMessage(
                type="confirm_card",
                subnode_id="input",  # Old field name
                values={}
            )
    
    def test_iris_state_rejects_current_subnode(self):
        """
        IRISState should NOT have 'current_subnode' field.
        """
        with pytest.raises((ValueError, TypeError)):
            state = IRISState(
                current_subnode="input"  # Old field name
            )
    
    def test_field_updated_response_rejects_subnode_id(self):
        """
        FieldUpdatedMessage should NOT accept 'subnode_id' in response.
        """
        with pytest.raises((ValueError, TypeError)):
            msg = FieldUpdatedMessage(
                type="field_updated",
                subnode_id="input",  # Old field name
                field_id="volume",
                value=50,
                valid=True
            )
    
    def test_card_confirmed_response_rejects_subnode_id(self):
        """
        CardConfirmedMessage should NOT accept 'subnode_id' in response.
        """
        with pytest.raises((ValueError, TypeError)):
            msg = CardConfirmedMessage(
                type="card_confirmed",
                subnode_id="input",  # Old field name
                orbit_angle=0.0
            )


class TestNewTerminologyWorks:
    """Verify that new 'section_id' terminology works correctly."""
    
    def test_select_section_accepts_section_id(self):
        """SelectSectionMessage should accept 'section_id' field."""
        msg = SelectSectionMessage(
            type="select_section",
            section_id="input"
        )
        assert msg.section_id == "input"
    
    def test_field_update_accepts_section_id(self):
        """FieldUpdateMessage should accept 'section_id' field."""
        msg = FieldUpdateMessage(
            type="update_field",
            section_id="input",
            field_id="volume",
            value=50
        )
        assert msg.section_id == "input"
    
    def test_iris_state_accepts_current_section(self):
        """IRISState should have 'current_section' field."""
        state = IRISState(
            current_section="input"
        )
        assert state.current_section == "input"


class TestNoMiniNodeReferences:
    """Verify no 'MiniNode' references remain in the codebase."""
    
    def test_no_subnode_configs_constant(self):
        """SUBNODE_CONFIGS constant should not exist."""
        import backend.models as models
        assert not hasattr(models, 'SUBNODE_CONFIGS'), \
            "SUBNODE_CONFIGS still exists - should be SECTION_CONFIGS"
    
    def test_no_subnode_class(self):
        """SubNode class should not exist."""
        import backend.models as models
        assert not hasattr(models, 'SubNode'), \
            "SubNode class still exists - should be Section"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
