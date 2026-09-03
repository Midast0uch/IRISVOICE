"""
Skill Crystalliser - Pattern detection and skill naming for IRIS.

Detects frequently used, high-score tool sequences and converts them
into named skills stored in semantic memory.

Design Principles:
1. Minimum thresholds - 5+ uses, 0.7+ avg score
2. AI naming - Use model to generate meaningful skill names
3. Confidence scoring - Crystallised skills have high confidence (0.9)
"""

import json
import logging
from typing import Any, List, Dict, Optional

from backend.memory.interface import MemoryInterface

logger = logging.getLogger(__name__)


class SkillCrystalliser:
    """
    Detects and names high-value tool sequences.
    
    Scans episodic memory for tool patterns that:
    - Are used 5+ times (MIN_USES)
    - Have average score >= 0.7 (MIN_SCORE)
    
    Converts qualifying patterns into named skills stored in
    semantic memory for future reuse.
    """
    
    MIN_USES = 5
    MIN_SCORE = 0.7
    CONFIDENCE = 0.9
    
    def __init__(self, memory_interface: MemoryInterface, adapter: Any):
        """
        Initialize SkillCrystalliser.
        
        Args:
            memory_interface: MemoryInterface instance
            adapter: Model adapter for skill naming
        """
        self.memory = memory_interface
        self.adapter = adapter
        
        logger.info(
            f"[SkillCrystalliser] Initialized "
            f"(min_uses={self.MIN_USES}, min_score={self.MIN_SCORE})"
        )
    
    async def scan_and_crystallise(self) -> int:
        """
        Scan for crystallisation candidates and create skills.
        
        Returns:
            Number of skills crystallised
        """
        try:
            # Get candidates from episodic store
            candidates = self.memory.episodic.get_crystallisation_candidates(
                min_uses=self.MIN_USES,
                min_avg_score=self.MIN_SCORE
            )
            
            if not candidates:
                logger.debug("[SkillCrystalliser] No crystallisation candidates found")
                return 0
            
            logger.info(f"[SkillCrystalliser] Found {len(candidates)} candidates")
            
            crystallised = 0
            for candidate in candidates:
                try:
                    if await self._crystallise_skill(candidate):
                        crystallised += 1
                except Exception as e:
                    logger.error(f"[SkillCrystalliser] Failed to crystallise: {e}")
                    continue
            
            return crystallised
            
        except Exception as e:
            logger.error(f"[SkillCrystalliser] Scan failed: {e}")
            return 0
    
    async def _crystallise_skill(self, candidate: Dict[str, Any]) -> bool:
        """
        Convert a candidate tool sequence into a named skill.
        
        Args:
            candidate: Tool sequence candidate with uses and avg_score
        
        Returns:
            True if successfully crystallised
        """
        tool_sequence = candidate.get('tool_sequence', [])
        uses = candidate.get('uses', 0)
        avg_score = candidate.get('avg_score', 0.0)
        
        if not tool_sequence:
            return False
        
        # Generate skill name using model
        skill_name = await self._generate_skill_name(tool_sequence)
        
        # Create skill description
        description = self._create_skill_description(tool_sequence, uses, avg_score)
        
        # Store in semantic memory
        skill_key = f"skill_{skill_name.lower().replace(' ', '_')}"
        
        self.memory.semantic.update(
            category="named_skills",
            key=skill_key,
            value=json.dumps({
                "name": skill_name,
                "description": description,
                "tool_sequence": tool_sequence,
                "uses": uses,
                "avg_score": avg_score
            }),
            confidence=self.CONFIDENCE,
            source="crystallisation"
        )
        
        # Update display memory
        display_name = f"Skill: {skill_name} ({uses} uses, {avg_score:.0%} success)"
        self.memory.semantic.update_user_display(
            key=f"named_skills.{skill_key}",
            display_name=display_name,
            source="auto_learned"
        )
        
        logger.info(
            f"[SkillCrystalliser] Crystallised skill '{skill_name}' "
            f"({uses} uses, {avg_score:.2f} avg score)"
        )
        
        return True
    
    async def _generate_skill_name(self, tool_sequence: List[Dict[str, Any]]) -> str:
        """
        Generate a meaningful name for a tool sequence.
        
        Args:
            tool_sequence: List of tool calls
        
        Returns:
            Generated skill name
        """
        try:
            # Extract tool names
            tool_names = []
            for step in tool_sequence:
                if isinstance(step, dict):
                    tool = step.get('tool', step.get('name', 'unknown'))
                    tool_names.append(tool)
                elif isinstance(step, str):
                    tool_names.append(step)
            
            # Build prompt for naming
            tools_str = " -> ".join(tool_names)
            prompt = (
                f"Given this tool sequence: {tools_str}\n\n"
                f"Generate a concise, descriptive name for this skill. "
                f"Use 2-4 words, Title Case. "
                f"Examples: 'File Analysis Pipeline', 'Web Search Summary', 'Code Review Flow'\n\n"
                f"Skill name:"
            )
            
            # Query model for name
            if hasattr(self.adapter, 'infer'):
                result = self.adapter.infer(prompt, max_tokens=50)
                name = result.raw_text if hasattr(result, 'raw_text') else str(result)
                
                # Clean up the name
                name = name.strip().strip('"').strip("'")
                
                # Validate name
                if name and len(name.split()) <= 5:
                    return name
            
            # Fallback: derive from tool names
            if tool_names:
                return f"{tool_names[0].replace('_', ' ').title()} Workflow"
            
            return "Automated Skill"
            
        except Exception as e:
            logger.error(f"[SkillCrystalliser] Name generation failed: {e}")
            return "Automated Skill"
    
    def _create_skill_description(
        self,
        tool_sequence: List[Dict[str, Any]],
        uses: int,
        avg_score: float
    ) -> str:
        """
        Create a human-readable description of a skill.
        
        Args:
            tool_sequence: List of tool calls
            uses: Number of times used
            avg_score: Average success score
        
        Returns:
            Description string
        """
        # Extract tool names
        tool_names = []
        for step in tool_sequence:
            if isinstance(step, dict):
                tool = step.get('tool', step.get('name', 'unknown'))
                tool_names.append(tool)
            elif isinstance(step, str):
                tool_names.append(step)
        
        tools_str = " → ".join(tool_names)
        
        return (
            f"Automated workflow using: {tools_str}. "
            f"Used {uses} times with {avg_score:.0%} success rate."
        )
    
    def get_crystallised_skills(self) -> List[Dict[str, Any]]:
        """
        Get all crystallised skills.
        
        Returns:
            List of skill dictionaries
        """
        entries = self.memory.semantic.get_by_category("named_skills")
        skills = []
        
        for entry in entries:
            try:
                data = json.loads(entry.value)
                skills.append({
                    "key": entry.key,
                    "name": data.get("name", "Unknown"),
                    "description": data.get("description", ""),
                    "uses": data.get("uses", 0),
                    "avg_score": data.get("avg_score", 0.0),
                    "confidence": entry.confidence
                })
            except json.JSONDecodeError:
                continue
        
        return skills
