#!/usr/bin/env python3
"""
AutoResearch Runner

Background loop that iterates skill variations against Mycelium metrics.

Architecture:
    1. Pull crystallised skills from MemoryInterface (SemanticMemory tier)
    2. For each underperforming skill, ask the LLM to propose improved variants
    3. Evaluate each variant on a small test-prompt suite
    4. Score responses using Mycelium resonance (capability + conduct spaces)
    5. If a variant outscores the baseline, persist it back to memory
    6. Loop with configurable interval until stopped

Usage:
    runner = AutoResearchRunner(memory_interface, lmstudio_base_url)
    runner.start()          # fire-and-forget in background
    runner.stop()           # graceful shutdown
    runner.get_status()     # current state + last N results
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

# Minimum score improvement required to accept a variant (absolute delta)
MIN_IMPROVEMENT = 0.05

# How many prompt variations to test per skill candidate
VARIANTS_PER_SKILL = 3

# Number of test prompts per variant evaluation
TEST_PROMPTS_PER_VARIANT = 3

# Default interval between research cycles (seconds)
DEFAULT_INTERVAL = 1800  # 30 minutes

# Max cycles before auto-stopping (0 = unlimited)
MAX_CYCLES = 0

# Standard test prompts used to benchmark skill quality
BENCHMARK_PROMPTS = [
    "Summarise what you can do for me in one sentence.",
    "How would you search for information about machine learning?",
    "What tools do you have available and when would you use each?",
    "Walk me through how you'd solve a multi-step research task.",
    "If I ask you to remember something important, what do you do?",
    "How do you handle a task that requires both reasoning and tool use?",
]


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SkillVariant:
    """A proposed variation of an existing skill description."""
    skill_name: str
    original_description: str
    variant_description: str
    variant_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class EvalResult:
    """Result of evaluating one variant on one test prompt."""
    variant_id: str
    prompt: str
    response: str
    latency_ms: float
    score: float           # 0–1, higher is better
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class ResearchCycleReport:
    """Summary of one completed research cycle."""
    cycle_id: str
    started_at: float
    finished_at: float
    skill_name: str
    baseline_score: float
    best_variant_score: float
    improved: bool
    best_variant_description: Optional[str] = None
    eval_results: List[EvalResult] = field(default_factory=list)

    def duration_s(self) -> float:
        return self.finished_at - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "skill": self.skill_name,
            "started_at": self.started_at,
            "duration_s": round(self.duration_s(), 2),
            "baseline_score": round(self.baseline_score, 4),
            "best_variant_score": round(self.best_variant_score, 4),
            "improved": self.improved,
            "best_variant": self.best_variant_description,
        }


# ── Runner ──────────────────────────────────────────────────────────────────

class AutoResearchRunner:
    """
    Background loop that iterates skill variations against Mycelium metrics.

    Lifecycle:
        start()   → launches _loop() as an asyncio Task
        stop()    → sets _stop event; loop exits after current cycle
        get_status() → returns running state + recent reports
    """

    def __init__(
        self,
        memory_interface: Any,           # MemoryInterface
        lmstudio_base_url: str = "http://localhost:1234",
        interval: float = DEFAULT_INTERVAL,
        model_name: str = "auto",        # "auto" → use whatever is loaded
    ) -> None:
        self._memory = memory_interface
        self._base_url = lmstudio_base_url
        self._interval = interval
        self._model_name = model_name

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._running = False
        self._cycles_completed = 0
        self._reports: List[ResearchCycleReport] = []   # last 50

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the research loop as a background asyncio Task."""
        if self._running:
            logger.warning("[AutoResearch] Already running — ignoring start()")
            return
        self._stop_event.clear()
        self._running = True
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._loop(), name="auto_research_loop")
        logger.info("[AutoResearch] Started background loop (interval=%.0fs)", self._interval)

    def stop(self) -> None:
        """Signal the loop to stop after the current cycle completes."""
        if not self._running:
            return
        self._stop_event.set()
        logger.info("[AutoResearch] Stop requested — will finish current cycle")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycles_completed": self._cycles_completed,
            "recent_reports": [r.to_dict() for r in self._reports[-10:]],
        }

    # ── Internal loop ─────────────────────────────────────────────────────

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                if MAX_CYCLES > 0 and self._cycles_completed >= MAX_CYCLES:
                    logger.info("[AutoResearch] MAX_CYCLES reached — stopping")
                    break
                try:
                    await self._run_cycle()
                except Exception as exc:
                    logger.error("[AutoResearch] Cycle error: %s", exc, exc_info=True)
                # Wait for interval OR early stop
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()),
                        timeout=self._interval,
                    )
                except asyncio.TimeoutError:
                    pass  # interval elapsed — continue
        finally:
            self._running = False
            logger.info("[AutoResearch] Loop exited after %d cycles", self._cycles_completed)

    async def _run_cycle(self, override_candidate: Optional[Dict[str, Any]] = None) -> None:
        cycle_id = str(uuid.uuid4())[:8]
        t0 = time.time()
        logger.info("[AutoResearch] Cycle %s starting", cycle_id)

        # 1. Pick a candidate from memory — or use the caller-supplied one
        if override_candidate is not None:
            candidate = override_candidate
        else:
            candidate = self._pick_skill_candidate()
        if not candidate:
            logger.info("[AutoResearch] No candidate found — skipping cycle")
            self._cycles_completed += 1
            return

        skill_name = candidate.get("name", "unknown")
        original_desc = candidate.get("description", "")
        candidate_category = candidate.get("_category", "named_skills")
        logger.info("[AutoResearch] Evaluating: %s (category=%s)", skill_name, candidate_category)

        # 2. Score baseline
        baseline_score = await self._score_skill_description(original_desc, skill_name)
        logger.info("[AutoResearch] Baseline score: %.4f", baseline_score)

        # 3. Generate variants
        variants = await self._generate_variants(skill_name, original_desc)

        # 4. Evaluate variants
        all_results: List[EvalResult] = []
        best_score = baseline_score
        best_variant: Optional[SkillVariant] = None

        for v in variants:
            v_score, v_results = await self._evaluate_variant(v)
            all_results.extend(v_results)
            logger.info(
                "[AutoResearch]   Variant %s score: %.4f (delta: %+.4f)",
                v.variant_id, v_score, v_score - baseline_score,
            )
            if v_score > best_score + MIN_IMPROVEMENT:
                best_score = v_score
                best_variant = v

        # 5. Persist best variant if it improved
        improved = best_variant is not None
        if improved and best_variant:
            self._persist_variant(skill_name, best_variant, category=candidate_category)
            logger.info(
                "[AutoResearch] Skill '%s' improved: %.4f → %.4f",
                skill_name, baseline_score, best_score,
            )

        # 6. Record report
        report = ResearchCycleReport(
            cycle_id=cycle_id,
            started_at=t0,
            finished_at=time.time(),
            skill_name=skill_name,
            baseline_score=baseline_score,
            best_variant_score=best_score,
            improved=improved,
            best_variant_description=best_variant.variant_description if best_variant else None,
            eval_results=all_results,
        )
        self._reports.append(report)
        if len(self._reports) > 50:
            self._reports = self._reports[-50:]
        self._cycles_completed += 1

        logger.info(
            "[AutoResearch] Cycle %s done in %.1fs — improved=%s",
            cycle_id, report.duration_s(), improved,
        )

    # ── Memory helpers ────────────────────────────────────────────────────

    def _pick_skill_candidate(self) -> Optional[Dict[str, Any]]:
        """
        Return the lowest-confidence entry from semantic memory across all categories.

        Prefers entries in 'named_skills' for backward compatibility, but will
        fall through to any other stored category so that ad-hoc research topics
        queued by the user are also eligible for improvement.
        """
        try:
            # Collect entries from all available categories
            all_entries: List[Any] = []
            categories_to_scan = ["named_skills", "auto_research", "research_topics"]
            for cat in categories_to_scan:
                try:
                    entries = self._memory.semantic.get_by_category(cat)
                    for e in entries:
                        setattr(e, "_category", cat)
                    all_entries.extend(entries)
                except Exception:
                    pass

            if not all_entries:
                return None

            # Pick entry with lowest confidence (most room for improvement)
            worst = min(all_entries, key=lambda e: getattr(e, "confidence", 1.0))
            raw = getattr(worst, "value", "{}")
            data = json.loads(raw) if isinstance(raw, str) else raw
            category = getattr(worst, "_category", "named_skills")
            name = (
                data.get("name")
                or data.get("topic")
                or (worst.key if hasattr(worst, "key") else "unknown")
            )
            description = data.get("description") or data.get("content") or str(raw)
            return {
                "name": name,
                "description": description,
                "score": getattr(worst, "confidence", 0.5),
                "_key": getattr(worst, "key", ""),
                "_category": category,
            }
        except Exception as exc:
            logger.error("[AutoResearch] Failed to fetch candidates: %s", exc)
            return None

    def _persist_variant(
        self,
        skill_name: str,
        variant: SkillVariant,
        category: str = "named_skills",
    ) -> None:
        """Update the entry in semantic memory with the improved variant."""
        try:
            import json as _json
            payload = _json.dumps({
                "name": skill_name,
                "description": variant.variant_description,
                "improved_by": "auto_research",
                "improved_at": time.time(),
                "previous": variant.original_description,
            })
            entry_key = f"ar_{skill_name.lower().replace(' ', '_')}"
            self._memory.semantic.update(
                category=category,
                key=entry_key,
                value=payload,
                confidence=0.87,
                source="auto_research",
            )
        except Exception as exc:
            logger.error("[AutoResearch] Failed to persist variant: %s", exc)

    # ── LLM helpers ───────────────────────────────────────────────────────

    def _get_lm_client(self) -> Any:
        """Return a cached OpenAI-compatible client for LM Studio."""
        if not hasattr(self, "_lm_client") or self._lm_client is None:
            try:
                from openai import OpenAI as _OpenAI
                self._lm_client = _OpenAI(base_url=self._base_url + "/v1", api_key="lm-studio")
            except ImportError:
                logger.error("[AutoResearch] openai package not available")
                raise
        return self._lm_client  # type: ignore[attr-defined]

    async def _lm_complete(self, prompt: str, max_tokens: int = 512) -> str:
        """Run a single completion against LM Studio (blocking, in executor)."""
        loop = asyncio.get_event_loop()

        def _call() -> str:
            client = self._get_lm_client()
            model = self._model_name if self._model_name != "auto" else "auto"
            kwargs: Dict[str, Any] = {
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }
            if model != "auto":
                kwargs["model"] = model
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

        return await loop.run_in_executor(None, _call)

    async def _generate_variants(
        self, skill_name: str, original: str
    ) -> List[SkillVariant]:
        """Ask the LLM to propose VARIANTS_PER_SKILL improved versions of anything."""
        prompt = (
            f"You are an expert at improving content quality.\n\n"
            f"Topic: {skill_name}\n"
            f"Current version:\n{original}\n\n"
            f"Generate {VARIANTS_PER_SKILL} improved versions. "
            f"Each should be clearer, more useful, more actionable, or more accurate than the current version. "
            f"Adapt your improvements to whatever the content represents — it may be a skill definition, "
            f"a behaviour description, a process, an explanation, or any other kind of text.\n"
            f"Return a JSON array of {VARIANTS_PER_SKILL} strings. "
            f"No other text, only the JSON array."
        )
        try:
            raw = await self._lm_complete(prompt, max_tokens=1024)
            # Parse JSON array from response
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON array in response")
            descriptions: List[str] = json.loads(raw[start:end])
            return [
                SkillVariant(
                    skill_name=skill_name,
                    original_description=original,
                    variant_description=str(d),
                )
                for d in descriptions[:VARIANTS_PER_SKILL]
            ]
        except Exception as exc:
            logger.error("[AutoResearch] Failed to generate variants: %s", exc)
            return []

    async def _score_skill_description(
        self, description: str, skill_name: str, memory_category: Optional[str] = None
    ) -> float:
        """
        Score any piece of content by:
        1. Memory confidence (if a stored entry exists for this topic)
        2. LLM quality rating (0-10)
        """
        scores: List[float] = []

        # Memory confidence — search the given category (or named_skills as fallback)
        search_category = memory_category or "named_skills"
        try:
            entries = self._memory.semantic.get_by_category(search_category)
            for e in entries:
                data_raw = getattr(e, "value", "{}")
                data = json.loads(data_raw) if isinstance(data_raw, str) else data_raw
                stored_name = data.get("name") or data.get("topic") or getattr(e, "key", "")
                if stored_name == skill_name:
                    conf = float(getattr(e, "confidence", 0.5))
                    scores.append(min(conf, 1.0))
                    break
        except Exception:
            pass

        # LLM self-rating — generic enough for any content type
        try:
            prompt = (
                f"Rate the quality of the following content on a scale from 0 to 10. "
                f"Consider clarity, usefulness, and accuracy. Return only the number.\n\n"
                f"Topic: {skill_name}\n"
                f"Content: {description}"
            )
            raw = await self._lm_complete(prompt, max_tokens=10)
            digits = "".join(c for c in raw if c.isdigit() or c == ".")
            if digits:
                llm_score = float(digits) / 10.0
                scores.append(min(max(llm_score, 0.0), 1.0))
        except Exception:
            pass

        return sum(scores) / len(scores) if scores else 0.5

    async def _evaluate_variant(
        self, variant: SkillVariant
    ) -> tuple[float, List[EvalResult]]:
        """Evaluate a variant on TEST_PROMPTS_PER_VARIANT benchmark prompts."""
        import random
        test_prompts = random.sample(BENCHMARK_PROMPTS, min(TEST_PROMPTS_PER_VARIANT, len(BENCHMARK_PROMPTS)))

        results: List[EvalResult] = []
        for prompt in test_prompts:
            t0 = time.time()
            try:
                system = (
                    f"You are IRIS, an AI assistant. "
                    f"Your capability: [{variant.skill_name}] {variant.variant_description}"
                )
                full_prompt = f"{system}\n\nUser: {prompt}"
                response = await self._lm_complete(full_prompt, max_tokens=200)
                latency = (time.time() - t0) * 1000
                score = self._score_response(response, prompt)
                results.append(EvalResult(
                    variant_id=variant.variant_id,
                    prompt=prompt,
                    response=response,
                    latency_ms=latency,
                    score=score,
                ))
            except Exception as exc:
                logger.debug("[AutoResearch] Eval prompt failed: %s", exc)
                results.append(EvalResult(
                    variant_id=variant.variant_id,
                    prompt=prompt,
                    response="",
                    latency_ms=0,
                    score=0.0,
                ))

        avg_score = sum(r.score for r in results) / len(results) if results else 0.0
        return avg_score, results

    def _score_response(self, response: str, prompt: str) -> float:
        """
        Heuristic response quality scorer.

        Criteria (each 0–1, averaged):
        - Length: penalise empty or excessively short (<20 chars)
        - Coherence: response mentions at least one keyword from the prompt
        - Actionability: response contains actionable language
        """
        if not response or len(response.strip()) < 10:
            return 0.0

        scores: List[float] = []

        # Length score (target: 50–300 chars)
        length = len(response)
        if length < 20:
            scores.append(0.2)
        elif length < 50:
            scores.append(0.5)
        elif length <= 300:
            scores.append(1.0)
        else:
            scores.append(0.8)  # slightly penalise verbosity

        # Keyword overlap (prompt words in response)
        prompt_words = set(w.lower() for w in prompt.split() if len(w) > 3)
        resp_lower = response.lower()
        if prompt_words:
            overlap = sum(1 for w in prompt_words if w in resp_lower) / len(prompt_words)
            scores.append(min(overlap * 2, 1.0))  # scale up: 50% overlap → 1.0

        # Actionability (presence of verbs associated with doing)
        action_words = ["can", "will", "would", "use", "search", "store", "find", "help", "run"]
        has_action = any(w in resp_lower for w in action_words)
        scores.append(1.0 if has_action else 0.3)

        return sum(scores) / len(scores) if scores else 0.5


# ── Singleton ────────────────────────────────────────────────────────────────

_runner_instance: Optional[AutoResearchRunner] = None


def get_auto_research_runner(
    memory_interface: Any = None,
    lmstudio_base_url: str = "http://localhost:1234",
    interval: float = DEFAULT_INTERVAL,
) -> AutoResearchRunner:
    """Return (or create) the AutoResearch runner singleton."""
    global _runner_instance
    if _runner_instance is None:
        if memory_interface is None:
            raise ValueError("memory_interface required for first-time creation")
        _runner_instance = AutoResearchRunner(
            memory_interface=memory_interface,
            lmstudio_base_url=lmstudio_base_url,
            interval=interval,
        )
    return _runner_instance
