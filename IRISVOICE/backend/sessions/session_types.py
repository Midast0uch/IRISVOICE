"""
IRIS Session Types
Defines session type hierarchy for session isolation.
"""
from enum import Enum, auto


class SessionType(Enum):
    MAIN = auto()
    VISION = auto()
    ISOLATED = auto()


class Session:
    """Base session type."""
    def __init__(self, session_id: str, session_type: SessionType):
        self.session_id = session_id
        self.session_type = session_type

    def __repr__(self):
        return f"{self.__class__.__name__}(session_id={self.session_id}, session_type={self.session_type.name})"


class MainSession(Session):
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.MAIN)


class VisionSession(Session):
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.VISION)


class IsolatedSession(Session):
    def __init__(self, session_id: str):
        super().__init__(session_id, SessionType.ISOLATED)
