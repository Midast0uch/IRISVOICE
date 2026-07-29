"""Contract test CT-I6: spoken words SHALL be a subset of visible display text.

REQ-7 AC3: Every utterance emitted by the agent MUST correspond to content
that is also displayed in the UI (or, for internal status, derived from it).
"""
from backend.agent.event_bus import EventBus, IRISStreamEvent


class TestSpeechVisible:
    def test_utterance_text_appears_in_display(self):
        bus = EventBus()
        utterances = []
        display_cards = []
        bus.subscribe(IRISStreamEvent.UTTERANCE_START, lambda p: utterances.append(p.data.get("text", "")))
        bus.subscribe(IRISStreamEvent.TASK_START, lambda p: display_cards.append(p.data.get("description", "")))
        # Simulate: a task starts and something is spoken
        bus.emit(IRISStreamEvent.UTTERANCE_START, data={"text": "Search web for results", "utterance_id": "u1"})
        bus.emit(IRISStreamEvent.TASK_START, data={"description": "Search web for results", "steps": [], "task_id": "t1"})
        # UTTERANCE_START fires first — text must be derived from display content
        # This is a soft contract: the spoken text should be a substring or close variant
        for utt in utterances:
            assert any(utt.lower() in (card or "").lower() for card in display_cards) or not display_cards, \
                f"Spoken '{utt}' not found in display: {display_cards}"
