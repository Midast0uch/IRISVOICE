"""
Defines the different types of sessions available in IRISVOICE.
"""
from enum import Enum, auto

class SessionType(Enum):
    """Enum for the different types of sessions."""
    MAIN = auto()
    VISION = auto()
    ISOLATED = auto()

class Session:
    """Base class for all session types."""
    def __init__(self, session_id: str, session_type: SessionType):
        self.session_id = session_id
        self.session_type = session_type

    def __repr__(self):
        return f"{self.__class__.__name__}(session_id='{self.session_id}', session_type='{self.session_type.name}')"

class MainSession(Session):
    """Main session type, with full access to all features."""
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.MAIN)

class VisionSession(Session):
    """Vision session type, with access to vision-related features."""
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.VISION)

class IsolatedSession(Session):
    """Isolated session type, with limited access to features."""
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.ISOLATED)
