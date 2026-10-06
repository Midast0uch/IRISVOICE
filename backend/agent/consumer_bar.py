"""Per-consumer enforcement bar record (REQ-31 AC31.5/AC31.6, T52).

The EVIDENCE TRAIL behind every enforcement decision: for each consumer, the
measured bar (rows, precision, ECE) that justified its flip OR its continued
shadow status.

Two things this exists to make impossible:
  * "why is this consumer enforced?" being unanswerable — the record names the
    rows, precision and ECE behind each decision; and
  * a flip measured at a SUPERSEDED configuration quietly surviving — the
    record stores the configuration it was measured at, so AC31.6's
    "no flip measured at a superseded configuration shall stand" is checkable
    rather than assumed.

The bar itself is TG-7's (authoritative per Decision C): >= 100 rows AND
precision >= 0.90 AND ECE within bound. A consumer that fails ANY clause stays
in SHADOW with the gap recorded — never a partial flip (AC18.4, AC22.4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("consumer_bar")

# The repo-relative record. A temp path would be invisible to the next run.
BAR_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "benchmarks" / "consumer_bar_record.json"
)

# TG-7's bar (Decision C: the authoritative enforcement gate).
MIN_ROWS = 100
MIN_PRECISION = 0.90
# REQ-18 AC18.4: the ECE bound a flip must ALSO clear. A consumer with no
# measured ECE cannot be flipped on precision alone.
MAX_ECE = 0.05

# THE HARDENED BAR (2026-10-05, Oracle Stage A). The three clauses above were
# measured to pass on evidence that proves nothing: the same input rescored many
# times counted as many rows (web_intent 654 distinct of 2690; presentation 2
# distinct of 918), a reference with one class passes any precision, and ECE on
# raw confidences says nothing about whether confidence RANKS errors. The extra
# clauses are read from an OUT-OF-FOLD calibration (scripts/fit_oracle_calibration):
#   * the reference needs both classes, the minority at least 5% of rows;
#   * error-detection AUROC >= 0.65 (0.5 is chance);
#   * a calibrated threshold exists: precision >= MIN_PRECISION there, with its
#     Wilson 95% lower bound >= MIN_WILSON_LB, on >= MIN_ROWS_ABOVE distinct rows.
MIN_MINORITY = 0.05
MIN_AUROC = 0.65
MIN_ROWS_ABOVE = 50
MIN_WILSON_LB = 0.85


@dataclass(frozen=True)
class ConsumerBar:
    consumer_id: str
    rows: int
    precision: float
    ece: Optional[float]
    status: str          # "enforced" | "shadow"
    gap: str = ""        # why it is NOT enforced ("" when enforced)
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def flipped(self) -> bool:
        return self.status == "enforced"


def derive_status(
    rows: int,
    precision: float,
    ece: Optional[float],
    *,
    min_rows: int = MIN_ROWS,
    min_precision: float = MIN_PRECISION,
    max_ece: float = MAX_ECE,
    honest: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """``(status, gap)`` for one consumer's measurements.

    Returns ``("enforced", "")`` only when EVERY clause holds. Otherwise
    ``("shadow", <the first missing clause>)`` — the gap is recorded, never
    rounded up into a flip (AC22.4: no enforcement below the bar).

    ``honest`` is the out-of-fold measurement (``fit_consumer`` in
    scripts/fit_oracle_calibration.py). When given, the HARDENED bar applies and
    ``rows`` / ``precision`` / ``ece`` are ignored in favour of its numbers. The
    report and ``bar_rows`` always pass it. Without it only the three legacy
    clauses run - kept because contract tests pin that shape, not because it is
    enough to flip a consumer.
    """
    if honest is not None:
        return _derive_hardened(honest, min_rows, min_precision, max_ece)
    if rows < min_rows:
        return "shadow", f"rows {rows} < {min_rows}"
    if precision < min_precision:
        return "shadow", f"precision {precision:.3f} < {min_precision:.2f}"
    if ece is None:
        # AC18.4: precision alone is NOT enough — an uncalibrated distribution
        # may not be enforced on.
        return "shadow", "ECE not measured (precision alone cannot flip)"
    if ece > max_ece:
        return "shadow", f"ECE {ece:.3f} > {max_ece:.2f}"
    return "enforced", ""


def _derive_hardened(
    h: Dict[str, Any], min_rows: int, min_precision: float, max_ece: float,
) -> Tuple[str, str]:
    """The hardened clauses, in order; the first one missing is the gap."""
    n = int(h.get("rows_distinct") or 0)
    if n < min_rows:
        return "shadow", f"distinct rows {n} < {min_rows}"
    cls = h.get("classes") or {}
    a, b = int(cls.get("correct") or 0), int(cls.get("wrong") or 0)
    if a == 0 or b == 0:
        return "shadow", (
            f"reference has one class only (correct {a}, wrong {b}): "
            "precision and AUROC prove nothing"
        )
    minority = min(a, b) / (a + b)
    if minority < MIN_MINORITY:
        return "shadow", f"minority class {minority:.1%} < {MIN_MINORITY:.0%}"
    oof = h.get("oof") or {}
    auroc = oof.get("auroc")
    if auroc is None or auroc < MIN_AUROC:
        return "shadow", f"oof AUROC {auroc} < {MIN_AUROC} (confidence does not rank errors)"
    t = h.get("threshold")
    above = int(h.get("rows_above") or 0)
    prec, wlb = oof.get("precision_at_t"), oof.get("wilson_lb")
    if t is None:
        return "shadow", (
            f"no calibrated threshold gives precision >= {min_precision:.2f} "
            f"(Wilson LB >= {MIN_WILSON_LB}) on >= {MIN_ROWS_ABOVE} distinct rows"
        )
    # A threshold in the file is not trusted on its own: re-check what it implies.
    if above < MIN_ROWS_ABOVE:
        return "shadow", f"rows above threshold {above} < {MIN_ROWS_ABOVE}"
    if prec is None or prec < min_precision:
        return "shadow", f"oof precision at threshold {prec} < {min_precision:.2f}"
    if wlb is None or wlb < MIN_WILSON_LB:
        return "shadow", f"Wilson lower bound {wlb} < {MIN_WILSON_LB}"
    ece = oof.get("ece")
    if ece is None or ece > max_ece:
        return "shadow", f"oof calibrated ECE {ece} > {max_ece:.2f}"
    return "enforced", ""


def build_bar(
    consumer_id: str,
    measured: Dict[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> ConsumerBar:
    """One consumer's bar record from its measured numbers."""
    rows = int(measured.get("rows") or 0)
    precision = float(measured.get("precision") or 0.0)
    ece_raw = measured.get("ece")
    ece = None if ece_raw is None else float(ece_raw)
    status, gap = derive_status(rows, precision, ece, honest=measured.get("honest"))
    return ConsumerBar(
        consumer_id=consumer_id, rows=rows, precision=round(precision, 4),
        ece=None if ece is None else round(ece, 4), status=status, gap=gap,
        config=dict(config or {}),
    )


def record_bars(
    measured: Dict[str, Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, ConsumerBar]:
    """Build and persist the bar record for every measured consumer."""
    record = {
        cid: build_bar(cid, m, config=config)
        for cid, m in (measured or {}).items()
    }
    save_bar_record(record)
    return record


def save_bar_record(record: Dict[str, ConsumerBar], path: Optional[Path] = None) -> None:
    """Persist the record. Best-effort — never raises."""
    target = Path(path) if path else BAR_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {cid: asdict(bar) for cid, bar in record.items()},
                indent=2, sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 — recording is best-effort
        logger.warning("consumer_bar: write failed (%r)", e)


def load_bar_record(path: Optional[Path] = None) -> Dict[str, ConsumerBar]:
    """Read the record. An absent/unreadable file is EMPTY, never fatal."""
    target = Path(path) if path else BAR_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, ConsumerBar] = {}
    for cid, payload in (raw or {}).items():
        try:
            out[cid] = ConsumerBar(**payload)
        except Exception:  # noqa: BLE001 — a malformed row is skipped
            continue
    return out


def superseded_flips(
    record: Dict[str, ConsumerBar],
    deployed: Dict[str, Any],
) -> list:
    """AC31.6: consumers ENFORCED on a configuration that has since moved.

    Returns their ids. A flip is only valid for the configuration it was
    measured at; when the deployed backend/cap/variant differs, the flip must
    be re-validated (or reverted to shadow) rather than silently standing.
    """
    out: list = []
    for cid, bar in (record or {}).items():
        if not bar.flipped:
            continue
        measured_at = bar.config or {}
        for key in ("candidate_cap", "backend_id", "variant"):
            if key in measured_at and key in deployed:
                if measured_at[key] != deployed[key]:
                    out.append(cid)
                    break
    return sorted(out)
