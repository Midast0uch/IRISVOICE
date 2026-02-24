
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path

class SessionReplay:
    """
    Records and replays user sessions for debugging and analysis.
    This tool captures a timeline of events and state changes within a session.
    """

    def __init__(self, session_id: str, recording_dir: Path = Path("./recordings")):
        self.session_id = session_id
        self.recording_dir = recording_dir
        self.events: List[Dict[str, Any]] = []
        self.is_recording = False
        self.start_time: Optional[datetime] = None

        self.recording_dir.mkdir(parents=True, exist_ok=True)

    def start_recording(self):
        """Starts a new recording session."""
        if self.is_recording:
            return

        self.is_recording = True
        self.start_time = datetime.now(timezone.utc)
        self.events = []
        self.add_event("session_start", {"session_id": self.session_id})

    def stop_recording(self):
        """Stops the current recording session."""
        if not self.is_recording:
            return

        self.add_event("session_end", {"session_id": self.session_id})
        self.is_recording = False

    def add_event(self, event_type: str, payload: Dict[str, Any]):
        """Adds a new event to the recording timeline."""
        if not self.is_recording or not self.start_time:
            return

        timestamp = datetime.now(timezone.utc)
        time_offset = (timestamp - self.start_time).total_seconds()

        event = {
            "timestamp": timestamp.isoformat(),
            "time_offset": time_offset,
            "event_type": event_type,
            "payload": payload,
        }
        self.events.append(event)

    def save_recording(self) -> Optional[Path]:
        """Saves the recorded events to a JSON file."""
        if not self.events or not self.start_time:
            return None

        filename = f"session_{self.session_id}_{self.start_time.strftime('%Y%m%d_%H%M%S')}.json"
        file_path = self.recording_dir / filename

        recording = {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
            "event_count": len(self.events),
            "events": self.events,
        }
        
        try:
            with open(file_path, "w") as f:
                json.dump(recording, f, default=lambda o: o.__dict__ if hasattr(o, '__dict__') else str(o), indent=4)
            return file_path
        except (IOError, TypeError) as e:
            print(f"Error saving recording: {e}")
            return None

    @staticmethod
    def load_recording(file_path: Path) -> Optional[Dict[str, Any]]:
        """Loads a session recording from a JSON file."""
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return None
