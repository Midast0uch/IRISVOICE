"""
SkillSimulator — fast heuristic variant pre-filter for AutoResearch.

Trains from ResearchCycleReport history (in-memory, no DB read).
Predicts improvement probability for each variant before spending LLM tokens.

Usage:
    from backend.agent.skill_simulator import SkillSimulator
    sim = SkillSimulator()
    prob = sim.predict(variant_desc, original_desc, caducean_state)
    if prob >= 0.35:  # threshold
        evaluate_variant(variant)
"""

import logging
import re
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Action-word density lexicon
_ACTION_WORDS = frozenset(
    ["will", "can", "use", "search", "find", "run", "help", "do", "perform"]
)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


def _extract_features(
    variant: str, original: str, caducean_state: Optional[Dict[str, Any]]
) -> np.ndarray:
    """Return feature vector (shape 6, float32) for a variant."""
    v_tok = _tokenize(variant)
    o_tok = _tokenize(original)

    # 0. Length score (peak at 80-400 chars)
    length = len(variant)
    f_len = 1.0 if 80 <= length <= 400 else max(0.0, 1.0 - abs(length - 240) / 240)

    # 1. Action word density
    action_hits = sum(1 for w in v_tok if w in _ACTION_WORDS)
    f_action = min(1.0, action_hits / max(len(v_tok), 1) * 5)

    # 2. Keyword overlap with original (lower = higher improvement potential)
    v_set = set(v_tok)
    o_set = set(o_tok)
    overlap = len(v_set & o_set) / max(len(v_set | o_set), 1)
    f_overlap = 1.0 - overlap  # invert: less overlap = higher score

    # 3. Novel word ratio
    novel = v_set - o_set
    f_novel = min(1.0, len(novel) / max(len(v_set), 1) * 3)

    # 4. EML at eval time
    eml = float(caducean_state.get("eml", 1.0)) if caducean_state else 1.0
    f_eml = min(1.0, max(0.0, eml / 2.0))

    # 5. x/y balance ratio
    x = float(caducean_state.get("x", 0.5)) if caducean_state else 0.5
    y = float(caducean_state.get("y", 0.5)) if caducean_state else 0.5
    denom = x + y
    f_balance = x / denom if denom > 0 else 0.5

    return np.array([f_len, f_action, f_overlap, f_novel, f_eml, f_balance], dtype=np.float64)


class SkillSimulator:
    """
    Lightweight heuristic predictor for skill variant improvement probability.

    Auto-fits after each cycle once ≥10 reports exist.
    Falls back to 0.5 (no filtering) when insufficient data.
    """

    MIN_TRAIN_REPORTS = 10
    PREDICTION_FEATURES = 6

    def __init__(self) -> None:
        self._coeffs: Optional[np.ndarray] = None  # shape (7,) — 6 features + bias
        self._reports: List[Dict[str, Any]] = []

    # ── Training ────────────────────────────────────────────────────────

    def add_report(self, report: Dict[str, Any]) -> None:
        """Append a ResearchCycleReport-like dict for future training."""
        self._reports.append(report)
        if len(self._reports) >= self.MIN_TRAIN_REPORTS and self._coeffs is None:
            self.fit_from_reports()

    def fit_from_reports(self, reports: Optional[List[Dict[str, Any]]] = None) -> bool:
        """
        Fit coefficients from historical cycle reports.
        Each report must have keys: variant, original, caducean_state, improved (bool).
        Returns True if fit succeeded.
        """
        data = reports if reports is not None else self._reports
        if len(data) < self.MIN_TRAIN_REPORTS:
            logger.info("[SkillSimulator] skip fit — only %d reports", len(data))
            return False

        X = np.zeros((len(data), self.PREDICTION_FEATURES + 1), dtype=np.float64)
        y = np.zeros(len(data), dtype=np.float64)
        for i, rep in enumerate(data):
            X[i, : self.PREDICTION_FEATURES] = _extract_features(
                rep.get("variant", ""),
                rep.get("original", ""),
                rep.get("caducean_state", None),
            )
            X[i, self.PREDICTION_FEATURES] = 1.0  # bias term
            y[i] = 1.0 if rep.get("improved", False) else 0.0

        # Ridge regression (lstsq with mild L2 via pseudo-inverse)
        try:
            self._coeffs, *_ = np.linalg.lstsq(X, y, rcond=None)
            logger.info("[SkillSimulator] fit complete on %d reports", len(data))
            return True
        except Exception as exc:
            logger.warning("[SkillSimulator] fit failed: %s", exc)
            return False

    # ── Inference ───────────────────────────────────────────────────────

    @property
    def is_trained(self) -> bool:
        return self._coeffs is not None

    def predict(
        self,
        variant: str,
        original: str,
        caducean_state: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Predict improvement probability [0.0, 1.0]."""
        if self._coeffs is None:
            return 0.5

        feats = _extract_features(variant, original, caducean_state)
        x = np.append(feats, 1.0)  # add bias
        raw = float(np.dot(x, self._coeffs))
        # clamp to [0, 1] with soft sigmoid
        return float(1.0 / (1.0 + np.exp(-raw)))

    # ── Convenience ─────────────────────────────────────────────────────

    def score_variants(
        self,
        variants: List[str],
        original: str,
        caducean_state: Optional[Dict[str, Any]] = None,
    ) -> List[float]:
        """Score a batch of variants."""
        return [self.predict(v, original, caducean_state) for v in variants]
