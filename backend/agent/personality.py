"""
Personality Engine - Manages AI assistant personality and behavior
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class PersonalityProfile:
    """AI personality configuration"""
    assistant_name: str = "IRIS"
    personality: str = "Friendly"  # Professional/Friendly/Concise/Creative/Technical
    knowledge_focus: str = "General"  # General/Coding/Writing/Research/Conversation
    response_length: str = "Balanced"  # Brief/Balanced/Detailed/Comprehensive


class PersonalityEngine:
    """
    Manages AI personality and generates system prompts
    """
    
    _instance: Optional['PersonalityEngine'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if PersonalityEngine._initialized:
            return
        
        self.profile = PersonalityProfile()
        self._system_prompt: Optional[str] = None
        self._cache_valid = False
        
        PersonalityEngine._initialized = True
    
    def update_profile(self, **kwargs) -> None:
        """Update personality profile"""
        for key, value in kwargs.items():
            if hasattr(self.profile, key):
                setattr(self.profile, key, value)
        
        self._cache_valid = False
        print(f"[PersonalityEngine] Updated profile: {kwargs}")
    
    def get_profile(self) -> Dict[str, Any]:
        """Get current personality profile"""
        return asdict(self.profile)
    
    def get_system_prompt(self) -> str:
        """Generate system prompt based on personality"""
        if self._cache_valid and self._system_prompt:
            return self._system_prompt
        
        # Build personality description
        personality_desc = self._get_personality_description()
        knowledge_desc = self._get_knowledge_description()
        length_guidance = self._get_length_guidance()
        
        prompt = f"""You are {self.profile.assistant_name}, an AI assistant with the following traits:

Personality: {personality_desc}
Knowledge Focus: {knowledge_desc}
Response Style: {length_guidance}

You are helpful, accurate, and conversational. You respond naturally as {self.profile.assistant_name}."""
        
        self._system_prompt = prompt
        self._cache_valid = True
        return prompt
    
    def _get_personality_description(self) -> str:
        """Get description for personality type"""
        descriptions = {
            "Professional": "formal, business-oriented, precise, and structured",
            "Friendly": "warm, approachable, conversational, and encouraging",
            "Concise": "brief, direct, efficient, and to-the-point",
            "Creative": "imaginative, expressive, enthusiastic, and inspiring",
            "Technical": "analytical, detailed, precise, and methodical"
        }
        return descriptions.get(self.profile.personality, descriptions["Friendly"])
    
    def _get_knowledge_description(self) -> str:
        """Get description for knowledge focus"""
        descriptions = {
            "General": "broad general knowledge across many topics",
            "Coding": "software development, programming languages, and technical implementation",
            "Writing": "creative writing, grammar, storytelling, and communication",
            "Research": "academic research, analysis, and in-depth investigation",
            "Conversation": "natural dialogue, social interaction, and everyday topics"
        }
        return descriptions.get(self.profile.knowledge_focus, descriptions["General"])
    
    def _get_length_guidance(self) -> str:
        """Get response length guidance"""
        guidance = {
            "Brief": "Keep responses short and concise (1-2 sentences when possible)",
            "Balanced": "Provide complete but concise responses (2-4 sentences typical)",
            "Detailed": "Give thorough explanations with context and examples",
            "Comprehensive": "Provide in-depth, exhaustive responses covering all aspects"
        }
        return guidance.get(self.profile.response_length, guidance["Balanced"])
    
    def format_response(self, text: str) -> str:
        """
        Format response according to personality settings
        Currently just passes through, but could adjust tone/length
        """
        # Could implement: shortening for Concise, expanding for Comprehensive, etc.
        return text


def get_personality_engine() -> PersonalityEngine:
    """Get the singleton PersonalityEngine instance"""
    return PersonalityEngine()
