"""
Recall Decoder — parse <recall .../> grammar ops and resolve them against
the live memory brain. Zero new retrieval logic: every resolver delegates to
an already-existing memory primitive.

Grammar (all self-closing):
    <recall coord="[x,y,z]" k=5/>            — Mycelium coordinate neighborhood
    <recall pin="name"/>                      — Named landmark
    <recall semantic="query" gate=2/>         — Episodic + semantic chunks
    <recall predict tools=3/>                 — BehavioralPredictor next-step hints
    <recall route depth=3/>                   — Immortus CoordinateRoute candidates
    <recall similar task="..."/>              — Resonance-ranked past episodes
    <recall skill query="..."/>               — Registered action modules

Cold-start sentinels: when DB is empty or Mycelium is absent, each resolver
returns a ResolvedSpan with status="empty" or status="sparse" plus a hint
instead of raising or returning blank content. The agent can act on these.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RecallOp:
    """One parsed <recall .../> op from model output."""
    op_type: str           # coord | pin | semantic | predict | route | similar | skill
    args: Dict[str, Any]   # key/value pairs from the tag attributes
    raw: str               # original tag text (for provenance logging)


@dataclass
class ResolvedSpan:
    """The result of resolving one RecallOp."""
    op: RecallOp
    content: str
    confidence: float = 1.0
    source: str = ""
    status: str = "ok"    # ok | empty | sparse | error

    def to_prompt_span(self) -> str:
        """Wrap for injection into Phase A as an assistant-turn span."""
        src = f' src="{self.source}"' if self.source else ""
        conf = f' confidence="{self.confidence:.2f}"'
        stat = f' status="{self.status}"' if self.status != "ok" else ""
        return (
            f'<recalled op="{self.op.op_type}"{src}{conf}{stat}>\n'
            f'{self.content}\n'
            f'</recalled>'
        )

    @property
    def is_empty(self) -> bool:
        return self.status in ("empty", "sparse")


# Sentinel templates for cold-start / missing data
def _empty_span(op: RecallOp, hint: str, suggest: str = "bootstrap") -> ResolvedSpan:
    return ResolvedSpan(
        op=op,
        content=f"[no memory — hint:{hint} suggest:{suggest}]",
        confidence=0.0,
        source="sentinel",
        status="empty",
    )

def _sparse_span(op: RecallOp, confidence: float, hint: str = "") -> ResolvedSpan:
    return ResolvedSpan(
        op=op,
        content=f"[sparse memory — confidence:{confidence:.2f} hint:{hint}]",
        confidence=confidence,
        source="sentinel",
        status="sparse",
    )

def _error_span(op: RecallOp, exc: Exception) -> ResolvedSpan:
    logger.debug("[RecallDecoder] %s op failed: %s", op.op_type, exc)
    return ResolvedSpan(
        op=op,
        content=f"[recall error — {type(exc).__name__}]",
        confidence=0.0,
        source="error",
        status="error",
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Matches <recall key="val" key2=val .../> — both quoted and unquoted attr values
_RECALL_RE = re.compile(
    r'<recall\s+([^/]*?)/\s*>',
    re.DOTALL,
)
_ATTR_RE = re.compile(
    r'(\w+)\s*=\s*(?:"([^"]*?)"|\'([^\']*?)\'|([^\s/>]+))'
)

_VALID_OPS = frozenset({"coord", "pin", "semantic", "predict", "route", "similar", "skill"})


def parse_recall_ops(text: str) -> List[RecallOp]:
    """Extract all <recall .../> ops from a text block. Never raises."""
    ops: List[RecallOp] = []
    for m in _RECALL_RE.finditer(text):
        raw = m.group(0)
        attrs_str = m.group(1)
        attrs: Dict[str, Any] = {}
        for a in _ATTR_RE.finditer(attrs_str):
            key = a.group(1)
            val = a.group(2) or a.group(3) or a.group(4) or ""
            # coerce numeric-looking values
            if re.fullmatch(r'\d+', val):
                attrs[key] = int(val)
            elif re.fullmatch(r'\d+\.\d+', val):
                attrs[key] = float(val)
            else:
                attrs[key] = val

        # first key determines op_type (e.g. coord=, pin=, semantic=, ...)
        op_type = next((k for k in attrs if k in _VALID_OPS), None)
        if op_type is None:
            # fallback: check if any known op keyword appears as a bare attribute
            # e.g. <recall predict tools=3/> where 'predict' has no value
            bare_m = re.search(r'\b(' + '|'.join(_VALID_OPS) + r')\b', attrs_str)
            if bare_m:
                op_type = bare_m.group(1)
                # parse remaining attrs only
                attrs = {k: v for k, v in attrs.items() if k != op_type}
            else:
                logger.debug("[RecallDecoder] unrecognised recall tag: %s", raw)
                continue

        ops.append(RecallOp(op_type=op_type, args=attrs, raw=raw))
    return ops


# ---------------------------------------------------------------------------
# NBL fingerprint (for cache invalidation)
# ---------------------------------------------------------------------------

def _nbl_fingerprint(nbl_str: Optional[str]) -> str:
    if not nbl_str:
        return "empty"
    # first line of NBL encodes gate + coord — changes when coordinates shift
    first_line = nbl_str.split("\n")[0][:80]
    return hashlib.md5(first_line.encode(), usedforsecurity=False).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

class RecallDecoder:
    """
    Resolves RecallOps against existing memory primitives.

    Args:
        memory_interface:  MemoryInterface instance (optional — all resolvers
                           degrade gracefully to cold-start sentinels when None).
        session_id:        Current session identifier.
        nbl_str:           Current NBL string (used to invalidate LRU cache on
                           coordinate shifts).
        skills_loader:     SkillsLoader (optional — powers <recall skill/>).
    """

    _MAX_CACHE = 256   # max cached resolutions per decoder instance

    def __init__(
        self,
        memory_interface: Optional[Any] = None,
        session_id: str = "default",
        nbl_str: Optional[str] = None,
        skills_loader: Optional[Any] = None,
        pin_store: Optional[Any] = None,
    ) -> None:
        self._mem = memory_interface
        self._session_id = session_id
        self._nbl_fp = _nbl_fingerprint(nbl_str)
        self._skills = skills_loader
        self._pin_store = pin_store
        self._cache: Dict[Tuple, ResolvedSpan] = {}

    def update_nbl(self, nbl_str: str) -> None:
        """Call when coordinates shift so stale cache entries are evicted."""
        new_fp = _nbl_fingerprint(nbl_str)
        if new_fp != self._nbl_fp:
            self._cache.clear()
            self._nbl_fp = new_fp

    def invalidate_cache(self) -> None:
        """Clear the resolver cache. Call after pin writes so stale results aren't reused."""
        self._cache.clear()

    def set_pin_store(self, pin_store: Any) -> None:
        """Wire a PinStore after construction (used by AgentKernel.set_memory_interface)."""
        self._pin_store = pin_store
        self._cache.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, op: RecallOp) -> ResolvedSpan:
        """Resolve a single RecallOp. Returns a sentinel span on any error."""
        cache_key = (op.op_type, tuple(sorted(op.args.items())), self._nbl_fp)
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolver = {
            "coord":    self._resolve_coord,
            "pin":      self._resolve_pin,
            "semantic": self._resolve_semantic,
            "predict":  self._resolve_predict,
            "route":    self._resolve_route,
            "similar":  self._resolve_similar,
            "skill":    self._resolve_skill,
        }.get(op.op_type)

        if resolver is None:
            span = _empty_span(op, hint=f"unknown op {op.op_type!r}")
        else:
            try:
                span = resolver(op)
            except Exception as exc:
                span = _error_span(op, exc)

        # only cache successful / sparse resolutions (not errors — they may be transient)
        if span.status != "error":
            if len(self._cache) >= self._MAX_CACHE:
                # evict oldest entry (first-inserted, dict ordering in Python 3.7+)
                next(iter(self._cache))  # peek
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = span

        return span

    def resolve_all(self, ops: List[RecallOp]) -> List[ResolvedSpan]:
        """Resolve a list of ops, returning in the same order."""
        return [self.resolve(op) for op in ops]

    def format_spans_for_phase_a(self, spans: List[ResolvedSpan]) -> str:
        """
        Format resolved spans as the assistant-turn memory block injected
        at the start of Phase A.  Empty/sparse spans are included so the
        model can act on probe/decompose suggestions.
        """
        if not spans:
            return ""
        parts = [s.to_prompt_span() for s in spans]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Resolvers
    # ------------------------------------------------------------------

    def _resolve_coord(self, op: RecallOp) -> ResolvedSpan:
        """Navigate Mycelium coordinate neighborhood."""
        if self._mem is None or getattr(self._mem, '_mycelium', None) is None:
            return _empty_span(op, hint="no_mycelium", suggest="probe")

        myc = self._mem._mycelium
        k = op.args.get("k", 5)
        coord_str = op.args.get("coord", "")

        try:
            path = myc._navigator.navigate_from_task(
                task_text=coord_str or self._session_id,
                session_id=self._session_id,
                max_hops=min(int(k), 8),
            )
            if not path or not path.nodes:
                return _empty_span(op, hint="no_nodes", suggest="probe")

            confidence = path.cumulative_score / max(len(path.nodes), 1)
            lines = [f"- [{n.space}] {n.label} (conf={n.confidence:.2f})" for n in path.nodes[:int(k)]]
            return ResolvedSpan(
                op=op,
                content="\n".join(lines),
                confidence=min(confidence, 1.0),
                source="mycelium/navigator",
            )
        except Exception:
            # try navigate_all_spaces as cold-start fallback
            try:
                nodes = myc._navigator.navigate_all_spaces(self._session_id)
                if not nodes:
                    return _empty_span(op, hint="empty_graph", suggest="probe")
                lines = [f"- [{n.space}] {n.label} (conf={n.confidence:.2f})" for n in nodes[:int(k)]]
                avg_conf = sum(n.confidence for n in nodes[:int(k)]) / max(len(nodes[:int(k)]), 1)
                return _sparse_span(op, confidence=avg_conf, hint="cold_start_fallback") if avg_conf < 0.5 else ResolvedSpan(
                    op=op, content="\n".join(lines), confidence=avg_conf,
                    source="mycelium/navigator/all_spaces",
                )
            except Exception as exc2:
                return _error_span(op, exc2)

    def _resolve_pin(self, op: RecallOp) -> ResolvedSpan:
        """
        Resolve a pin recall op against the mycelium_pins table.

        Supported forms:
          <recall pin="Title"/>                  — exact title lookup
          <recall pin query="text"/>             — ranked search across title/content/tags
          <recall pin file="path/X.md"/>         — all checkpoint pins for a file
          <recall pin tags="api,auth"/>          — pins matching any of the tags
          <recall pin query="text" depth=2/>     — ranked search + 1-hop linked pins

        Falls back to the legacy semantic-store lookup when no PinStore is wired,
        so existing callers continue to work during rollout.
        """
        # Branch 1: file-checkpoint recovery (pin file="path")
        file_path = op.args.get("file", "")
        if file_path and self._pin_store is not None:
            try:
                pins = self._pin_store.list_checkpoints_for_file(file_path, limit=20)
                if not pins:
                    return _empty_span(op, hint=f"no_checkpoints:{file_path}", suggest="decompose")
                content = "\n\n---\n\n".join(p.to_markdown() for p in pins)
                return ResolvedSpan(
                    op=op, content=content, confidence=0.9,
                    source=f"pin_store/checkpoints/{file_path}",
                )
            except Exception as exc:
                return _error_span(op, exc)

        # Branch 2: tags filter (pin tags="api,auth")
        tags_arg = op.args.get("tags", "")
        if tags_arg and self._pin_store is not None:
            wanted = [t.strip().lower() for t in str(tags_arg).split(",") if t.strip()]
            try:
                # Use search to leverage tags weight; pass each tag as a query and merge
                matched: Dict[str, Tuple[Any, float]] = {}
                for tag in wanted:
                    for pin, score in self._pin_store.search(tag, limit=20):
                        prev = matched.get(pin.pin_id)
                        if prev is None or score > prev[1]:
                            matched[pin.pin_id] = (pin, score)
                if not matched:
                    return _empty_span(op, hint=f"no_pins_for_tags:{tags_arg}", suggest="decompose")
                ranked = sorted(matched.values(), key=lambda t: t[1], reverse=True)[:8]
                content = "\n\n---\n\n".join(p.to_markdown() for p, _ in ranked)
                avg = sum(s for _, s in ranked) / len(ranked)
                return ResolvedSpan(
                    op=op, content=content,
                    confidence=min(1.0, avg / 100.0),  # weights sum ~100 — normalize
                    source="pin_store/tags",
                )
            except Exception as exc:
                return _error_span(op, exc)

        # Branch 3: ranked query (pin query="text")
        query = op.args.get("query", "")
        if query and self._pin_store is not None:
            try:
                k = min(int(op.args.get("k", 4)), 8)
                ranked = self._pin_store.search(query, limit=k)
                # Optional 1-hop link expansion
                depth = int(op.args.get("depth", 0))
                if depth > 0 and ranked:
                    seen_ids = {p.pin_id for p, _ in ranked}
                    for top_pin, _ in list(ranked):
                        for linked in self._pin_store.linked(top_pin.pin_id, depth=depth):
                            if linked.pin_id not in seen_ids:
                                seen_ids.add(linked.pin_id)
                                ranked.append((linked, 0.0))  # appended without score boost
                if not ranked:
                    return _empty_span(op, hint=f"no_pins_for_query:{query}", suggest="decompose")
                content = "\n\n---\n\n".join(p.to_markdown() for p, _ in ranked)
                top_score = ranked[0][1]
                return ResolvedSpan(
                    op=op, content=content,
                    confidence=min(1.0, top_score / 100.0),
                    source="pin_store/query",
                )
            except Exception as exc:
                return _error_span(op, exc)

        # Branch 4: exact title lookup (pin="Title")
        name = op.args.get("pin", "")
        if name and self._pin_store is not None:
            try:
                pin = self._pin_store.get_by_title(name)
                if pin is not None:
                    return ResolvedSpan(
                        op=op, content=pin.to_markdown(),
                        confidence=1.0, source=f"pin_store/title/{name}",
                    )
            except Exception as exc:
                return _error_span(op, exc)

        # Branch 5: legacy semantic-store fallback (pre-PinStore behaviour)
        if self._mem is not None and name:
            try:
                for category in ("named_skills", "domain_knowledge", "tool_proficiency", "cognitive_model"):
                    entry = self._mem.semantic.get(category, name)
                    if entry:
                        return ResolvedSpan(
                            op=op,
                            content=f"[{category}:{name}] {entry.value}",
                            confidence=entry.confidence,
                            source=f"semantic/{category}",
                        )
            except Exception as exc:
                return _error_span(op, exc)

        if not (name or query or file_path or tags_arg):
            return _empty_span(op, hint="no_pin_args")
        return _empty_span(op, hint=f"pin_not_found:{name or query or file_path or tags_arg}",
                           suggest="decompose")

    def _resolve_semantic(self, op: RecallOp) -> ResolvedSpan:
        """Retrieve resonance-weighted episodic context chunks."""
        if self._mem is None:
            return _empty_span(op, hint="no_memory", suggest="bootstrap")

        query = op.args.get("semantic", "")
        limit = min(op.args.get("k", 4), 8)

        if not query:
            return _empty_span(op, hint="no_query")

        try:
            chunks = self._mem.episodic.retrieve_context_chunks(
                query=query,
                session_id=self._session_id,
                limit=int(limit),
                min_similarity=0.2,
            )
            if not chunks:
                return _empty_span(op, hint="no_chunks", suggest="decompose")

            return ResolvedSpan(
                op=op,
                content="\n---\n".join(chunks),
                confidence=0.7,
                source="episodic/chunks",
            )
        except Exception as exc:
            return _error_span(op, exc)

    def _resolve_predict(self, op: RecallOp) -> ResolvedSpan:
        """Return BehavioralPredictor next-step hints."""
        if self._mem is None or getattr(self._mem, '_mycelium', None) is None:
            return _empty_span(op, hint="no_mycelium", suggest="probe")

        top_n = min(op.args.get("tools", 3), 6)
        myc = self._mem._mycelium

        try:
            from backend.memory.mycelium.interpreter import BehavioralPredictor
            predictor = BehavioralPredictor()
            # Get active node IDs from current session
            active_nodes = list(myc._registry.get_active(self._session_id))
            if not active_nodes:
                return _sparse_span(op, confidence=0.1, hint="no_active_nodes")

            predictions = predictor.predict(
                session_id=self._session_id,
                current_node_ids=active_nodes,
                task_class="",
                completed_tools=[],
                conn=myc._store._conn,
            )
            if not predictions:
                return _empty_span(op, hint="no_predictions", suggest="probe")

            return ResolvedSpan(
                op=op,
                content="Predicted next steps: " + ", ".join(predictions[:int(top_n)]),
                confidence=0.6,
                source="mycelium/predictor",
            )
        except Exception as exc:
            return _error_span(op, exc)

    def _resolve_route(self, op: RecallOp) -> ResolvedSpan:
        """Return Immortus SpeculativeRouter candidate routes."""
        try:
            from backend.agent.immortus.router import SpeculativeRouter
            from backend.agent.immortus.temporal import TemporalCoordinate
            from backend.agent.immortus.route import CoordinateRoute
        except ImportError as exc:
            return _error_span(op, exc)

        depth = op.args.get("depth", 3)

        if self._mem is None or getattr(self._mem, '_mycelium', None) is None:
            return _empty_span(op, hint="no_mycelium", suggest="probe")

        try:
            myc = self._mem._mycelium
            temporal = TemporalCoordinate(momentum=0.8, drift=0.1, identifier_depth=int(depth))
            router = SpeculativeRouter()

            # Use navigate_all_spaces as a lightweight entry point
            all_nodes = myc._navigator.navigate_all_spaces(self._session_id)
            if not all_nodes:
                return _empty_span(op, hint="no_graph_nodes", suggest="probe")

            # Build a minimal graph proxy for the router
            class _MiniGraph:
                def __init__(self, nodes):
                    self._nodes = {n.node_id: n for n in nodes}
                def nodes(self):
                    return list(self._nodes.values())
                def edges_from(self, node_id):
                    return []

            entry = all_nodes[0]
            objective = all_nodes[-1] if len(all_nodes) > 1 else all_nodes[0]
            graph = _MiniGraph(all_nodes)
            routes = router.find_candidate_routes(
                entry=entry,
                objective=objective,
                temporal=temporal,
                thread_id=self._session_id,
                graph=graph,
                max_routes=int(depth),
            )
            if not routes:
                # cold-start: synthetic stub
                return _sparse_span(op, confidence=0.1, hint="no_routes_fresh_graph")

            lines = [
                f"Route {i+1}: score={r.score:.2f} steps={len(r.steps)} pheromone={r.pheromone_weight:.2f}"
                for i, r in enumerate(routes)
            ]
            top_conf = routes[0].score if routes else 0.0
            return ResolvedSpan(
                op=op,
                content="\n".join(lines),
                confidence=top_conf,
                source="immortus/speculative_router",
            )
        except Exception as exc:
            return _error_span(op, exc)

    def _resolve_similar(self, op: RecallOp) -> ResolvedSpan:
        """Return resonance-ranked similar past episodes."""
        if self._mem is None:
            return _empty_span(op, hint="no_memory", suggest="bootstrap")

        task = op.args.get("task", op.args.get("similar", ""))
        limit = min(op.args.get("k", 3), 6)

        if not task:
            return _empty_span(op, hint="no_task_query")

        try:
            episodes = self._mem.episodic.retrieve_similar(
                task=task,
                limit=int(limit),
                min_score=0.0,   # include failures — they have negative resonance signal
            )
            if not episodes:
                return _empty_span(op, hint="no_similar_episodes", suggest="decompose")

            parts = []
            for ep in episodes:
                outcome = "✓" if ep.get("outcome_score", 0) >= 0.5 else "✗"
                sim = ep.get("similarity", 0)
                parts.append(
                    f"{outcome} [{sim:.2f}] {ep.get('task_summary','?')}"
                    f" — tools: {', '.join(ep.get('tool_sequence', []))}"
                )
            avg_conf = sum(ep.get("outcome_score", 0) for ep in episodes) / len(episodes)
            return ResolvedSpan(
                op=op,
                content="\n".join(parts),
                confidence=avg_conf,
                source="episodic/similar",
            )
        except Exception as exc:
            return _error_span(op, exc)

    def _resolve_skill(self, op: RecallOp) -> ResolvedSpan:
        """Search registered action modules by query string."""
        query = op.args.get("query", op.args.get("skill", "")).lower()

        # Try SkillsLoader (SKILL.md based modules)
        if self._skills is not None:
            try:
                skills_dict = (
                    self._skills._skills
                    if hasattr(self._skills, "_skills")
                    else self._skills.reload() or {}
                )
                matches = [
                    (name, content)
                    for name, content in skills_dict.items()
                    if not query or query in name.lower() or query in content.lower()
                ]
                if matches:
                    parts = [f"## {name}\n{content[:300]}" for name, content in matches[:4]]
                    return ResolvedSpan(
                        op=op,
                        content="\n\n".join(parts),
                        confidence=0.9,
                        source="skills/loader",
                    )
            except Exception as exc:
                logger.debug("[RecallDecoder] skills loader failed: %s", exc)

        # Fallback: SkillRegistry (runtime-registered callable skills)
        # No search method exists yet — use list_registered_skills()
        # (a search() method will be added to SkillRegistry in a separate step)
        return _empty_span(op, hint="no_skills_match", suggest="create_skill")
