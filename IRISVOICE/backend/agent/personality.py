"""
Personality Manager - Manages AI assistant personality and behavior
"""
import logging
from typing import Optional, Dict, Any, Set
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


# Allowed values for personality traits
ALLOWED_TONES = {"professional", "casual", "friendly", "formal", "enthusiastic"}
ALLOWED_FORMALITY = {"very_formal", "formal", "neutral", "informal", "very_informal"}
ALLOWED_VERBOSITY = {"concise", "balanced", "detailed", "comprehensive"}
ALLOWED_HUMOR = {"none", "subtle", "moderate", "playful"}
ALLOWED_EMPATHY = {"low", "moderate", "high", "very_high"}


@dataclass
class PersonalityProfile:
    """AI personality configuration"""
    assistant_name: str = "IRIS"
    tone: str = "friendly"  # professional/casual/friendly/formal/enthusiastic
    formality: str = "neutral"  # very_formal/formal/neutral/informal/very_informal
    verbosity: str = "balanced"  # concise/balanced/detailed/comprehensive
    humor: str = "subtle"  # none/subtle/moderate/playful
    empathy: str = "moderate"  # low/moderate/high/very_high
    knowledge: str = "general"  # general/technical/creative/analytical


class PersonalityManager:
    """
    Manages AI personality and generates system prompts
    """
    
    _instance: Optional['PersonalityManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if PersonalityManager._initialized:
            return
        
        self.profile = PersonalityProfile()
        self._system_prompt: Optional[str] = None
        self._cache_valid = False
        
        PersonalityManager._initialized = True
    
    def load_from_config(self, config: Dict[str, Any]) -> None:
        """
        Load personality configuration from agent.identity fields
        
        Args:
            config: Dictionary containing identity fields
        
        Raises:
            ValueError: If any personality value is invalid
        """
        identity = config.get("identity", {})
        
        # Extract and validate each field
        updates = {}
        
        if "assistant_name" in identity:
            updates["assistant_name"] = identity["assistant_name"]
        
        if "tone" in identity:
            tone = identity["tone"].lower()
            if tone not in ALLOWED_TONES:
                raise ValueError(
                    f"Invalid tone '{tone}'. Allowed values: {', '.join(sorted(ALLOWED_TONES))}"
                )
            updates["tone"] = tone
        
        if "formality" in identity:
            formality = identity["formality"].lower()
            if formality not in ALLOWED_FORMALITY:
                raise ValueError(
                    f"Invalid formality '{formality}'. Allowed values: {', '.join(sorted(ALLOWED_FORMALITY))}"
                )
            updates["formality"] = formality
        
        if "verbosity" in identity:
            verbosity = identity["verbosity"].lower()
            if verbosity not in ALLOWED_VERBOSITY:
                raise ValueError(
                    f"Invalid verbosity '{verbosity}'. Allowed values: {', '.join(sorted(ALLOWED_VERBOSITY))}"
                )
            updates["verbosity"] = verbosity
        
        if "humor" in identity:
            humor = identity["humor"].lower()
            if humor not in ALLOWED_HUMOR:
                raise ValueError(
                    f"Invalid humor '{humor}'. Allowed values: {', '.join(sorted(ALLOWED_HUMOR))}"
                )
            updates["humor"] = humor
        
        if "empathy" in identity:
            empathy = identity["empathy"].lower()
            if empathy not in ALLOWED_EMPATHY:
                raise ValueError(
                    f"Invalid empathy '{empathy}'. Allowed values: {', '.join(sorted(ALLOWED_EMPATHY))}"
                )
            updates["empathy"] = empathy
        
        if "knowledge" in identity:
            updates["knowledge"] = identity["knowledge"].lower()
        
        # Apply updates
        if updates:
            self.update_profile(**updates)
            logger.info(f"[PersonalityManager] Loaded configuration: {updates}")
    
    def update_profile(self, **kwargs) -> None:
        """
        Update personality profile
        
        Args:
            **kwargs: Personality attributes to update
        
        Raises:
            ValueError: If any value is invalid
        """
        # Validate before updating
        for key, value in kwargs.items():
            if not hasattr(self.profile, key):
                raise ValueError(f"Unknown personality attribute: {key}")
            
            # Validate against allowed values
            if key == "tone" and value not in ALLOWED_TONES:
                raise ValueError(
                    f"Invalid tone '{value}'. Allowed values: {', '.join(sorted(ALLOWED_TONES))}"
                )
            elif key == "formality" and value not in ALLOWED_FORMALITY:
                raise ValueError(
                    f"Invalid formality '{value}'. Allowed values: {', '.join(sorted(ALLOWED_FORMALITY))}"
                )
            elif key == "verbosity" and value not in ALLOWED_VERBOSITY:
                raise ValueError(
                    f"Invalid verbosity '{value}'. Allowed values: {', '.join(sorted(ALLOWED_VERBOSITY))}"
                )
            elif key == "humor" and value not in ALLOWED_HUMOR:
                raise ValueError(
                    f"Invalid humor '{value}'. Allowed values: {', '.join(sorted(ALLOWED_HUMOR))}"
                )
            elif key == "empathy" and value not in ALLOWED_EMPATHY:
                raise ValueError(
                    f"Invalid empathy '{value}'. Allowed values: {', '.join(sorted(ALLOWED_EMPATHY))}"
                )
        
        # Apply updates
        for key, value in kwargs.items():
            setattr(self.profile, key, value)
        
        self._cache_valid = False
        logger.info(f"[PersonalityManager] Updated profile: {kwargs}")
    
    def get_profile(self) -> Dict[str, Any]:
        """Get current personality profile"""
        return asdict(self.profile)
    
    def get_system_prompt(self) -> str:
        """
        Generate system prompt based on personality configuration
        
        Returns:
            System prompt string incorporating personality traits
        """
        if self._cache_valid and self._system_prompt:
            return self._system_prompt
        
        # Build personality-aware system prompt
        tone_desc = self._get_tone_description()
        formality_desc = self._get_formality_description()
        verbosity_desc = self._get_verbosity_description()
        humor_desc = self._get_humor_description()
        empathy_desc = self._get_empathy_description()
        knowledge_desc = self._get_knowledge_description()
        
        prompt = f"""You are {self.profile.assistant_name}, an AI assistant with the following personality:

Tone: {tone_desc}
Formality: {formality_desc}
Communication Style: {verbosity_desc}
Humor: {humor_desc}
Empathy: {empathy_desc}
Knowledge Focus: {knowledge_desc}

Embody these traits naturally in your responses. Be helpful, accurate, and maintain consistency with your personality throughout the conversation."""
        
        self._system_prompt = prompt
        self._cache_valid = True
        return prompt
    
    def _get_tone_description(self) -> str:
        """Get description for tone"""
        descriptions = {
            "professional": "Maintain a professional, business-appropriate demeanor",
            "casual": "Use a relaxed, informal conversational style",
            "friendly": "Be warm, approachable, and personable",
            "formal": "Use formal language and structured communication",
            "enthusiastic": "Show energy, excitement, and positive engagement"
        }
        return descriptions.get(self.profile.tone, descriptions["friendly"])
    
    def _get_formality_description(self) -> str:
        """Get description for formality level"""
        descriptions = {
            "very_formal": "Use highly formal language, avoid contractions, maintain strict professional distance",
            "formal": "Use formal language with proper grammar and professional courtesy",
            "neutral": "Balance between formal and informal, adapt to context",
            "informal": "Use conversational language with some casual expressions",
            "very_informal": "Use casual, relaxed language with colloquialisms"
        }
        return descriptions.get(self.profile.formality, descriptions["neutral"])
    
    def _get_verbosity_description(self) -> str:
        """Get description for verbosity level"""
        descriptions = {
            "concise": "Keep responses brief and to-the-point (1-2 sentences when possible)",
            "balanced": "Provide complete but concise responses (2-4 sentences typical)",
            "detailed": "Give thorough explanations with context and examples",
            "comprehensive": "Provide in-depth, exhaustive responses covering all aspects"
        }
        return descriptions.get(self.profile.verbosity, descriptions["balanced"])
    
    def _get_humor_description(self) -> str:
        """Get description for humor level"""
        descriptions = {
            "none": "Maintain a serious, straightforward tone without humor",
            "subtle": "Occasionally use light, understated humor when appropriate",
            "moderate": "Include humor naturally in conversation when fitting",
            "playful": "Use humor frequently, be witty and entertaining"
        }
        return descriptions.get(self.profile.humor, descriptions["subtle"])
    
    def _get_empathy_description(self) -> str:
        """Get description for empathy level"""
        descriptions = {
            "low": "Focus on facts and information, minimal emotional engagement",
            "moderate": "Show understanding and consideration for user feelings",
            "high": "Demonstrate strong emotional awareness and supportive responses",
            "very_high": "Prioritize emotional support, validate feelings extensively"
        }
        return descriptions.get(self.profile.empathy, descriptions["moderate"])
    
    def _get_knowledge_description(self) -> str:
        """Get description for knowledge focus"""
        descriptions = {
            "general": "Broad general knowledge across many topics",
            "technical": "Software development, programming, and technical implementation",
            "creative": "Creative writing, storytelling, and artistic expression",
            "analytical": "Data analysis, research, and logical reasoning"
        }
        return descriptions.get(self.profile.knowledge, descriptions["general"])
    
    def validate_personality_config(self, config: Dict[str, Any]) -> Dict[str, str]:
        """
        Validate personality configuration without applying it
        
        Args:
            config: Dictionary containing identity fields to validate
        
        Returns:
            Dictionary of validation errors (empty if valid)
        """
        errors = {}
        identity = config.get("identity", {})
        
        if "tone" in identity:
            tone = identity["tone"].lower()
            if tone not in ALLOWED_TONES:
                errors["tone"] = f"Invalid value '{tone}'. Allowed: {', '.join(sorted(ALLOWED_TONES))}"
        
        if "formality" in identity:
            formality = identity["formality"].lower()
            if formality not in ALLOWED_FORMALITY:
                errors["formality"] = f"Invalid value '{formality}'. Allowed: {', '.join(sorted(ALLOWED_FORMALITY))}"
        
        if "verbosity" in identity:
            verbosity = identity["verbosity"].lower()
            if verbosity not in ALLOWED_VERBOSITY:
                errors["verbosity"] = f"Invalid value '{verbosity}'. Allowed: {', '.join(sorted(ALLOWED_VERBOSITY))}"
        
        if "humor" in identity:
            humor = identity["humor"].lower()
            if humor not in ALLOWED_HUMOR:
                errors["humor"] = f"Invalid value '{humor}'. Allowed: {', '.join(sorted(ALLOWED_HUMOR))}"
        
        if "empathy" in identity:
            empathy = identity["empathy"].lower()
            if empathy not in ALLOWED_EMPATHY:
                errors["empathy"] = f"Invalid value '{empathy}'. Allowed: {', '.join(sorted(ALLOWED_EMPATHY))}"
        
        return errors
    
    def format_response(self, text: str) -> str:
        """
        Format response according to personality settings
        Currently just passes through, but could adjust tone/length
        """
        # Could implement: shortening for concise, expanding for comprehensive, etc.
        return text


def get_personality_manager() -> PersonalityManager:
    """Get the singleton PersonalityManager instance"""
    return PersonalityManager()


# Backward compatibility aliases
PersonalityEngine = PersonalityManager
get_personality_engine = get_personality_manager
